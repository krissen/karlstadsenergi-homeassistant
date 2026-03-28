# Developer Documentation

Technical documentation for contributors working on the Karlstadsenergi Home Assistant integration.

---

## Architecture overview

The integration follows the standard Home Assistant integration pattern:

```
custom_components/karlstadsenergi/
  __init__.py      # Entry setup, coordinators, heartbeat
  api.py           # HTTP client (auth + data fetching)
  config_flow.py   # UI config flow (BankID + password)
  const.py         # Constants, URLs, mappings
  sensor.py        # Sensor entities (waste + electricity)
  manifest.json    # Integration metadata
```

### Data flow

```
Config Flow (auth) --> async_setup_entry
  --> KarlstadsenergiApi (session, cookies)
  --> WasteCoordinator ---------> WasteCollectionSensor (per waste type)
  --> ConsumptionCoordinator ----> ElectricityConsumptionSensor
  --> Heartbeat timer (every 5 min)
```

### Key design decisions

- **Two coordinators**: Waste data changes rarely (every few hours is fine), while consumption data benefits from more frequent updates. The consumption coordinator polls at 1/6 of the waste interval (minimum 1 hour).
- **Cookie persistence**: Session cookies (`ASP.NET_SessionId`, `.PORTALAUTH`) are saved to the config entry data so sessions survive HA restarts.
- **Heartbeat**: A timer sends `GET /heart.beat` every 5 minutes to prevent the 15-minute server-side session timeout.
- **Fallback data**: If detailed flex services are unavailable, the integration falls back to the simpler start page summary (`GetNextFlexFetchDate`).

---

## API architecture

The backend is an ASP.NET Web Forms application built by CGI, with a mobile app layer by Evado. For a complete API reference, see [`research/api-architecture.md`](../research/api-architecture.md).

### Key points

- **Base URL**: `https://minasidor.karlstadsenergi.se`
- **ASP.NET WebMethod pattern**: All POST endpoints wrap responses in `{"d": <value>}` where `<value>` is often a JSON string that needs double-parsing
- **Required headers**: `Content-Type: application/json; charset=utf-8` and `X-Requested-With: XMLHttpRequest`
- **Session cookies**: `ASP.NET_SessionId` and `.PORTALAUTH` must be sent with every request
- **Server-side state**: Some endpoints (flex services, consumption) require visiting the corresponding `.aspx` page first to initialize server state before the API call will work

> **Important:** This API is reverse-engineered from the customer portal and Android app. There is no official public API. Endpoints may change without notice when CGI or Karlstads Energi update the portal.

---

## BankID authentication flow

BankID uses a multi-step flow that requires interactive user action (QR scan). This makes it fundamentally different from password auth, which can be done programmatically.

### Initial setup (config flow)

```
1. User enters personnummer
2. POST /api/grp2/Authenticate/{transactionId}/bankid/0
   --> Returns orderRef, autoStartToken, qrStartToken, QR code (base64 PNG)
3. Show QR code to user in HA config UI
4. User scans with BankID app and signs
5. Poll: POST /api/grp2/CollectRequest/{orderRef}/bankid
   --> progressStatusField: 2=waiting, 1=signing, 0=complete
6. POST /api/grp2/GetCustomerByPinCode/{personnummer}/{transactionId}
   --> Returns list of customer accounts
7. If multiple accounts: user selects one
8. POST /api/grp2/Login/{personnummer}/{base64_customerId}/{transactionId}/{subUserId}
   --> Establishes session (sets ASP.NET_SessionId + .PORTALAUTH cookies)
9. GET /start.aspx to initialize session view
```

### Re-authentication

BankID cannot re-authenticate non-interactively. When a BankID session expires:

1. The coordinator raises `ConfigEntryAuthFailed`
2. Home Assistant triggers the reauth flow
3. The user must scan a new QR code

This is why cookie persistence and heartbeat are critical for BankID users -- they avoid frequent re-authentication.

### Password authentication

Password auth is straightforward:

```
POST /default.aspx/Authenticate
  {"user": "<customer_number>", "password": "<password>", "captcha": ""}
--> {"d": "{\"Result\":\"OK\", ...}"}
```

On session expiry, the integration re-authenticates automatically without user interaction.

---

## Session management

### Cookies

Two cookies maintain the session:

| Cookie | Purpose |
|--------|---------|
| `ASP.NET_SessionId` | Server-side session identifier |
| `.PORTALAUTH` | Authentication/authorization token |

Both are persisted to the config entry on every coordinator update, so they survive HA restarts.

### Heartbeat

The server-side session times out after approximately 15 minutes of inactivity. A heartbeat timer sends `GET /heart.beat` every 5 minutes to keep it alive.

### Session expiry detection

The API client detects expired sessions by checking for:
- HTTP 301/302 redirects (typically to the login page)
- HTTP 401/403 responses
- Non-JSON response content types (HTML login page instead of JSON)

On detection, password users re-authenticate automatically. BankID users trigger the HA reauth flow.

### Cookie restoration flow

```
HA restart
  --> async_setup_entry reads saved cookies from config entry
  --> api.set_session_cookies(saved_cookies)
  --> _ensure_session() restores cookies into aiohttp CookieJar
  --> First coordinator update tests the session
  --> If expired: re-auth (password) or ConfigEntryAuthFailed (BankID)
```

---

## Debug tooling

The `debug/` directory (gitignored) is intended for traffic captures, test scripts, and other debugging artifacts. See [`debug/README.md`](../debug/README.md) for detailed instructions.

### mitmproxy setup (quick reference)

```bash
# Install
brew install mitmproxy

# Start proxy with web UI
mitmweb

# Launch browser through proxy
open -na "/Applications/Vivaldi.app" --args \
  --proxy-server="http://localhost:8080" \
  --user-data-dir="/tmp/vivaldi-proxy"

# Install the CA cert from http://mitm.it in the proxied browser
```

This lets you intercept and inspect all HTTPS traffic between the browser and the Karlstads Energi portal -- invaluable when debugging API changes or discovering new endpoints.

### APK decompilation

The Android app (`se.karlstadsenergi.app.extern`) was decompiled using `jadx` and `apktool` to discover the API architecture. Key findings are documented in `research/api-architecture.md`.

### Security reminder

Never commit captured flow files, session cookies, personnummer, or passwords. Remove the mitmproxy CA certificate from your system keychain when you are done:

```bash
sudo security delete-certificate -c "mitmproxy" /Library/Keychains/System.keychain
```

---

## Easter eggs from the API

During reverse engineering, we discovered that the login endpoint has a rather... opinionated response to certain edge cases. If you send stale session cookies along with a login request, the server returns a response whose binary content decodes to a message that would make a sailor blush. We choose to interpret this as a heartfelt greeting from a fellow developer who spent one too many late nights debugging ASP.NET session state.

If you find it, know that you are not alone. We see you, backend developer. We love you. Stay strong.

---

## Useful resources

- [Home Assistant integration development docs](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [Home Assistant DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data)
- [aiohttp documentation](https://docs.aiohttp.org/)
- [`research/api-architecture.md`](../research/api-architecture.md) -- Complete API reference
- [`debug/README.md`](../debug/README.md) -- Traffic interception and APK decompilation guide
