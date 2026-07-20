"""Prometheus metric definitions.

Conventions:
- Every per-vehicle metric carries a ``vin`` label.
- Distances are exported in meters, pressures in pascals, temperatures in
  Celsius, durations in seconds (Prometheus base units).
- Vehicle-state enums (charging status, usage mode, ...) are exported
  one-hot: one series per state with value 0/1, mirroring
  ``node_systemd_unit_state``. This keeps them usable in Grafana state
  timelines without magic-number decoding.
"""

from __future__ import annotations

from enum import IntEnum

from prometheus_client import CollectorRegistry, Counter, Gauge


class PolestarMetrics:
    """All exporter metrics, bound to a registry (injectable for tests)."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry

        def gauge(name: str, doc: str, labels: tuple[str, ...] = ("vin",)) -> Gauge:
            return Gauge(name, doc, labels, registry=registry)

        # -- Exporter / poll health --
        self.vehicle_info = gauge(
            "polestar_vehicle_info",
            "Static vehicle metadata (value is always 1)",
            ("vin", "model_name", "model_year", "registration_no"),
        )
        self.api_connected = Gauge(
            "polestar_api_connected",
            "1 if the exporter currently holds an authenticated API session",
            registry=registry,
        )
        self.poll_success = gauge(
            "polestar_last_poll_successful",
            "1 if the most recent poll cycle for this vehicle completed without errors",
        )
        self.last_success_timestamp = gauge(
            "polestar_last_successful_poll_timestamp_seconds",
            "Unix timestamp of the last error-free poll cycle for this vehicle",
        )
        self.poll_duration = gauge(
            "polestar_poll_duration_seconds",
            "Wall-clock duration of the most recent poll cycle for this vehicle",
        )
        self.poll_errors = Counter(
            "polestar_poll_errors",
            "Errors while fetching data, by API endpoint",
            ("vin", "endpoint"),
            registry=registry,
        )
        self.connection_errors = Counter(
            "polestar_connection_errors",
            "Errors establishing or re-establishing the API session",
            registry=registry,
        )
        self.data_timestamp = gauge(
            "polestar_data_timestamp_seconds",
            "Unix timestamp the vehicle reported for each data source "
            "(how fresh the cloud-side data is, not when we polled)",
            ("vin", "source"),
        )

        # -- Battery / charging --
        self.battery_charge_percent = gauge(
            "polestar_battery_charge_percent", "Battery state of charge (0-100)"
        )
        self.battery_range_meters = gauge(
            "polestar_battery_range_meters", "Estimated remaining range"
        )
        self.battery_power_watts = gauge(
            "polestar_battery_power_watts", "Instantaneous charge power"
        )
        self.battery_current_amps = gauge(
            "polestar_battery_current_amps", "Instantaneous charge current"
        )
        self.battery_voltage_volts = gauge(
            "polestar_battery_voltage_volts", "Instantaneous charge voltage"
        )
        self.battery_charging = gauge(
            "polestar_battery_charging", "1 if the battery is actively charging"
        )
        self.battery_plugged_in = gauge(
            "polestar_battery_plugged_in", "1 if a charger is connected"
        )
        self.battery_time_to_full_seconds = gauge(
            "polestar_battery_time_to_full_seconds",
            "Estimated time until charging completes "
            "(upstream field is assumed to be minutes; scaled to seconds)",
        )
        self.battery_charging_status = gauge(
            "polestar_battery_charging_status",
            "One-hot charging state; exactly one status label has value 1",
            ("vin", "status"),
        )
        self.battery_charging_type = gauge(
            "polestar_battery_charging_type",
            "One-hot charging type (AC/DC/...); exactly one type label has value 1",
            ("vin", "type"),
        )
        self.battery_avg_consumption = gauge(
            "polestar_battery_avg_consumption_kwh_per_100km",
            "Average energy consumption as reported by the vehicle",
        )

        # -- Charging settings --
        self.charge_target_soc_percent = gauge(
            "polestar_charge_target_soc_percent", "Configured charge target level"
        )
        self.charge_amp_limit_amps = gauge(
            "polestar_charge_amp_limit_amps", "Configured charging amperage limit"
        )

        # -- Odometer --
        self.odometer_meters = gauge("polestar_odometer_meters", "Total odometer")
        self.trip_meter_meters = gauge(
            "polestar_trip_meter_meters",
            "Trip meter readings",
            ("vin", "meter"),
        )

        # -- Health --
        self.days_to_service = gauge(
            "polestar_days_to_service", "Days until the next scheduled service"
        )
        self.distance_to_service_meters = gauge(
            "polestar_distance_to_service_meters",
            "Distance until the next scheduled service",
        )
        self.service_warning = gauge(
            "polestar_service_warning", "1 if the vehicle reports a service warning"
        )
        self.tyre_pressure_pascals = gauge(
            "polestar_tyre_pressure_pascals",
            "Tyre pressure by wheel position",
            ("vin", "position"),
        )
        self.tyre_pressure_warning = gauge(
            "polestar_tyre_pressure_warning",
            "1 if the given tyre reports a pressure warning",
            ("vin", "position"),
        )
        self.brake_fluid_warning = gauge(
            "polestar_brake_fluid_warning", "1 if the brake fluid level is too low"
        )
        self.low_voltage_battery_warning = gauge(
            "polestar_low_voltage_battery_warning",
            "1 if the 12V battery reports a warning",
        )
        self.exterior_light_failure = gauge(
            "polestar_exterior_light_failure",
            "1 if any exterior light reports a failure",
        )

        # -- Exterior --
        self.locked = gauge("polestar_locked", "1 if the central lock is locked")
        self.door_open = gauge(
            "polestar_door_open",
            "1 if the given door/hood/tailgate is open or ajar",
            ("vin", "door"),
        )
        self.window_open = gauge(
            "polestar_window_open",
            "1 if the given window (or sunroof) is open or ajar",
            ("vin", "window"),
        )

        # -- Availability / climate --
        self.vehicle_available = gauge(
            "polestar_vehicle_available", "1 if the vehicle is reachable by the cloud"
        )
        self.usage_mode = gauge(
            "polestar_vehicle_usage_mode",
            "One-hot vehicle usage mode (driving, inactive, ...)",
            ("vin", "mode"),
        )
        self.unavailable_reason = gauge(
            "polestar_vehicle_unavailable_reason",
            "One-hot reason the vehicle is unavailable",
            ("vin", "reason"),
        )
        self.climatization_active = gauge(
            "polestar_climatization_active", "1 if pre-conditioning is running"
        )

        # -- Location / environment --
        self.location_latitude = gauge(
            "polestar_location_latitude_degrees", "Last known latitude"
        )
        self.location_longitude = gauge(
            "polestar_location_longitude_degrees", "Last known longitude"
        )
        self.location_altitude_meters = gauge(
            "polestar_location_altitude_meters", "Last known altitude"
        )
        self.location_heading_degrees = gauge(
            "polestar_location_heading_degrees", "Last known heading"
        )
        self.outside_temperature_celsius = gauge(
            "polestar_outside_temperature_celsius",
            "Outside temperature at the vehicle's location (cloud weather report)",
        )

    def set_enum_one_hot(
        self,
        gauge: Gauge,
        vin: str,
        label: str,
        enum_cls: type[IntEnum],
        active: IntEnum,
    ) -> None:
        """Set one series per enum state: 1 for the active state, 0 for the rest."""
        for state in enum_cls:
            gauge.labels(**{"vin": vin, label: state.name}).set(
                1.0 if state == active else 0.0
            )

    def set_bool(self, gauge: Gauge, vin: str, value: bool) -> None:
        gauge.labels(vin=vin).set(1.0 if value else 0.0)
