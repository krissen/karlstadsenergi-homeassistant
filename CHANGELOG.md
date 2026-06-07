# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Reauth reused an expired BankID order** -- starting a re-authentication, letting the order time out, and trying again (without restarting the integration) kept showing the same dead order, so signing failed with "wrong code" every time. Each entry into the BankID step now starts a fresh order, so a resumed or retried reauth always shows a new, signable code.
- **BankID app link opened Home Assistant instead of BankID on mobile** -- the same-device link used the `bankid://` custom scheme, which a phone could route back to the HA app. It now uses the official `https://app.bankid.com/` universal link, which the OS hands to the BankID app.
- **Heartbeat followed the logout redirect** -- a dead session 302-redirects `/heart.beat` to `/Logout.aspx`; the heartbeat followed it, so it reported success against the logout page (200) and may have logged the session out server-side. It now uses `allow_redirects=False`, treats a redirect as failure, and logs the status so session lifetime can be traced.

## [0.4.0] - 2026-06-06

### Added
- **Cross-device BankID QR code** -- the BankID setup step now shows a scannable QR code so you can authenticate from a desktop browser using the BankID app on a separate phone. Previously only same-device sign-in (tapping the `bankid://` link on the phone running Home Assistant) worked, because the QR could not be rendered in the config-flow UI. The QR is served from a small auth-free HTTP endpoint and linked from the form for clients that do not render inline images.

### Fixed
- **BankID account always required reconfiguration after setup** -- a successfully configured BankID account (including delegated/sub-user accounts) failed on the very first data refresh with "BankID requires interactive authentication", forcing a reauth loop. Restoring saved session cookies did not mark the client as authenticated, so the pre-request guard triggered a re-auth before the session applied the cookies -- fatal for BankID, which cannot re-auth without an interactive QR scan. Restored cookies now mark the client authenticated; a genuinely stale cookie is still caught by the first request's 302/401 and surfaces a reauth prompt.
- **Crash when re-submitting BankID after a failed attempt** -- a second "Submit" after a pending/failed BankID order raised `AttributeError: 'NoneType' object has no attribute 'bankid_poll'`. The step now re-initiates a fresh order instead of polling a torn-down session, and keeps the order valid across retries.
- **10-digit personnummer signed in but found no BankID accounts** -- BankID signing identifies the person by signature regardless of the typed number, but the portal's customer lookup only matches the 12-digit form, so a 10-digit entry signed successfully yet returned zero accounts ("BankID authentication failed"). A 10-digit entry is now expanded to 12 digits (century inferred from the two-digit year) before the lookup.
- **BankID session lost on restart despite a live session** -- the portal reissues the `.PORTALAUTH` forms-auth ticket with a fresh expiry on every request (sliding expiration), but the saved copy was only refreshed after the infrequent coordinator updates -- never after the 5-minute heartbeat. The persisted ticket went stale during normal operation, so a Home Assistant restart loaded an expired ticket and forced a BankID re-scan even though the running session was healthy. The heartbeat now persists the refreshed cookies, so a restart within the session window resumes without re-authentication.
- **BankID QR cache leak on retries** -- each recoverable retry during BankID sign-in started a new order without evicting the previous order's cached QR image, leaking a small amount of memory per retry for the process lifetime. The old entry is now dropped before the new order is created.
- **Locked accounts are distinguished from wrong credentials** -- the portal's `LoginResultStatus=7` (account locked) now shows a specific "account locked" message instead of the generic "invalid credentials". The credentials may be correct, so reporting them as wrong was misleading.
- **Authentication failure now surfaces reauth instead of retrying forever** -- when setup fails because credentials are invalid (and no saved session is available), the integration raises `ConfigEntryAuthFailed` to start a reauthentication flow, instead of `ConfigEntryNotReady`. Previously this path retried the portal login indefinitely on HA's schedule, which never prompted the user and could trigger a portal-side account lockout. Transient connection errors still raise `ConfigEntryNotReady` (retry).

### Changed
- **Reauthentication reload** -- reauth now updates the config entry with the non-reloading `async_update_and_abort()` and then schedules the reload explicitly, instead of using a reloading config-flow method. Resolves a Home Assistant 2026.6 deprecation (combining an update listener with a reloading config-flow method) that becomes an error in 2026.12. Reauth reloads reliably even when only the session cookie changed or when the previous setup had failed (no listener registered yet); the update listener itself continues to reload only on options changes.
- **Coordinators pass the config entry explicitly** -- all `DataUpdateCoordinator` instances now receive `config_entry=` at construction, resolving the "relies on ContextVar" deprecation warning emitted since HA 2025.x.
- **Minimum Home Assistant raised to 2025.11** -- the reauth flow now uses `async_update_and_abort()`, introduced in HA 2025.11.

