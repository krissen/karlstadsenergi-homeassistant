# Developer Documentation

Technical documentation for contributors working on the Karlstadsenergi Home Assistant integration.

---

## Architecture overview

The integration follows the standard Home Assistant integration pattern:

```
custom_components/karlstadsenergi/
  __init__.py       # Entry setup, coordinators, heartbeat
  api.py            # HTTP client (auth + data fetching)
  binary_sensor.py  # "Pickup tomorrow" binary sensors
  calendar.py       # Waste collection calendar entities
  config_flow.py    # UI config flow (BankID + password)
  const.py          # Constants, URLs, mappings
  diagnostics.py    # Diagnostic data export (redacted)
  sensor.py         # Sensor entities (waste + electricity)
  manifest.json     # Integration metadata
```

### Data flow

```
Config Flow (auth) --> async_setup_entry
  --> KarlstadsenergiApi (session, cookies)
  --> WasteCoordinator (6h) ---------> WasteCollectionSensor (per waste type)
  |                                 +> WasteCollectionCalendar (per waste type)
  |                                 +> WastePickupTomorrowSensor (per waste type)
  --> ConsumptionCoordinator (1h) ---> ElectricityConsumptionSensor
  |                                 +> ElectricityPriceSensor
  |                                 +> ElectricityCostSensor (x6 fee types)
  --> ContractCoordinator (24h) -----> ContractSensor (per contract)
  --> SpotPriceCoordinator (15min) --> SpotPriceSensor
  --> Heartbeat timer (every 5 min)
```

### Key design decisions

- **Four coordinators**: Each data source has its own refresh interval -- waste (6h), consumption (1h), contracts (24h), spot prices (15min).
- **Cookie persistence**: Session cookies are saved to the config entry so sessions survive HA restarts.
- **Heartbeat**: A timer sends a keepalive every 5 minutes to prevent server-side session timeout.
- **Fallback data**: If detailed services are unavailable, the integration falls back to a simpler summary endpoint.
- **Password over BankID**: Password auth can re-authenticate automatically. BankID requires interactive sign-in in the BankID app each time.

---

## Development setup

```bash
# Clone
git clone https://github.com/krissen/karlstadsenergi-homeassistant.git
cd karlstadsenergi-homeassistant

# Create virtual environment and install test deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt

# Symlink into test HA instance
ln -s "$(pwd)/custom_components/karlstadsenergi" \
  ../hass-test/config/custom_components/karlstadsenergi

# Restart HA to pick up changes
cd ../hass-test && docker compose restart
```

### Running tests

```bash
source .venv/bin/activate
pytest tests/              # full suite
pytest tests/ -q           # quiet output
pytest tests/test_api.py   # single module
```

### Linting

```bash
ruff format custom_components/karlstadsenergi/
ruff check custom_components/karlstadsenergi/ --fix
```

### Version

`const.py` defines `VERSION` and `manifest.json` defines `"version"`. Both **must be updated together** on every release -- they are not linked automatically.

### Translations

`strings.json` is the source of truth. `translations/en.json` must be an exact copy. After editing `strings.json`, copy it:

```bash
cp custom_components/karlstadsenergi/strings.json \
   custom_components/karlstadsenergi/translations/en.json
```

### Validating

```bash
for f in custom_components/karlstadsenergi/*.py; do
  python3 -m py_compile "$f" && echo "OK: $f"
done
```

---

## API notes

The integration communicates with an ASP.NET Web Forms backend. A few patterns are worth noting:

- **Response wrapper**: All POST endpoints return `{"d": <value>}` where `<value>` is sometimes a JSON string requiring double-parsing.
- **Server-side state**: Some endpoints require visiting the corresponding `.aspx` page (via GET) before the API call works.
- **Session cookies**: Two cookies (`ASP.NET_SessionId`, `.PORTALAUTH`) maintain the session and must be sent with every request.
- **Explicit nulls**: The API sometimes returns `null` for keys that normally hold objects or arrays. Python's `dict.get("key", {})` returns `None` (not `{}`) when the key exists with value `null`. Use `data.get("key") or {}` instead.

> **Note:** The API is reverse-engineered and may change when the portal is updated. There is no official public API.

### Consumption data resolution

The `GetConsumption` endpoint accepts an `IntervalEnum` parameter that controls data granularity:

| IntervalEnum | Interval | Description |
|---|---|---|
| 3 | DAY | Daily totals (default) |
| 4 | HOUR | Hourly consumption |
| 5 | WEEK | Weekly totals |
| 6 | QUARTER | 15-minute intervals |

The integration currently fetches DAY (for the main sensor) and HOUR (for the `hourly_consumption` attribute). **15-minute data is available** from the API but not yet exposed -- can be added on request.

