"""Environment-based configuration for the exporter."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9772
DEFAULT_POLL_INTERVAL = 300.0
# The upstream API is a private, reverse-engineered cloud API. Polling
# aggressively raises the odds of Polestar noticing and blocking access,
# so refuse to poll faster than this.
MIN_POLL_INTERVAL = 60.0


class ConfigError(Exception):
    """Raised when the exporter is misconfigured."""


def _read_secret(env: Mapping[str, str], name: str) -> str | None:
    """Read NAME from the environment, or NAME_FILE as a file path (docker secrets)."""
    value = env.get(name)
    if value:
        return value
    file_path = env.get(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Could not read {name}_FILE ({file_path}): {exc}") from exc
    return None


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean (got {raw!r})")


@dataclass(frozen=True)
class Config:
    email: str
    password: str
    port: int = DEFAULT_PORT
    address: str = "0.0.0.0"
    poll_interval: float = DEFAULT_POLL_INTERVAL
    token_cache_path: Path | None = None
    export_location: bool = True
    export_weather: bool = True
    vins: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        email = _read_secret(env, "POLESTAR_EMAIL")
        password = _read_secret(env, "POLESTAR_PASSWORD")
        if not email or not password:
            raise ConfigError(
                "POLESTAR_EMAIL and POLESTAR_PASSWORD are required "
                "(or POLESTAR_EMAIL_FILE / POLESTAR_PASSWORD_FILE)"
            )

        try:
            port = int(env.get("EXPORTER_PORT", DEFAULT_PORT))
        except ValueError as exc:
            raise ConfigError("EXPORTER_PORT must be an integer") from exc

        try:
            poll_interval = float(env.get("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL))
        except ValueError as exc:
            raise ConfigError("POLL_INTERVAL_SECONDS must be a number") from exc
        if poll_interval < MIN_POLL_INTERVAL:
            logger.warning(
                "POLL_INTERVAL_SECONDS=%s is below the minimum of %s; clamping",
                poll_interval,
                MIN_POLL_INTERVAL,
            )
            poll_interval = MIN_POLL_INTERVAL

        token_cache = env.get("TOKEN_CACHE_PATH")

        vins = tuple(
            vin.strip().upper()
            for vin in env.get("POLESTAR_VINS", "").split(",")
            if vin.strip()
        )

        return cls(
            email=email,
            password=password,
            port=port,
            address=env.get("EXPORTER_ADDRESS", "0.0.0.0"),
            poll_interval=poll_interval,
            token_cache_path=Path(token_cache) if token_cache else None,
            export_location=_read_bool(env, "EXPORT_LOCATION", True),
            export_weather=_read_bool(env, "EXPORT_WEATHER", True),
            vins=vins,
        )