## [0.3.1] - 2026-05-30

### Changed
- **Now available in HACS default** -- search "Karlstadsenergi" directly in HACS; the custom-repository step is no longer required.

### Removed
- **Duplicate brand assets at package root** -- icon/logo PNGs (light + dark, `@1x` + `@2x`) removed from the package root; `brand/` is the supported location since HA 2026.3 (~290 KB smaller install footprint).
- **Unused `GetServiceInfo` API call** -- the endpoint's response was never consumed by any entity (its `NetAreaCode` is already exposed via the contract sensor). Removing it drops a recurring debug log line and one HTTP request per consumption update.

## [0.3.0] - 2026-04-12

### Added
- **District heating (fjärrvärme) support** -- consumption, price, cost breakdown, flow, and temperature difference sensors for accounts with district heating. Separate HA device ("Karlstadsenergi Fjärrvärme"). Long-term statistics import for DH consumption and fees. Based on @bazuz's contribution (#7).
- **District heating flow sensor** (m³) -- cumulative water flow volume (*unverified: depends on API support for `Loadoptions: ["Flow"]`*)
- **District heating temperature difference sensor** (°C) -- supply/return dT (*unverified: depends on API support for `Loadoptions: ["DT"]`*)
- **Account utility type logging** -- available utilities (E = electricity, F = district heating) logged at info level on each DH coordinator update

### Changed
- **Shared coordinator base class** -- electricity and district heating coordinators share `_UtilityConsumptionCoordinator` for statistics import, date widening, and ASP.NET date parsing
- **Shared sensor base classes** -- `_UtilityConsumptionSensor`, `_UtilityPriceSensor`, `_UtilityCostSensor` eliminate duplication between electricity and DH sensors
- **DH coordinator reads base model from electricity coordinator** -- avoids duplicate page visits and API calls
- **Conditional DH entity creation** -- DH sensors only created when account has district heating (listener pattern)

## [0.2.1] - 2026-04-03

### Fixed
- **Electricity price sensor always showing "unknown"** -- the sensor calculated price by intersecting fee data (invoice-based, lagging ~1 month) with the OnLoad consumption chart (current billing period only), which never overlap. Now fetches monthly kWh with the same wide date range as fee data, ensuring overlap.
- **Session re-authentication losing server state** -- when a session expired mid-update, `_request()` re-authenticated but the required ASP.NET page visits were not redone with the new session, causing empty API responses. Page visits now detect expired sessions (`allow_redirects=False`) and are redone after re-authentication. All API methods that depend on page visits (consumption, flex services, contracts, monthly kWh, fee data) use this pattern.

### Changed
- **Electricity price uses latest invoiced month** -- price sensor now shows the most recent month's effective price instead of averaging over the full history. Falls back to period average when the latest month is unavailable. New `price_source` attribute indicates which method is used (`latest_month` or `period_average`).
- **Simplified price sensor attributes** -- shows single-month fee breakdown (`fee_month`, `consumption_kwh`, per-fee amounts) instead of cumulative multi-year totals.

### Added
- **Monthly kWh comparison attributes** on consumption sensor -- `latest_month_kwh`, `previous_month_kwh`, `same_month_last_year_kwh` for year-over-year comparison in Lovelace cards. Falls back to previous month when same-month-last-year is unavailable.
- **`async_get_monthly_consumption` API method** -- lightweight endpoint (~26 rows) fetching monthly kWh data independently of hourly metering access.

## [0.2.0] - 2026-04-01

