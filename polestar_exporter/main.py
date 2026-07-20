"""Exporter entry point: HTTP server plus the API poll loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from polestar_api import PolestarApi, Vehicle
from polestar_api.auth import FileTokenStore
from prometheus_client import REGISTRY, CollectorRegistry, start_http_server

from .collector import VehicleCollector
from .config import Config, ConfigError
from .metrics import PolestarMetrics

logger = logging.getLogger(__name__)

INITIAL_BACKOFF = 60.0
MAX_BACKOFF = 900.0


def select_vehicles(api: PolestarApi, discovered: list, vins: tuple[str, ...]) -> list:
    """Pick which vehicles to poll.

    Vehicle discovery returns an empty list for guest/secondary Polestar
    accounts (the car shows as "Guest user" on polestar.com) — the backend
    only lists cars you own. Mirroring the upstream Home Assistant
    integration's "my vehicle is not listed" flow, any configured VIN that
    discovery didn't return is used directly: the data services accept guest
    tokens even though the discovery query omits the car.
    """
    if not vins:
        if not discovered:
            raise RuntimeError(
                "No vehicles found on this account. If this is a guest/secondary "
                "account (car shows as 'Guest user' on polestar.com), discovery "
                "returns an empty list — set POLESTAR_VINS to your car's VIN "
                "to poll it directly."
            )
        return discovered

    by_vin = {v.vin.upper(): v for v in discovered}
    selected = []
    for vin in vins:
        if vin in by_vin:
            selected.append(by_vin[vin])
        else:
            logger.info(
                "VIN %s not in the account's vehicle list (guest account?); "
                "polling it directly",
                vin,
            )
            # PolestarApi offers no public way to build an undiscovered
            # vehicle; upstream is pinned to <0.4 so reaching for the
            # session's connection is stable enough.
            selected.append(Vehicle(vin=vin, connection=api._connection))
    return selected


async def poll_forever(config: Config, metrics: PolestarMetrics) -> None:
    """Maintain an API session and poll all vehicles on an interval.

    On session-level failure (auth, network, discovery) the session is torn
    down and rebuilt with exponential backoff; the HTTP endpoint stays up and
    keeps serving the last good values with polestar_api_connected = 0.
    """
    collector = VehicleCollector(metrics, config)
    backoff = INITIAL_BACKOFF

    while True:
        token_store = (
            FileTokenStore(config.token_cache_path) if config.token_cache_path else None
        )
        try:
            async with PolestarApi(
                email=config.email,
                password=config.password,
                token_store=token_store,
            ) as api:
                vehicles = select_vehicles(api, await api.get_vehicles(), config.vins)
                logger.info(
                    "Polling %d vehicle(s) every %.0fs: %s",
                    len(vehicles),
                    config.poll_interval,
                    ", ".join(v.vin for v in vehicles),
                )
                metrics.api_connected.set(1)
                backoff = INITIAL_BACKOFF

                while True:
                    cycle_start = time.monotonic()
                    for vehicle in vehicles:
                        await collector.collect(vehicle)
                    elapsed = time.monotonic() - cycle_start
                    await asyncio.sleep(max(0.0, config.poll_interval - elapsed))
        except asyncio.CancelledError:
            raise
        except Exception:
            metrics.api_connected.set(0)
            metrics.connection_errors.inc()
            logger.exception("API session failed; reconnecting in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


async def run(config: Config, registry: CollectorRegistry, on_server_started=None) -> None:
    metrics = PolestarMetrics(registry)
    metrics.api_connected.set(0)
    server, server_thread = start_http_server(
        config.port, addr=config.address, registry=registry
    )
    if on_server_started is not None:
        on_server_started(server)
    logger.info(
        "Serving metrics on http://%s:%d/metrics", config.address, server.server_port
    )
    try:
        await poll_forever(config, metrics)
    finally:
        server.shutdown()
        server_thread.join()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_env(os.environ)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    try:
        asyncio.run(run(config, REGISTRY))
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
