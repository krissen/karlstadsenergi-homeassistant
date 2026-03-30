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

> **Note:** The API is reverse-engineered and may change when the portal is updated. There is no official public API.

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
