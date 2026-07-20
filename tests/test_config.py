import pytest

from polestar_exporter.config import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    MIN_POLL_INTERVAL,
    Config,
    ConfigError,
)

BASE_ENV = {"POLESTAR_EMAIL": "me@example.com", "POLESTAR_PASSWORD": "hunter2"}


def test_minimal_env_uses_defaults():
    config = Config.from_env(BASE_ENV)
    assert config.email == "me@example.com"
    assert config.password == "hunter2"
    assert config.port == DEFAULT_PORT
    assert config.poll_interval == DEFAULT_POLL_INTERVAL
    assert config.export_location is True
    assert config.export_weather is True
    assert config.vins == ()
    assert config.token_cache_path is None


def test_missing_credentials_raises():
    with pytest.raises(ConfigError):
        Config.from_env({})
    with pytest.raises(ConfigError):
        Config.from_env({"POLESTAR_EMAIL": "me@example.com"})


def test_password_from_file(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("from-a-file\n")
    config = Config.from_env(
        {"POLESTAR_EMAIL": "me@example.com", "POLESTAR_PASSWORD_FILE": str(secret)}
    )
    assert config.password == "from-a-file"


def test_missing_password_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        Config.from_env(
            {
                "POLESTAR_EMAIL": "me@example.com",
                "POLESTAR_PASSWORD_FILE": str(tmp_path / "nope"),
            }
        )


def test_poll_interval_clamped_to_minimum():
    config = Config.from_env({**BASE_ENV, "POLL_INTERVAL_SECONDS": "5"})
    assert config.poll_interval == MIN_POLL_INTERVAL


def test_invalid_port_raises():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE_ENV, "EXPORTER_PORT": "not-a-port"})


def test_invalid_bool_raises():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE_ENV, "EXPORT_LOCATION": "maybe"})


def test_location_opt_out():
    config = Config.from_env({**BASE_ENV, "EXPORT_LOCATION": "false"})
    assert config.export_location is False


def test_vins_parsed_and_normalised():
    config = Config.from_env({**BASE_ENV, "POLESTAR_VINS": " abc123 , DEF456,"})
    assert config.vins == ("ABC123", "DEF456")


def test_token_cache_path(tmp_path):
    config = Config.from_env({**BASE_ENV, "TOKEN_CACHE_PATH": str(tmp_path / "t.json")})
    assert config.token_cache_path == tmp_path / "t.json"
