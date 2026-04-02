# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-04-02

### Fixed
- **Electricity price sensor always showing "unknown"** -- the sensor calculated price by intersecting fee data (invoice-based, lagging ~1 month) with the OnLoad consumption chart (current billing period only), which never overlap. Now fetches monthly kWh with the same wide date range as fee data, ensuring overlap.
- **Session re-authentication losing server state** -- when a session expired mid-update, `_request()` re-authenticated but the required ASP.NET page visits were not redone with the new session, causing empty API responses. Page visits now detect expired sessions (`allow_redirects=False`) and are redone after re-authentication.

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

[Unreleased]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/krissen/karlstadsenergi-homeassistant/releases/tag/v0.1.0
