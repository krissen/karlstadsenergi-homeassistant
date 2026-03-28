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
- **Password over BankID**: Password auth can re-authenticate automatically. BankID requires interactive QR scanning each time.

---

## Development setup

```bash
# Clone
git clone https://github.com/krissen/karlstadsenergi-homeassistant.git
cd karlstadsenergi-homeassistant

# Symlink into test HA instance
ln -s "$(pwd)/custom_components/karlstadsenergi" \
  ../hass-test/config/custom_components/karlstadsenergi

# Restart HA to pick up changes
cd ../hass-test && docker compose restart
```

### Linting

```bash
ruff format custom_components/karlstadsenergi/
ruff check custom_components/karlstadsenergi/ --fix
```

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

## Easter eggs from the API

During development, we discovered that the login endpoint has a rather... opinionated response to certain edge cases. If you send stale session cookies along with a login request, the server returns a binary-encoded response that decodes to a message that would make a sailor blush.

We choose to interpret this as a heartfelt greeting from a fellow developer who spent one too many late nights debugging ASP.NET session state. If you find it, know that you are not alone. We see you, backend developer. We love you. Stay strong. <3

---

## Useful resources

- [Home Assistant integration development docs](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [Home Assistant DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data)
- [aiohttp documentation](https://docs.aiohttp.org/)
