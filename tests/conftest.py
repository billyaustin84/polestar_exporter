"""Shared fixtures.

Tests build *real* model objects from unofficial-polestar-api (they are plain
frozen dataclasses) and feed them through a FakeVehicle, so the collector is
exercised against the exact types the live API returns.
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from polestar_api.models.availability import (
    Availability,
    AvailabilityStatus,
    UnavailableReason,
    UsageMode,
)
from polestar_api.models.battery import (
    Battery,
    ChargerConnectionStatus,
    ChargingStatus,
    ChargingType,
)
from polestar_api.models.charging import AmpLimitResponse, TargetSocResponse
from polestar_api.models.climate import ClimatizationInfo, ClimatizationRunningStatus
from polestar_api.models.common import Coordinate, Location, Timestamp
from polestar_api.models.exterior import (
    CentralLockStatus,
    DoorStatus,
    DoorsStatus,
    ExteriorStatus,
    HoodStatus,
    LockStatus,
    OpenStatus,
    SunroofStatus,
    TailgateStatus,
    WindowStatus,
    WindowsStatus,
)
from polestar_api.models.health import (
    BrakeFluidLevelWarning,
    ExteriorLightWarning,
    Health,
    ServiceWarning,
    TyrePressureWarning,
)
from polestar_api.models.odometer import OdometerStatus
from polestar_api.models.weather import WeatherReport

from polestar_exporter.config import Config
from polestar_exporter.metrics import PolestarMetrics

VIN = "YSMTEST123456789A"
DATA_TS = Timestamp(seconds=1_752_000_000)


class FakeVehicle:
    """Stands in for polestar_api.Vehicle; per-endpoint values or exceptions."""

    def __init__(self, vin: str = VIN, **responses):
        self.vin = vin
        self.model_name = "Polestar 2"
        self.model_year = 2024
        self.registration_no = "AB12 CDE"
        self._responses = responses

    def _answer(self, endpoint: str):
        value = self._responses.get(endpoint)
        if isinstance(value, Exception):
            raise value
        return value

    async def get_battery(self):
        return self._answer("battery")

    async def get_odometer(self):
        return self._answer("odometer")

    async def get_health(self):
        return self._answer("health")

    async def get_exterior(self):
        return self._answer("exterior")

    async def get_availability(self):
        return self._answer("availability")

    async def get_climate(self):
        return self._answer("climate")

    async def get_target_soc(self):
        return self._answer("target_soc")

    async def get_amp_limit(self):
        return self._answer("amp_limit")

    async def get_location(self):
        return self._answer("location")

    async def get_weather(self):
        return self._answer("weather")


@pytest.fixture
def registry() -> CollectorRegistry:
    return CollectorRegistry()


@pytest.fixture
def metrics(registry: CollectorRegistry) -> PolestarMetrics:
    return PolestarMetrics(registry)


@pytest.fixture
def config() -> Config:
    return Config(email="test@example.com", password="secret")


def sample_battery(**overrides) -> Battery:
    defaults = dict(
        timestamp=DATA_TS,
        charge_level=80.0,
        range_km=350.0,
        time_to_full=90,  # minutes
        charger_connection_status=ChargerConnectionStatus.CONNECTED,
        charging_status=ChargingStatus.CHARGING,
        charging_type=ChargingType.AC,
        power_watts=11000,
        current_amps=16,
        voltage_volts=230,
        avg_consumption=18.5,
    )
    defaults.update(overrides)
    return Battery(**defaults)


def sample_odometer(**overrides) -> OdometerStatus:
    defaults = dict(
        timestamp=DATA_TS,
        odometer_meters=12_345_678,
        trip_meter_manual_km=42.5,
        trip_meter_automatic_km=7.2,
    )
    defaults.update(overrides)
    return OdometerStatus(**defaults)


def sample_health(**overrides) -> Health:
    defaults = dict(
        timestamp=DATA_TS,
        days_to_service=180,
        distance_to_service_km=15000,
        service_warning=ServiceWarning.NO_WARNING,
        brake_fluid_level_warning=BrakeFluidLevelWarning.NO_WARNING,
        front_left_tyre_pressure_warning=TyrePressureWarning.NO_WARNING,
        front_right_tyre_pressure_warning=TyrePressureWarning.NO_WARNING,
        rear_left_tyre_pressure_warning=TyrePressureWarning.NO_WARNING,
        rear_right_tyre_pressure_warning=TyrePressureWarning.NO_WARNING,
        front_left_tyre_pressure_kpa=270.0,
        front_right_tyre_pressure_kpa=272.0,
        rear_left_tyre_pressure_kpa=250.0,
        rear_right_tyre_pressure_kpa=251.0,
    )
    defaults.update(overrides)
    return Health(**defaults)


def sample_exterior(**overrides) -> ExteriorStatus:
    closed_door = DoorStatus(lock_status=LockStatus.LOCKED, open_status=OpenStatus.CLOSED)
    defaults = dict(
        central_lock=CentralLockStatus(lock_status=LockStatus.LOCKED),
        doors=DoorsStatus(
            front_left=closed_door,
            front_right=closed_door,
            rear_left=closed_door,
            rear_right=DoorStatus(lock_status=LockStatus.LOCKED, open_status=OpenStatus.AJAR),
        ),
        windows=WindowsStatus(
            front_left=WindowStatus(open_status=OpenStatus.OPEN),
            front_right=WindowStatus(open_status=OpenStatus.CLOSED),
            rear_left=WindowStatus(open_status=OpenStatus.CLOSED),
            rear_right=WindowStatus(open_status=OpenStatus.UNSPECIFIED),
        ),
        sunroof=SunroofStatus(open_status=OpenStatus.CLOSED),
        hood=HoodStatus(status=DoorStatus(open_status=OpenStatus.CLOSED)),
        tailgate=TailgateStatus(status=DoorStatus(open_status=OpenStatus.OPEN)),
    )
    defaults.update(overrides)
    return ExteriorStatus(**defaults)


def sample_availability(**overrides) -> Availability:
    defaults = dict(
        timestamp=DATA_TS,
        availability_status=AvailabilityStatus.AVAILABLE,
        unavailable_reason=UnavailableReason.UNSPECIFIED,
        usage_mode=UsageMode.INACTIVE,
    )
    defaults.update(overrides)
    return Availability(**defaults)


def full_responses() -> dict:
    """A complete, healthy set of endpoint responses."""
    return dict(
        battery=sample_battery(),
        odometer=sample_odometer(),
        health=sample_health(),
        exterior=sample_exterior(),
        availability=sample_availability(),
        climate=ClimatizationInfo(running_status=ClimatizationRunningStatus.IDLE),
        target_soc=TargetSocResponse(target_level=90),
        amp_limit=AmpLimitResponse(amperage_limit=16),
        location=Location(
            timestamp=DATA_TS,
            coordinate=Coordinate(latitude=51.5074, longitude=-0.1278),
            altitude=35,
            heading=270,
        ),
        weather=WeatherReport(
            timestamp_epoch_millis=1_752_000_000_000, temperature_celsius=19.5
        ),
    )
