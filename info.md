# Karlstadsenergi for Home Assistant

A Home Assistant integration for [Karlstads Energi](https://www.karlstadsenergi.se/) customers. Track waste collection pickup dates and electricity consumption from the customer portal ("Mina sidor").

## Features

- **Waste collection** -- Next pickup date per waste type with computed attributes like `days_until_pickup` and `pickup_is_tomorrow`.
- **Electricity consumption** -- Daily and hourly consumption data with year-over-year comparison.
- **BankID and password login** -- Choose the authentication method that suits you.
- **Session persistence** -- Automatic keepalive and cookie persistence across HA restarts.

## Installation

1. Add this repository as a **Custom Repository** in HACS (category: Integration).
   - Repository URL: `https://github.com/krissen/karlstadsenergi-homeassistant`
2. Install **Karlstadsenergi**.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for `Karlstadsenergi`.
3. Choose **Kundnummer & lösenord** (recommended) or **Mobilt BankID** and follow the prompts.

## Sensors

| Sensor | State | Attributes |
|--------|-------|------------|
| Food & residual waste | Next pickup date | address, container_size, frequency, days_until_pickup, pickup_is_today, pickup_is_tomorrow |
| Glass/Metal | Next pickup date | (same as above) |
| Plastic & paper packaging | Next pickup date | (same as above) |
| Electricity consumption | Latest day (kWh) | meter_number, total_this_period, monthly_consumption, hourly_consumption, and more |

## Notes

- This integration is not affiliated with Karlstads Energi AB.
- The API is reverse-engineered from the customer portal and may change without notice.
