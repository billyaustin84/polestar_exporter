"""Collector behaviour: model → metric mapping, unit conversions, error isolation."""

from __future__ import annotations

from polestar_api.exceptions import ApiError
from polestar_api.models.availability import AvailabilityStatus, UnavailableReason, UsageMode
from polestar_api.models.battery import ChargerConnectionStatus, ChargingStatus, ChargingType
from polestar_api.models.exterior import CentralLockStatus, LockStatus
from polestar_api.models.health import ExteriorLightWarning, ServiceWarning, TyrePressureWarning

from polestar_exporter.collector import VehicleCollector
from polestar_exporter.config import Config

from conftest import (
    DATA_TS,
    VIN,
    FakeVehicle,
    full_responses,
    sample_availability,
    sample_battery,
    sample_exterior,
    sample_health,
)


def value(registry, name, **labels):
    return registry.get_sample_value(name, {"vin": VIN, **labels})


async def collect(metrics, config, **responses) -> bool:
    collector = VehicleCollector(metrics, config)
    return await collector.collect(FakeVehicle(**responses))


class TestBattery:
    async def test_basic_values(self, metrics, registry, config):
        await collect(metrics, config, battery=sample_battery())
        assert value(registry, "polestar_battery_charge_percent") == 80.0
        assert value(registry, "polestar_battery_range_meters") == 350_000.0
        assert value(registry, "polestar_battery_power_watts") == 11000
        assert value(registry, "polestar_battery_current_amps") == 16
        assert value(registry, "polestar_battery_voltage_volts") == 230
        assert value(registry, "polestar_battery_time_to_full_seconds") == 90 * 60
        assert value(registry, "polestar_battery_avg_consumption_kwh_per_100km") == 18.5

    async def test_charging_flags_and_one_hot(self, metrics, registry, config):
        await collect(metrics, config, battery=sample_battery())
        assert value(registry, "polestar_battery_charging") == 1.0
        assert value(registry, "polestar_battery_plugged_in") == 1.0
        assert value(registry, "polestar_battery_charging_status", status="CHARGING") == 1.0
        assert value(registry, "polestar_battery_charging_status", status="IDLE") == 0.0
        assert value(registry, "polestar_battery_charging_type", type="AC") == 1.0
        assert value(registry, "polestar_battery_charging_type", type="DC") == 0.0

    async def test_idle_unplugged(self, metrics, registry, config):
        await collect(
            metrics,
            config,
            battery=sample_battery(
                charging_status=ChargingStatus.IDLE,
                charger_connection_status=ChargerConnectionStatus.DISCONNECTED,
                charging_type=ChargingType.NONE,
            ),
        )
        assert value(registry, "polestar_battery_charging") == 0.0
        assert value(registry, "polestar_battery_plugged_in") == 0.0
        assert value(registry, "polestar_battery_charging_status", status="IDLE") == 1.0

    async def test_data_timestamp(self, metrics, registry, config):
        await collect(metrics, config, battery=sample_battery())
        assert (
            value(registry, "polestar_data_timestamp_seconds", source="battery")
            == DATA_TS.seconds
        )


class TestOdometer:
    async def test_odometer_and_trips(self, metrics, registry, config):
        await collect(metrics, config, odometer=full_responses()["odometer"])
        assert value(registry, "polestar_odometer_meters") == 12_345_678
        assert value(registry, "polestar_trip_meter_meters", meter="manual") == 42_500.0
        assert value(registry, "polestar_trip_meter_meters", meter="automatic") == 7_200.0


class TestHealth:
    async def test_service_and_pressures(self, metrics, registry, config):
        await collect(metrics, config, health=sample_health())
        assert value(registry, "polestar_days_to_service") == 180
        assert value(registry, "polestar_distance_to_service_meters") == 15_000_000.0
        assert value(registry, "polestar_service_warning") == 0.0
        assert (
            value(registry, "polestar_tyre_pressure_pascals", position="front_left")
            == 270_000.0
        )
        assert (
            value(registry, "polestar_tyre_pressure_warning", position="front_left") == 0.0
        )

    async def test_warnings_active(self, metrics, registry, config):
        await collect(
            metrics,
            config,
            health=sample_health(
                service_warning=ServiceWarning.REGULAR_MAINTENANCE_TIME,
                rear_left_tyre_pressure_warning=TyrePressureWarning.LOW_PRESSURE,
                low_beam_left_warning=ExteriorLightWarning.FAILURE,
            ),
        )
        assert value(registry, "polestar_service_warning") == 1.0
        assert (
            value(registry, "polestar_tyre_pressure_warning", position="rear_left") == 1.0
        )
        assert (
            value(registry, "polestar_tyre_pressure_warning", position="front_left") == 0.0
        )
        assert value(registry, "polestar_exterior_light_failure") == 1.0

    async def test_zero_pressure_not_exported(self, metrics, registry, config):
        """EVs that don't report a corner shouldn't export a bogus 0 Pa sample."""
        await collect(
            metrics, config, health=sample_health(front_left_tyre_pressure_kpa=0.0)
        )
        assert value(registry, "polestar_tyre_pressure_pascals", position="front_left") is None
        assert (
            value(registry, "polestar_tyre_pressure_pascals", position="front_right")
            == 272_000.0
        )


