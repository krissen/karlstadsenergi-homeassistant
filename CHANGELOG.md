# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Electricity price sensor** -- effective energy price (SEK/kWh) derived from fee breakdown, Energy Dashboard compatible
- **Spot price sensor** -- current Nord Pool SE3 spot price from Evado public API (15-min intervals), Energy Dashboard compatible
- **Contract sensors** -- one per contract (Elnät, Elhandel, Renhållning) showing contract type, dates, GSRN, and net area
- Calendar entities for waste collection (TrashCard compatible)
- Binary sensors for "pickup tomorrow" per waste type
- Diagnostics support (Settings > Devices > Download Diagnostics)
- Hourly electricity consumption data in sensor attributes
- Detailed waste service data via GetFlexServices (with fallback)

### Fixed
- Electricity sensor now compatible with HA Energy Dashboard (`last_reset` added)

### Changed
- Cleaned up debug logging for production use
- Added comprehensive documentation (README, CONTRIBUTING, DEVELOPMENT)

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

### Technical
- Reverse-engineered API from Karlstadsenergi's customer portal (Evado MFR platform)
- Cookie-based ASP.NET session authentication
- Two DataUpdateCoordinators (waste: 6h, consumption: 1h intervals)
- HACS compatible (custom repository)

[Unreleased]: https://github.com/krissen/karlstadsenergi-homeassistant/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/krissen/karlstadsenergi-homeassistant/releases/tag/v0.1.0