All consumption data lags ~1 day behind real-time. The portal appears to update once per day, likely when meter data is imported from the grid operator.

To request 15-min data, set `IntervalEnum: 6` and `Interval: "QUARTER"` in the ConsumptionModel payload. Note that this returns ~96 points/day (~5500 for the default 2-month window) vs ~24/day for hourly.

### Long-term statistics import

Hourly consumption data is imported into HA's long-term statistics using `async_add_external_statistics`. This is done in `ConsumptionCoordinator._async_update_data()` after each successful fetch. Key details:

- **Statistic ID:** `karlstadsenergi:electricity_consumption_{customer_id}` (customer ID from config entry)
- **Source:** `karlstadsenergi`
- Each hourly data point becomes a `StatisticData(start=..., sum=..., state=...)` entry where `sum` is a running total starting from 0 at first import and `state` is the hourly kWh value
- On subsequent imports, `sum` continues from the last imported value via `get_last_statistics`
- Only new data points (after the last known statistic timestamp) are inserted
- The `has_mean` / `has_sum` metadata tells HA that this statistic has a cumulative sum, making it compatible with the Energy Dashboard

### Monthly cost statistics import

Fee data is imported into long-term statistics using the same pattern as hourly consumption, but with monthly granularity and SEK instead of kWh. This is implemented in `ConsumptionCoordinator._async_import_fee_statistics()`.

- **Statistic IDs:** `karlstadsenergi:cost_{fee_type}_{customer_id}` -- one per fee type (consumption_fee, power_fee, fixed_fee, energy_tax, vat, total_cost)
- **Source:** `karlstadsenergi`
- **Unit:** `SEK` with `unit_class=None` (monetary values have no unit conversion -- `unit_class` must be explicitly set to avoid HA 2026.11 deprecation warning)
- Each monthly data point (`dateInterval` like `"2026-02-01"`) becomes a `StatisticData` entry with `state` (monthly SEK amount) and `sum` (running cumulative total)
- The corresponding `ElectricityCostSensor` entities use `state_class: total` so they appear in HA's built-in Statistics card. Historical depth beyond the current sensor state is provided by the external statistics import above

### History depth and date range widening

The portal API's default `ConsumptionModel` only covers the last ~2 months (the `StartDate` field is typically set to the beginning of last month). However, the API supports requests going all the way back to the customer's `ContractsStartDate`, which can be 7+ years of data.

The coordinator's `_widen_start_date()` method overrides `StartDate` based on the configurable **history_years** setting (options flow, default 2 years):

1. Calculate target: January 1st of `(current_year - history_years)`
2. Clamp to `ContractsStartDate` as the lower bound (can't request data before the contract existed)
3. Replace `StartDate` in the model copy

This widened model is used for hourly consumption on the initial backfill only; subsequent hourly refreshes use the API's default ~2 month window, reducing payload size (19k → 1.4k rows). Fee requests always use the widened model (~25 monthly rows regardless of window) because cost sensors expose `monthly_breakdown` as an entity attribute for dashboard charts. The `get_last_statistics` check ensures only new data points are imported regardless of fetch window.

Observed data volumes for reference (single customer):

| History | Hourly points | Fee points (per type) |
|---------|--------------|----------------------|
| 2 months (default API) | ~1,400 | 1 |
| 2 years | ~19,000 | ~25 |
| Full contract (~7 years) | ~66,000 | ~83 |

---

## Session management

The server session times out after ~15 minutes. The integration handles this with:

1. **Heartbeat** -- keepalive request every 5 minutes
2. **Cookie persistence** -- cookies saved to config entry, restored on HA restart
3. **Auto-reauth** -- password users re-authenticate automatically on session expiry; BankID users get a reauth prompt

---

## Release smoke test

Before tagging a release, run automated and manual tests against a real HA instance.

Use the **[Release Smoke Report Template](RELEASE_SMOKE_REPORT_TEMPLATE.md)** to document results. Save the filled-in report as `tmp/smoke-report-vX.Y.Z.md`.

Quick reference (the template has full details):

1. Run unit tests: `pytest tests/ --ignore=tests/test_live.py -q`
2. Run lint: `ruff check . && ruff format --check .`
3. Copy integration to test instance and restart HA
4. Run live tests: `pytest tests/test_live.py -v`
5. Manually verify reauth, BankID (if applicable), and options flow

---

## Useful resources

- [CONTRIBUTING.md](../CONTRIBUTING.md) -- how to submit changes, code style, PR guidelines
- [Home Assistant integration development docs](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [Home Assistant DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data)
- [aiohttp documentation](https://docs.aiohttp.org/)