class TestExterior:
    async def test_lock_doors_windows(self, metrics, registry, config):
        await collect(metrics, config, exterior=sample_exterior())
        assert value(registry, "polestar_locked") == 1.0
        assert value(registry, "polestar_door_open", door="front_left") == 0.0
        assert value(registry, "polestar_door_open", door="rear_right") == 1.0  # AJAR
        assert value(registry, "polestar_door_open", door="tailgate") == 1.0
        assert value(registry, "polestar_door_open", door="hood") == 0.0
        assert value(registry, "polestar_window_open", window="front_left") == 1.0
        assert value(registry, "polestar_window_open", window="sunroof") == 0.0
        # UNSPECIFIED window state must not produce a sample
        assert value(registry, "polestar_window_open", window="rear_right") is None

    async def test_unspecified_central_lock_not_exported(self, metrics, registry, config):
        exterior = sample_exterior(
            central_lock=CentralLockStatus(lock_status=LockStatus.UNSPECIFIED)
        )
        await collect(metrics, config, exterior=exterior)
        assert value(registry, "polestar_locked") is None


class TestAvailabilityAndClimate:
    async def test_available(self, metrics, registry, config):
        await collect(metrics, config, availability=sample_availability())
        assert value(registry, "polestar_vehicle_available") == 1.0
        assert value(registry, "polestar_vehicle_usage_mode", mode="INACTIVE") == 1.0
        assert value(registry, "polestar_vehicle_usage_mode", mode="DRIVING") == 0.0

    async def test_unavailable_with_reason(self, metrics, registry, config):
        await collect(
            metrics,
            config,
            availability=sample_availability(
                availability_status=AvailabilityStatus.UNAVAILABLE,
                unavailable_reason=UnavailableReason.POWER_SAVING_MODE,
                usage_mode=UsageMode.ABANDONED,
            ),
        )
        assert value(registry, "polestar_vehicle_available") == 0.0
        assert (
            value(
                registry,
                "polestar_vehicle_unavailable_reason",
                reason="POWER_SAVING_MODE",
            )
            == 1.0
        )

    async def test_climate_and_charge_settings(self, metrics, registry, config):
        responses = full_responses()
        await collect(
            metrics,
            config,
            climate=responses["climate"],
            target_soc=responses["target_soc"],
            amp_limit=responses["amp_limit"],
        )
        assert value(registry, "polestar_climatization_active") == 0.0
        assert value(registry, "polestar_charge_target_soc_percent") == 90
        assert value(registry, "polestar_charge_amp_limit_amps") == 16


class TestLocationAndWeather:
    async def test_location_exported(self, metrics, registry, config):
        await collect(metrics, config, location=full_responses()["location"])
        assert value(registry, "polestar_location_latitude_degrees") == 51.5074
        assert value(registry, "polestar_location_longitude_degrees") == -0.1278
        assert value(registry, "polestar_location_altitude_meters") == 35
        assert value(registry, "polestar_location_heading_degrees") == 270

    async def test_location_disabled_never_fetched(self, metrics, registry):
        config = Config(email="e", password="p", export_location=False)
        boom = ApiError("should not be called")
        success = await collect(metrics, config, location=boom, weather=None)
        assert success is True
        assert value(registry, "polestar_location_latitude_degrees") is None

    async def test_weather(self, metrics, registry, config):
        await collect(metrics, config, weather=full_responses()["weather"])
        assert value(registry, "polestar_outside_temperature_celsius") == 19.5
        assert (
            value(registry, "polestar_data_timestamp_seconds", source="weather")
            == 1_752_000_000.0
        )


class TestPollHealth:
    async def test_full_poll_success(self, metrics, registry, config):
        success = await collect(metrics, config, **full_responses())
        assert success is True
        assert value(registry, "polestar_last_poll_successful") == 1.0
        assert value(registry, "polestar_last_successful_poll_timestamp_seconds") > 0
        assert value(registry, "polestar_poll_duration_seconds") is not None
        info = registry.get_sample_value(
            "polestar_vehicle_info",
            {
                "vin": VIN,
                "model_name": "Polestar 2",
                "model_year": "2024",
                "registration_no": "AB12 CDE",
            },
        )
        assert info == 1.0

    async def test_endpoint_failure_is_isolated(self, metrics, registry, config):
        responses = full_responses()
        responses["health"] = ApiError("backend sad", status_code=500)
        success = await collect(metrics, config, **responses)
        assert success is False
        # other endpoints still landed
        assert value(registry, "polestar_battery_charge_percent") == 80.0
        assert value(registry, "polestar_odometer_meters") == 12_345_678
        assert value(registry, "polestar_last_poll_successful") == 0.0
        assert (
            registry.get_sample_value(
                "polestar_poll_errors_total", {"vin": VIN, "endpoint": "health"}
            )
            == 1.0
        )
        assert (
            value(registry, "polestar_last_successful_poll_timestamp_seconds") is None
        )

    async def test_error_counters_exist_at_zero(self, metrics, registry, config):
        """Series must exist before any error so 'no data' can't be mistaken for 'no errors'."""
        await collect(metrics, config, **full_responses())
        for endpoint in ("battery", "health", "location", "weather"):
            assert (
                registry.get_sample_value(
                    "polestar_poll_errors_total", {"vin": VIN, "endpoint": endpoint}
                )
                == 0.0
            )

    async def test_none_responses_are_not_errors(self, metrics, registry, config):
        """Polestar 4 style: several endpoints legitimately return None."""
        success = await collect(
            metrics, config, battery=None, health=None, exterior=None
        )
        assert success is True
        assert value(registry, "polestar_battery_charge_percent") is None
        assert value(registry, "polestar_last_poll_successful") == 1.0
