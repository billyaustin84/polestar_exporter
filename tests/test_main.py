from types import SimpleNamespace

import pytest

from polestar_exporter.main import select_vehicles


def vehicle(vin: str) -> SimpleNamespace:
    return SimpleNamespace(vin=vin)


def fake_api() -> SimpleNamespace:
    return SimpleNamespace(_connection=object())


def test_no_filter_returns_all_discovered():
    vehicles = [vehicle("AAA"), vehicle("BBB")]
    assert select_vehicles(fake_api(), vehicles, ()) == vehicles


def test_no_filter_and_nothing_discovered_raises_with_guest_hint():
    with pytest.raises(RuntimeError, match="POLESTAR_VINS"):
        select_vehicles(fake_api(), [], ())


def test_filter_selects_matching_case_insensitive():
    vehicles = [vehicle("aaa111"), vehicle("BBB222")]
    selected = select_vehicles(fake_api(), vehicles, ("AAA111",))
    assert [v.vin for v in selected] == ["aaa111"]


def test_undiscovered_vin_builds_vehicle_directly():
    """Guest accounts: discovery is empty but the VIN must still be polled."""
    api = fake_api()
    selected = select_vehicles(api, [], ("LPSVSEDEXML123456",))
    assert len(selected) == 1
    assert selected[0].vin == "LPSVSEDEXML123456"
    # It's a real polestar_api.Vehicle wired to the session's connection
    from polestar_api import Vehicle

    assert isinstance(selected[0], Vehicle)


def test_mixed_discovered_and_direct_vins():
    api = fake_api()
    discovered = [vehicle("AAA111")]
    selected = select_vehicles(api, discovered, ("AAA111", "ZZZ999"))
    assert [v.vin for v in selected] == ["AAA111", "ZZZ999"]
    assert selected[0] is discovered[0]
