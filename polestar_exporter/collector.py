"""Maps unofficial-polestar-api vehicle data onto Prometheus metrics."""

from __future__ import annotations

import logging
import time
from typing import Protocol

from polestar_api.models.availability import (
    AvailabilityStatus,
    UnavailableReason,
    UsageMode,
)
from polestar_api.models.battery import ChargingStatus, ChargingType
from polestar_api.models.exterior import LockStatus, OpenStatus
from polestar_api.models.health import (
    BrakeFluidLevelWarning,
    LowVoltageBatteryWarning,
    ServiceWarning,
    TyrePressureWarning,
)

from .config import Config
from .metrics import PolestarMetrics

logger = logging.getLogger(__name__)

TYRE_POSITIONS = ("front_left", "front_right", "rear_left", "rear_right")


class VehicleLike(Protocol):
    """The slice of polestar_api.Vehicle the collector needs (fakeable in tests)."""

    vin: str
    model_name: str | None
    model_year: int | None
    registration_no: str | None

    async def get_battery(self): ...
    async def get_odometer(self): ...
    async def get_health(self): ...
    async def get_exterior(self): ...
    async def get_availability(self): ...
    async def get_climate(self): ...
    async def get_target_soc(self): ...
    async def get_amp_limit(self): ...
    async def get_location(self): ...
    async def get_weather(self): ...


def _timestamp_seconds(timestamp) -> float | None:
    """Convert a polestar_api Timestamp message to Unix seconds."""
    if timestamp is None:
        return None
    seconds = getattr(timestamp, "seconds", 0)
    if not seconds:
        return None
    return seconds + getattr(timestamp, "nanos", 0) / 1e9


