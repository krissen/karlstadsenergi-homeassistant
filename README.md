# Karlstadsenergi for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]][license]

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

A Home Assistant integration for [Karlstads Energi](https://www.karlstadsenergi.se/) customers. Track waste collection pickup dates and electricity consumption.

> **Disclaimer:** This is an unofficial integration built entirely for personal use. It talks to Karlstads Energi's customer portal through a reverse-engineered API that could break at any time -- so we really can't recommend that anyone else use it.
>
> It exists because [@krissen](https://github.com/krissen) got new waste bins with a new pickup schedule and kept dragging the wrong ones to the curb on cold Värmland mornings. Automation to the rescue. It's shared here in case someone else in Karlstad has the same problem. If that's you -- välkommen, and good luck.

<table align="center"><tr>
  <td><img width="450" alt="Button Card with color-coded waste pickup dates" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/button-card.png" /></td>
  <td><img width="450" alt="Monthly electricity cost breakdown (Plotly)" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/cost-monthly-plotly.png" /></td>
</tr></table>

> *Right: Monthly cost breakdown rendered with [Plotly Graph Card](https://github.com/dbuezas/lovelace-plotly-graph-card). The winter spike? That's [@krissen](https://github.com/krissen) running a full-scale bathroom renovation from November -- turns out power tools don't do wonders for the electricity bill --- especially not when combined with Swedish winters.*

---

## Features

- **Waste collection sensors** -- Next pickup date for each waste type (food & residual waste, glass/metal, plastic & paper packaging)
- **Waste collection calendar** -- Calendar entities, works with HA's built-in Calendar card and [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom)
- **Pickup reminders** -- Binary sensors for "pickup tomorrow" per waste type
- **Electricity consumption** -- Daily and hourly consumption data with year-over-year comparison, Energy Dashboard compatible
- **Electricity price** -- Effective energy price (SEK/kWh) derived from your invoice fee breakdown, Energy Dashboard compatible
- **Cost breakdown** -- Individual sensors for each invoice fee component: consumption fee, power fee, fixed fee, energy tax, VAT, and total cost (SEK), with monthly long-term statistics for the Energy Dashboard
- **Spot price** -- Current Nord Pool SE3 spot price (15-minute intervals) from Karlstadsenergi/Evado public API
- **Historical statistics** -- Hourly consumption and monthly cost data imported into HA long-term statistics with configurable depth (1--10 years, default 2). The portal API has data going back to contract start -- this integration unlocks it for Energy Dashboard graphs and history analysis.
- **Contract overview** -- Sensors for each contract (grid, trading, waste) with contract type, dates, and identifiers
- **Computed attributes** -- `days_until_pickup`, `pickup_is_today`, `pickup_is_tomorrow`
- **Session management** -- Cookie persistence across restarts and automatic re-authentication on session expiry (silent and indefinite for password logins; BankID expires after ~15 min and needs a manual re-scan -- see below). When the session expires, sensors keep their last values (marked `data_stale`) instead of going unavailable, and those values are cached on disk so they also survive a Home Assistant restart or integration reload (the re-authentication prompt still appears when action is needed).
- **Configurable update interval** -- Set how often data is refreshed (1--24 hours)

---

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Search for **Karlstadsenergi** and click **Download**.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/karlstadsenergi` directory into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for `Karlstadsenergi`.
3. Choose your authentication method (see below).

### Authentication methods

The integration supports two login methods. **Customer number & password is by far the best** -- it re-authenticates silently and indefinitely, with no recurring interaction. Mobile BankID is a last resort: the portal expires a BankID session after ~15 minutes and there is no way to keep it alive, so it needs frequent manual re-scans (details below).

| | Customer number & password | Mobile BankID |
|---|---|---|
| **Recommended** | **Yes** | **No** -- last resort only |
| Session lifetime | Indefinite -- silent re-login | **~15 min**, then manual QR re-scan |
| Re-auth on expiry / restart | Automatic, no interaction | Manual BankID sign-in every time |
| Setup complexity | Simple | Requires BankID app sign-in |
| Multi-account | Logs in directly | Select the account at sign-in |

#### Customer number & password (recommended)

1. Select **Kundnummer & lösenord**.
2. Enter your Karlstads Energi customer number and password.

> **Don't have a password yet?** Go to [Karlstadsenergi Password Reset](https://minasidor.karlstadsenergi.se/Customer/PasswordReset.aspx). Have your customer number ready (found on your invoice). Enter the customer number and a password reset link will be sent to the email address Karlstads Energi has on file for your account. Then you're good to go!

#### Mobile BankID (last resort -- not recommended)

> **Warning:** BankID is a fallback only, for users who genuinely cannot use password login. The Karlstadsenergi portal expires a BankID session after **~15 minutes**, and there is **no way to keep it alive or re-authenticate automatically** -- verified by extensive testing (heartbeats, token replay, and the official app's own mechanism all expire on the same 15-minute limit). In practice, Home Assistant will prompt you to **re-scan the BankID QR roughly every ~15 minutes** of operation, which makes BankID impractical for unattended use. To soften this, sensors keep their last values (marked `data_stale`) between re-scans instead of going blank, and a re-scan acts as a refresh. **If at all possible, use customer number & password instead** (see the password-reset link above).

1. Select **Mobilt BankID**.
2. Enter your personnummer (10 or 12 digits -- a 10-digit number is expanded automatically).
3. **Scan the QR code** with the BankID app on your phone, or -- if Home Assistant is open on the same phone -- tap the **Open BankID app** link, then sign in.
4. If your personnummer is linked to multiple accounts, select which one to use.

> **On a phone:** the in-app "Open BankID app" link may not launch BankID from inside the Home Assistant Companion app (it can route back to Home Assistant). If that happens, scan the QR code from a computer, or open this page in your phone's browser. Cross-device -- Home Assistant on a computer, BankID app on your phone -- is the most reliable.

### Options

After setup, go to **Settings -> Devices & Services -> Karlstadsenergi -> Configure** to adjust:

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| Update interval | 6 hours | 1--24 hours | How often to fetch new data |
| Statistics history | 2 years | 1--10 years | How far back to import hourly consumption and monthly cost data |

> **Tip:** Waste pickup dates rarely change, so 6--12 hours is usually sufficient. Electricity consumption updates more frequently (1/6 of the waste interval, minimum 1 hour). The history setting controls the initial backfill depth -- the first refresh fetches the full historical range, and subsequent refreshes use a shorter window while still importing any new data points. Two years imports ~17,500 hourly data points; larger values are fine but the initial import takes longer.

---

## Entities and automations

<table><tr>
  <td><img width="420" alt="Built-in entities card with pickup dates and tomorrow alert" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/builtin-entities.png" /></td>
  <td><img width="420" alt="Hourly electricity consumption chart" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/consumption-hourly.png" /></td>
</tr></table>

See **[Entities](docs/user/entities.md)** for a reference of all sensors, calendars, binary sensors, and their attributes, with automation examples.

---

## Dashboard examples

<table align="center"><tr>
  <td><img width="420" alt="Mushroom chips showing days until pickup" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/mushroom-chips.png" /></td>
  <td><img width="420" alt="Calendar view with waste collection events" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/calendar.png" /></td>
</tr><tr>
  <td><img width="420" alt="Mushroom cards with monthly consumption and cost" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/mushroom-electricity.png" /></td>
  <td><img width="420" alt="Entities card with consumption, invoice price and spot price" src="https://raw.githubusercontent.com/krissen/karlstadsenergi-homeassistant/main/docs/images/electricity.png" /></td>
</tr></table>

See **[Dashboard examples](docs/user/dashboard-examples.md)** for card configurations using Mushroom Cards, Custom Button Card, and the built-in Calendar card.

---

## Advanced usage

See **[Advanced usage](docs/user/advanced.md)** for service calls, manual data refresh, template sensors (pickup countdown, cost estimates, price level), spot price automations, and smart plug control.

---

## Troubleshooting

See the **[Troubleshooting guide](docs/user/troubleshooting.md)** for solutions to common issues (sensors unavailable, missing data, authentication problems, Energy Dashboard setup).

---

## Known limitations

### Electricity consumption data lag

The portal API provides historical consumption data only. Depending on your meter and billing cycle, data may lag days or weeks behind real-time. The `latest_date` attribute on the electricity consumption sensor shows the actual date of the most recent data point -- use this to judge how current the data is.

### Electricity consumption and Energy Dashboard

The consumption sensor is informational only (no `state_class`) because the portal API provides delayed historical data, not real-time metering. For the Energy Dashboard, use the external statistic `karlstadsenergi:electricity_consumption_<customer_id>`, which is imported with correct hourly timestamps. See the [Troubleshooting guide](docs/user/troubleshooting.md#energy-dashboard-shows-incorrect-consumption-or-cost-values) for details on choosing the right statistic.

### Orphaned entity registry entries

The integration creates waste entities in one of two modes -- detailed (one entity per service line) or summary (one entity per waste type) -- depending on what data the API returns at startup. If the mode changes between restarts (for example, the detailed Flex API becomes available after initially being unreachable), both sets of entities may appear in the entity registry and the old set will show as "unavailable". To remove the stale entries: go to **Settings -> Devices & Services -> Entities**, filter by "unavailable", and delete them manually.

### Personnummer in API URLs

The upstream Karlstadsenergi portal API requires the personnummer in URL paths when authenticating via BankID. All communication with the portal uses HTTPS, so the URL path (including the personnummer) is encrypted in transit. This is an upstream API design decision that this integration cannot change.

---

## Development

See **[Development documentation](docs/DEVELOPMENT.md)** for architecture details, API notes, and how to set up a development environment.

---

## Data source

All data is retrieved from the [Karlstads Energi customer portal](https://minasidor.karlstadsenergi.se). This integration is not affiliated with or endorsed by Karlstads Energi AB.

---

[Want to support development? Buy me a coffee!](https://coff.ee/krissen)

---

[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Default-blue.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/krissen/karlstadsenergi-homeassistant.svg?style=for-the-badge
[license]: https://github.com/krissen/karlstadsenergi-homeassistant/blob/main/LICENSE
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40krissen-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/krissen/karlstadsenergi-homeassistant.svg?style=for-the-badge
[releases]: https://github.com/krissen/karlstadsenergi-homeassistant/releases
[user_profile]: https://github.com/krissen
[buymecoffee]: https://coff.ee/krissen
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