### Added
- **Cost breakdown sensors** -- six new monetary sensors exposing individual fee components from the invoice: consumption fee, power fee, fixed fee, energy tax, VAT, and total cost (SEK)
- **Hourly statistics import** -- hourly consumption data is now imported into HA long-term statistics via `async_add_external_statistics`, making it available in the Energy Dashboard and history graphs
- **Monthly cost statistics import** -- fee data is imported into HA long-term statistics (one statistic per fee type), enabling cost tracking in the Energy Dashboard and history graphs
- **Configurable history depth** -- new options flow setting (1--10 years, default 2) controls how far back hourly consumption and monthly cost data is imported into long-term statistics
- **Electricity price sensor** -- effective energy price (SEK/kWh) derived from fee breakdown
- **Spot price sensor** -- current Nord Pool SE3 spot price from Evado public API (15-min intervals)
- **Contract sensors** -- one per contract (Elnät, Elhandel, Renhållning) showing contract type, dates, and net area
- Calendar entities for waste collection
- Binary sensors for "pickup tomorrow" per waste type
- Diagnostics support (Settings > Devices > Download Diagnostics)
- Hourly electricity consumption data in sensor attributes
- Detailed waste service data via GetFlexServices (with fallback)
- Options flow for configurable update interval (1--24 hours)
- Dashboard card examples (Mushroom, Button Card, built-in HA cards)
- Dark mode icons
- Test fixtures based on real API response structures

### Changed
- **Consumption sensor is now informational** -- removed `state_class: total_increasing` from the consumption entity sensor. The portal API provides delayed historical data, not real-time metering. For the Energy Dashboard, use the external statistic `karlstadsenergi:electricity_consumption_{id}` which has correct hourly timestamps.
- **Cost sensors rely on external statistics only** -- cost sensors have no `state_class`; monthly fee values are non-cumulative and would produce incorrect recorder-derived statistics. History is provided entirely by the external statistics import.
- **Widened API date range** -- consumption and fee API requests now use the customer's `ContractsStartDate` (capped by the history depth setting) instead of the portal's default ~2 month window
- Spot price coordinator is now per-entry (no longer shared via hass.data)
- Contract sensors now have `entity_category: diagnostic`
- Config entry title for BankID no longer includes customer name (privacy)
- Reauth flow uses separate translated steps for password and BankID
- Swedish translations for cost sensors and history depth setting
- Cleaned up debug logging for production use

### Fixed
- **Statistics sum continuation** -- subsequent coordinator refreshes would reset the cumulative sum to near-zero, causing negative energy in the Energy Dashboard
- **Explicit null values** -- API responses with `null` for nested objects no longer cause `KeyError` or `TypeError`
- **Fee statistics unit_class** -- explicit `unit_class=None` for monetary statistics prevents HA 2026.11 deprecation warning
- **ASP.NET date parsing** -- date regex now accepts optional timezone offset (e.g. `/Date(1711920000000+0200)/`)
- **Options flow validation** -- history years setting is now range-checked with dedicated error messages
- **Date range start time** -- `_widen_start_date` now targets midnight UTC instead of inheriting current time
- Spot price coordinator properly cleaned up on last config entry unload
- BankID API responses properly released to prevent connection pool leaks
- BankID login failure returns to retry flow instead of aborting
- `pickup_is_today` attribute now correctly returns false for past dates
- Electricity price sensor returns `0.0` instead of unavailable when fee is zero
- Removed incorrect `device_class: monetary` from price sensors
- Config flow properly cleans up API session on abort
- `ContractId` now redacted in diagnostics exports

### Documentation
- Entity reference with Energy Dashboard setup guide
- Cost breakdown sensors and fee statistics reference
- Plotly Graph Card example for monthly cost visualization
- Dashboard card examples with multiple approaches

## [0.1.0] - 2026-03-28

First working release.

### Added
- **Waste collection sensors** -- next pickup date per waste type
  - Mat- och restavfall (food and residual waste)
  - Glas/Metall (glass/metal)
  - Plast- och pappersförpackningar (plastic/paper packaging)
  - Attributes: address, container size, frequency, days until pickup
- **Electricity consumption sensor** -- daily kWh
  - Year-over-year comparison
  - Monthly breakdown
  - Average daily consumption
- **BankID authentication** with QR code scanning
- **Password authentication** (kundnummer + lösenord) with auto-reauth
- **Account selection** for users with access to multiple customer accounts
- **Session management** -- heartbeat keep-alive, cookie persistence, reauth flow
- Swedish and English translations

### Technical notes
- Reverse-engineered API from Karlstadsenergi's customer portal (Evado MFR platform)
- Cookie-based ASP.NET session authentication
- Two DataUpdateCoordinators (waste: 6h, consumption: 1h intervals)
- HACS compatible (custom repository)

[Unreleased]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/krissen/karlstadsenergi-homeassistant/releases/tag/v0.1.0