class VehicleCollector:
    def __init__(self, metrics: PolestarMetrics, config: Config) -> None:
        self.metrics = metrics
        self.config = config

    async def collect(self, vehicle: VehicleLike) -> bool:
        """Poll every enabled endpoint for one vehicle.

        Endpoint failures are isolated: one failing service still lets the
        others update. Returns True when the whole cycle was error-free.
        """
        vin = vehicle.vin
        started = time.monotonic()

        self.metrics.vehicle_info.labels(
            vin=vin,
            model_name=vehicle.model_name or "unknown",
            model_year=str(vehicle.model_year or ""),
            registration_no=vehicle.registration_no or "",
        ).set(1.0)

        steps = [
            ("battery", self._collect_battery),
            ("odometer", self._collect_odometer),
            ("health", self._collect_health),
            ("exterior", self._collect_exterior),
            ("availability", self._collect_availability),
            ("climate", self._collect_climate),
            ("target_soc", self._collect_target_soc),
            ("amp_limit", self._collect_amp_limit),
        ]
        if self.config.export_location:
            steps.append(("location", self._collect_location))
        if self.config.export_weather:
            steps.append(("weather", self._collect_weather))

        # Touch every counter child up front so the series exist at 0 —
        # otherwise increase() queries and dashboards see "no data" instead
        # of "no errors" until the first failure.
        for endpoint, _ in steps:
            self.metrics.poll_errors.labels(vin=vin, endpoint=endpoint)

        errors = 0
        for endpoint, step in steps:
            try:
                await step(vehicle)
            except Exception:
                errors += 1
                self.metrics.poll_errors.labels(vin=vin, endpoint=endpoint).inc()
                logger.exception("Failed to fetch %s for %s", endpoint, vin)

        success = errors == 0
        self.metrics.set_bool(self.metrics.poll_success, vin, success)
        if success:
            self.metrics.last_success_timestamp.labels(vin=vin).set(time.time())
        self.metrics.poll_duration.labels(vin=vin).set(time.monotonic() - started)
        return success

    def _set_data_timestamp(self, vin: str, source: str, timestamp) -> None:
        seconds = _timestamp_seconds(timestamp)
        if seconds is not None:
            self.metrics.data_timestamp.labels(vin=vin, source=source).set(seconds)

    async def _collect_battery(self, vehicle: VehicleLike) -> None:
        battery = await vehicle.get_battery()
        if battery is None:
            return
        vin = vehicle.vin
        m = self.metrics
        m.battery_charge_percent.labels(vin=vin).set(battery.charge_level)
        m.battery_range_meters.labels(vin=vin).set(battery.range_km * 1000.0)
        m.battery_power_watts.labels(vin=vin).set(battery.power_watts)
        m.battery_current_amps.labels(vin=vin).set(battery.current_amps)
        m.battery_voltage_volts.labels(vin=vin).set(battery.voltage_volts)
        m.battery_time_to_full_seconds.labels(vin=vin).set(battery.time_to_full * 60)
        m.battery_avg_consumption.labels(vin=vin).set(battery.avg_consumption)
        m.set_bool(m.battery_charging, vin, battery.is_charging)
        m.set_bool(m.battery_plugged_in, vin, battery.is_plugged_in)
        m.set_enum_one_hot(
            m.battery_charging_status, vin, "status", ChargingStatus, battery.charging_status
        )
        m.set_enum_one_hot(
            m.battery_charging_type, vin, "type", ChargingType, battery.charging_type
        )
        self._set_data_timestamp(vin, "battery", battery.timestamp)

    async def _collect_odometer(self, vehicle: VehicleLike) -> None:
        odo = await vehicle.get_odometer()
        if odo is None:
            return
        vin = vehicle.vin
        self.metrics.odometer_meters.labels(vin=vin).set(odo.odometer_meters)
        self.metrics.trip_meter_meters.labels(vin=vin, meter="manual").set(
            odo.trip_meter_manual_km * 1000.0
        )
        self.metrics.trip_meter_meters.labels(vin=vin, meter="automatic").set(
            odo.trip_meter_automatic_km * 1000.0
        )
        self._set_data_timestamp(vin, "odometer", odo.timestamp)

    async def _collect_health(self, vehicle: VehicleLike) -> None:
        health = await vehicle.get_health()
        if health is None:
            return
        vin = vehicle.vin
        m = self.metrics
        m.days_to_service.labels(vin=vin).set(health.days_to_service)
        m.distance_to_service_meters.labels(vin=vin).set(
            health.distance_to_service_km * 1000.0
        )
        m.set_bool(
            m.service_warning,
            vin,
            health.service_warning
            not in (ServiceWarning.UNSPECIFIED, ServiceWarning.NO_WARNING),
        )
        for position in TYRE_POSITIONS:
            pressure_kpa = getattr(health, f"{position}_tyre_pressure_kpa")
            if pressure_kpa:
                m.tyre_pressure_pascals.labels(vin=vin, position=position).set(
                    pressure_kpa * 1000.0
                )
            warning = getattr(health, f"{position}_tyre_pressure_warning")
            m.tyre_pressure_warning.labels(vin=vin, position=position).set(
                1.0
                if warning
                not in (TyrePressureWarning.UNSPECIFIED, TyrePressureWarning.NO_WARNING)
                else 0.0
            )
        m.set_bool(
            m.brake_fluid_warning,
            vin,
            health.brake_fluid_level_warning == BrakeFluidLevelWarning.TOO_LOW,
        )
        m.set_bool(
            m.low_voltage_battery_warning,
            vin,
            health.low_voltage_battery_warning == LowVoltageBatteryWarning.TOO_LOW,
        )
        m.set_bool(m.exterior_light_failure, vin, health.any_light_failure)
        self._set_data_timestamp(vin, "health", health.timestamp)

    async def _collect_exterior(self, vehicle: VehicleLike) -> None:
        exterior = await vehicle.get_exterior()
        if exterior is None or not exterior.has_data:
            return
        vin = vehicle.vin
        m = self.metrics

        if (
            exterior.central_lock is not None
            and exterior.central_lock.lock_status != LockStatus.UNSPECIFIED
        ):
            m.set_bool(m.locked, vin, exterior.central_lock.lock_status == LockStatus.LOCKED)

        def open_value(open_status) -> float | None:
            if open_status in (OpenStatus.OPEN, OpenStatus.AJAR):
                return 1.0
            if open_status == OpenStatus.CLOSED:
                return 0.0
            return None

        if exterior.doors is not None:
            for position in TYRE_POSITIONS:  # same four corner names
                door = getattr(exterior.doors, position)
                if door is None:
                    continue
                value = open_value(door.open_status)
                if value is not None:
                    m.door_open.labels(vin=vin, door=position).set(value)
        for name, wrapper in (("hood", exterior.hood), ("tailgate", exterior.tailgate)):
            if wrapper is not None and wrapper.status is not None:
                value = open_value(wrapper.status.open_status)
                if value is not None:
                    m.door_open.labels(vin=vin, door=name).set(value)

        if exterior.windows is not None:
            for position in TYRE_POSITIONS:
                window = getattr(exterior.windows, position)
                if window is None:
                    continue
                value = open_value(window.open_status)
                if value is not None:
                    m.window_open.labels(vin=vin, window=position).set(value)
        if exterior.sunroof is not None:
            value = open_value(exterior.sunroof.open_status)
            if value is not None:
                m.window_open.labels(vin=vin, window="sunroof").set(value)

    async def _collect_availability(self, vehicle: VehicleLike) -> None:
        availability = await vehicle.get_availability()
        if availability is None:
            return
        vin = vehicle.vin
        m = self.metrics
        if availability.availability_status != AvailabilityStatus.UNSPECIFIED:
            m.set_bool(m.vehicle_available, vin, availability.is_available)
        m.set_enum_one_hot(
            m.usage_mode, vin, "mode", UsageMode, availability.usage_mode
        )
        m.set_enum_one_hot(
            m.unavailable_reason,
            vin,
            "reason",
            UnavailableReason,
            availability.unavailable_reason,
        )
        self._set_data_timestamp(vin, "availability", availability.timestamp)

    async def _collect_climate(self, vehicle: VehicleLike) -> None:
        climate = await vehicle.get_climate()
        if climate is None:
            return
        self.metrics.set_bool(
            self.metrics.climatization_active, vehicle.vin, climate.is_active
        )

    async def _collect_target_soc(self, vehicle: VehicleLike) -> None:
        response = await vehicle.get_target_soc()
        if response is None:
            return
        self.metrics.charge_target_soc_percent.labels(vin=vehicle.vin).set(
            response.target_level
        )

    async def _collect_amp_limit(self, vehicle: VehicleLike) -> None:
        response = await vehicle.get_amp_limit()
        if response is None:
            return
        self.metrics.charge_amp_limit_amps.labels(vin=vehicle.vin).set(
            response.amperage_limit
        )

    async def _collect_location(self, vehicle: VehicleLike) -> None:
        location = await vehicle.get_location()
        if location is None or location.coordinate is None:
            return
        vin = vehicle.vin
        m = self.metrics
        m.location_latitude.labels(vin=vin).set(location.coordinate.latitude)
        m.location_longitude.labels(vin=vin).set(location.coordinate.longitude)
        m.location_altitude_meters.labels(vin=vin).set(location.altitude)
        m.location_heading_degrees.labels(vin=vin).set(location.heading)
        self._set_data_timestamp(vin, "location", location.timestamp)

    async def _collect_weather(self, vehicle: VehicleLike) -> None:
        report = await vehicle.get_weather()
        if report is None:
            return
        vin = vehicle.vin
        self.metrics.outside_temperature_celsius.labels(vin=vin).set(
            report.temperature_celsius
        )
        if report.timestamp_epoch_millis:
            self.metrics.data_timestamp.labels(vin=vin, source="weather").set(
                report.timestamp_epoch_millis / 1000.0
            )
