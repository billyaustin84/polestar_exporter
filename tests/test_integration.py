"""End-to-end smoke test: run() with a faked API, scraped over real HTTP."""

from __future__ import annotations

import asyncio
import urllib.request

from prometheus_client import CollectorRegistry

import polestar_exporter.main as main_module
from polestar_exporter.config import Config

from conftest import VIN, FakeVehicle, full_responses


class FakePolestarApi:
    def __init__(self, email, password, token_store=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_vehicles(self):
        return [FakeVehicle(**full_responses())]


async def test_run_serves_metrics_over_http(monkeypatch):
    monkeypatch.setattr(main_module, "PolestarApi", FakePolestarApi)
    registry = CollectorRegistry()
    config = Config(email="e", password="p", port=0, address="127.0.0.1")

    servers = []
    task = asyncio.create_task(
        main_module.run(config, registry, on_server_started=servers.append)
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.05)
            if registry.get_sample_value(
                "polestar_battery_charge_percent", {"vin": VIN}
            ):
                break
        else:
            raise AssertionError("first poll cycle never completed")

        port = servers[0].server_port
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{port}/metrics", timeout=5
            ).read().decode()
        )
        assert "polestar_battery_charge_percent" in body
        assert f'vin="{VIN}"' in body
        assert "polestar_api_connected 1.0" in body
        assert "polestar_odometer_meters" in body
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
