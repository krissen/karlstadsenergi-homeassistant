# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Hourly statistics import** -- hourly consumption data is now imported into HA long-term statistics via `async_add_external_statistics`, making it available in the Energy Dashboard and history graphs
- **Cost breakdown sensors** -- six new monetary sensors exposing individual fee components from the invoice: consumption fee, power fee, fixed fee, energy tax, VAT, and total cost (SEK)
- **Monthly cost statistics import** -- fee data is imported into HA long-term statistics (one statistic per fee type), enabling cost tracking in the Energy Dashboard and history graphs
- **Configurable history depth** -- new options flow setting (1--10 years, default 2) controls how far back hourly consumption and monthly cost data is imported into long-term statistics. The portal API supports data going back to the start of the customer contract (up to ~7 years observed), but the default is 2 years to keep the initial import manageable (~17,500 hourly data points over 2 years, ~8,800 per year). The setting applies to both hourly consumption and monthly fee statistics.
- **Dark mode icons** -- brand icons and logos for HA's dark mode

### Changed
- **Widened API date range** -- consumption and fee API requests now use the customer's `ContractsStartDate` (capped by the history depth setting) instead of the portal's default ~2 month window, unlocking years of historical data that was previously inaccessible
- **Consumption sensor is now informational** -- removed `state_class: total_increasing` from the consumption entity sensor. The portal API provides delayed historical data, not real-time metering, making recorder-tracked statistics misleading. For the Energy Dashboard, use the external statistic `karlstadsenergi:electricity_consumption_{id}` which has correct hourly timestamps.
- **Cost sensors rely on external statistics only** -- removed `state_class: total` from cost sensors; monthly fee values are non-cumulative and would produce incorrect recorder-derived statistics. History is provided entirely by the external statistics import.
- **Swedish fee statistics metadata** -- long-term statistics for fee components now use Swedish display names
- **Swedish translations** -- cost sensors and history depth setting translated to Swedish

### Fixed
- **Statistics sum continuation** -- subsequent coordinator refreshes would reset the cumulative sum to near-zero, causing negative energy in the Energy Dashboard
- **Explicit null values** -- API responses with `null` for nested objects no longer cause `KeyError` or `TypeError`
- **Fee statistics unit_class** -- explicit `unit_class=None` for monetary statistics prevents HA 2026.11 deprecation warning
- **ASP.NET date parsing** -- date regex now accepts optional timezone offset (e.g. `/Date(1711920000000+0200)/`), preventing silent parse failures
- **Options flow validation** -- history years setting is now range-checked before saving

### Documentation
- Cost breakdown sensors and fee statistics reference
- Plotly Graph Card example for monthly cost visualization (with note on `statistics-graph` 12-month limit)

## [0.2.0] - 2026-03-29

### Added
- **Electricity price sensor** -- effective energy price (SEK/kWh) derived from fee breakdown, Energy Dashboard compatible
- **Spot price sensor** -- current Nord Pool SE3 spot price from Evado public API (15-min intervals), Energy Dashboard compatible
- **Contract sensors** -- one per contract (Elnät, Elhandel, Renhållning) showing contract type, dates, and net area
- Calendar entities for waste collection
- Binary sensors for "pickup tomorrow" per waste type
- Diagnostics support (Settings > Devices > Download Diagnostics)
- Hourly electricity consumption data in sensor attributes
- Detailed waste service data via GetFlexServices (with fallback)
- Options flow for configurable update interval (1--24 hours)
- Dashboard card examples (Mushroom, Button Card, built-in HA cards)
- Test fixtures based on real API response structures

### Fixed
- Electricity sensor now uses `state_class: total_increasing` for correct Energy Dashboard integration
- Spot price coordinator properly cleaned up on last config entry unload
- BankID API responses properly released to prevent connection pool leaks
- BankID login failure returns to retry flow instead of aborting
- `pickup_is_today` attribute now correctly returns false for past dates
- Electricity price sensor returns `0.0` instead of unavailable when fee is zero
- `DeviceInfo` import updated from deprecated path
- Removed synchronous file I/O for version constant at module load
- Config flow properly cleans up API session on abort
- `ContractId` now redacted in diagnostics exports
- Differentiated exception handling in spot price coordinator
- Removed incorrect `device_class: monetary` from price sensors (HA requires ISO 4217 currency code, not compound unit `SEK/kWh`)

### Changed
- Cleaned up debug logging for production use
- Spot price coordinator is now per-entry (no longer shared via hass.data)
- Contract sensors now have `entity_category: diagnostic` (shown under diagnostics in HA)
- Config entry title for BankID no longer includes customer name (privacy)
- Reauth flow uses separate translated steps for password and BankID
- Options dialog title simplified
- Customer number label no longer includes Swedish parenthetical

### Documentation
- Documentation (README, CONTRIBUTING, DEVELOPMENT)
- Entity reference with automation examples
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

[Unreleased]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/krissen/karlstadsenergi-homeassistant/releases/tag/v0.1.0
