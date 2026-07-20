# polestar-exporter

[![CI](https://github.com/billyaustin84/polestar_exporter/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/billyaustin84/polestar_exporter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Prometheus](https://prometheus.io/) exporter for Polestar vehicles, built on
[`unofficial-polestar-api`](https://pypi.org/project/unofficial-polestar-api/).
It signs in with your Polestar account, discovers your vehicles, and polls the
same cloud APIs the official mobile app uses — exposing battery, charging,
odometer, health, doors/windows, availability, location, and weather data as
Prometheus metrics. An example Grafana dashboard is included in
[`grafana/polestar-dashboard.json`](grafana/polestar-dashboard.json).

## ⚠️ Read this first — unofficial API disclaimers

- **This is not an official Polestar product.** It is not affiliated with,
  endorsed by, or supported by Polestar or Volvo Cars in any way.
- **The API is reverse-engineered and undocumented.** `unofficial-polestar-api`
  talks to the private backend used by the Polestar mobile app. Polestar can
  change, rate-limit, or **revoke access to these APIs at any time, without
  notice**, and this exporter will silently stop working when they do.
- **Your account is on the line.** Using private APIs may breach Polestar's
  terms of service. Polestar could throttle, suspend, or ban accounts that use
  them. Use a sensible poll interval (the default is 5 minutes; the exporter
  refuses to go below 60 seconds) and accept that you use this at your own risk.
- **Read-only by design.** The exporter only ever calls data-retrieval
  endpoints. It never sends commands (no wake-up, lock/unlock, climate, or
  charging commands), so it should not drain the 12V battery by keeping the car
  awake — but the polling itself is still traffic Polestar can see and object to.
- **Data may be wrong, stale, or missing.** Field meanings and units are
  inferred from observing the app. Some endpoints return nothing on some models
  (e.g. several legacy endpoints are unimplemented on Polestar 4). Don't build
  anything safety-critical on top of this.
- **Privacy: this exports your car's location.** By default the exporter
  publishes latitude/longitude of the vehicle as metrics. Anyone who can scrape
  the exporter or query your Prometheus can see where your car is. Set
  `EXPORT_LOCATION=false` if you don't want that, and keep the metrics port
  firewalled off either way.
- **Credentials:** your Polestar email and password are handed to an unofficial
  library. Read its source if that concerns you (it should), prefer
  `POLESTAR_PASSWORD_FILE` over plain environment variables, and consider a
  dedicated secondary driver account if Polestar offers you one.

## Requirements

- Python 3.12+
- A Polestar account with at least one vehicle
- Prometheus (and optionally Grafana) to do anything useful with the output

## Installation

```bash
pip install .
# or for development
pip install -e .[dev]
```

## Running

```bash
export POLESTAR_EMAIL="you@example.com"
export POLESTAR_PASSWORD="..."          # or POLESTAR_PASSWORD_FILE=/run/secrets/polestar
polestar-exporter
```

Metrics are then available at `http://localhost:9772/metrics`.

### Configuration (environment variables)

| Variable | Default | Description |
| --- | --- | --- |
| `POLESTAR_EMAIL` | *(required)* | Polestar account email (`POLESTAR_EMAIL_FILE` also supported) |
| `POLESTAR_PASSWORD` | *(required)* | Polestar account password (`POLESTAR_PASSWORD_FILE` also supported) |
| `EXPORTER_PORT` | `9772` | Port to serve `/metrics` on |
| `EXPORTER_ADDRESS` | `0.0.0.0` | Bind address |
| `POLL_INTERVAL_SECONDS` | `300` | How often to poll the Polestar cloud (min 60 — be polite) |
| `TOKEN_CACHE_PATH` | *(unset)* | Path to cache OAuth tokens between restarts (avoids repeated full logins) |
| `EXPORT_LOCATION` | `true` | Export vehicle position metrics (see privacy note above) |
| `EXPORT_WEATHER` | `true` | Export the cloud weather report for the car's location |
| `POLESTAR_VINS` | *(all)* | Comma-separated VINs to export, if the account has several cars |
| `LOG_LEVEL` | `INFO` | Python log level |

### Docker

```bash
docker build -t polestar-exporter .
docker run -d --name polestar-exporter \
  -e POLESTAR_EMAIL=you@example.com \
  -e POLESTAR_PASSWORD=... \
  -e TOKEN_CACHE_PATH=/data/tokens.json \
  -v polestar-tokens:/data \
  -p 9772:9772 \
  polestar-exporter
```

### systemd

Example unit and environment files live in [`contrib/`](contrib/):

```bash
sudo python3 -m venv /opt/polestar-exporter
sudo /opt/polestar-exporter/bin/pip install git+https://github.com/billyaustin84/polestar_exporter

sudo install -d -m 750 /etc/polestar-exporter
sudo install -m 600 contrib/polestar-exporter.env.example /etc/polestar-exporter/polestar-exporter.env
sudoedit /etc/polestar-exporter/polestar-exporter.env   # add your credentials/VINs

sudo cp contrib/polestar-exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polestar-exporter
```

The unit runs as an unprivileged `DynamicUser` with the credentials file
readable by root only, persists the OAuth token cache in
`/var/lib/polestar-exporter/`, and applies standard systemd sandboxing. The
env file holds everything — email, password, VINs, and any optional settings —
and its comments cover the `LoadCredential=` variant if you prefer the
password out of the env file entirely.

### Prometheus scrape config

The exporter polls the Polestar cloud on its own schedule and serves the most
recent values, so scraping more often than the poll interval just re-reads the
same numbers. Something like this is plenty:

```yaml
scrape_configs:
  - job_name: polestar
    scrape_interval: 60s
    static_configs:
      - targets: ["polestar-exporter:9772"]
```

## Metrics

All per-vehicle metrics carry a `vin` label. Base units throughout: meters,
pascals, seconds, watts, Celsius.

| Metric | Description |
| --- | --- |
| `polestar_vehicle_info` | Static metadata (`model_name`, `model_year`, `registration_no`) |
| `polestar_battery_charge_percent` | State of charge (0–100) |
| `polestar_battery_range_meters` | Estimated remaining range |
| `polestar_battery_power_watts` / `_current_amps` / `_voltage_volts` | Live charging electrical values |
| `polestar_battery_charging` / `polestar_battery_plugged_in` | Booleans (0/1) |
| `polestar_battery_charging_status{status=...}` | One-hot charging state (CHARGING, IDLE, SCHEDULED, ...) |
| `polestar_battery_charging_type{type=...}` | One-hot AC/DC/wireless |
| `polestar_battery_time_to_full_seconds` | Estimated time until charging completes¹ |
| `polestar_battery_avg_consumption_kwh_per_100km` | Average consumption as reported by the car¹ |
| `polestar_charge_target_soc_percent` / `polestar_charge_amp_limit_amps` | Configured charging settings |
| `polestar_odometer_meters` | Total odometer |
| `polestar_trip_meter_meters{meter=manual\|automatic}` | Trip meters |
| `polestar_days_to_service` / `polestar_distance_to_service_meters` | Service schedule |
| `polestar_service_warning`, `polestar_brake_fluid_warning`, `polestar_low_voltage_battery_warning`, `polestar_exterior_light_failure` | Warning booleans |
| `polestar_tyre_pressure_pascals{position=...}` / `polestar_tyre_pressure_warning{position=...}` | Per-wheel tyre data |
| `polestar_locked` | Central lock state |
| `polestar_door_open{door=...}` / `polestar_window_open{window=...}` | Doors, hood, tailgate, windows, sunroof |
| `polestar_vehicle_available` / `polestar_vehicle_usage_mode{mode=...}` / `polestar_vehicle_unavailable_reason{reason=...}` | Cloud reachability and usage state |
| `polestar_climatization_active` | Pre-conditioning running |
| `polestar_location_latitude_degrees` / `_longitude_degrees` / `_altitude_meters` / `_heading_degrees` | Last known position (disable with `EXPORT_LOCATION=false`) |
| `polestar_outside_temperature_celsius` | Cloud weather report at the car's location |
| `polestar_data_timestamp_seconds{source=...}` | How fresh the car-reported data is per source |
| `polestar_api_connected`, `polestar_last_poll_successful`, `polestar_last_successful_poll_timestamp_seconds`, `polestar_poll_duration_seconds`, `polestar_poll_errors_total{endpoint=...}`, `polestar_connection_errors_total` | Exporter health |

¹ Unit inferred from observing the app; treat with mild suspicion.

## Troubleshooting

**"No vehicles found on this account"** — vehicle discovery only returns cars
*owned* by the account. If your car shows as **"Guest user"** on polestar.com
(you're a secondary/guest driver), discovery comes back empty even though the
data APIs work fine. Set `POLESTAR_VINS` to your car's VIN (find it in the
Polestar app under car details, on the registration document, or at the base of
the windscreen) and the exporter will poll it directly:

```bash
export POLESTAR_VINS="LPSVSEDEXML123456"
```

Vehicles added this way have no `model_name`/`registration_no` metadata in
`polestar_vehicle_info`, since that metadata comes from the discovery response.

## Grafana dashboard

Import [`grafana/polestar-dashboard.json`](grafana/polestar-dashboard.json)
(Dashboards → New → Import), point it at your Prometheus datasource, and pick
your VIN from the *Vehicle* variable. It includes battery/charging panels, a
charging state timeline, tyre pressures, health warnings, door/window state, a
location map, and exporter-health panels so you notice when Polestar breaks the
API (see disclaimers above — it's a *when*, not an *if*).

## Development

```bash
pip install -e .[dev]
pytest
```

The test suite builds real `unofficial-polestar-api` model objects (they're
plain dataclasses) and feeds them through a fake vehicle, so collector logic is
tested against the exact types the live API returns — no network access needed.
A test also cross-checks that every metric referenced by the Grafana dashboard
actually exists in the exporter.

## License

MIT. See the disclaimers above; to spell it out once more: **this can stop
working at any moment, entirely at Polestar's discretion.**
