# Karlstadsenergi for Home Assistant

A Home Assistant integration for [Karlstads Energi](https://www.karlstadsenergi.se/) customers. Track waste collection pickup dates and electricity consumption from the customer portal ("Mina sidor").

## Features

- **Waste collection** -- Next pickup date per waste type, calendar entities, and "pickup tomorrow" binary sensors.
- **Electricity consumption** -- Daily and hourly kWh with year-over-year comparison. Energy Dashboard compatible.
- **Electricity price** -- Effective energy price (SEK/kWh) derived from your invoice fee breakdown. Energy Dashboard compatible.
- **Spot price** -- Current Nord Pool SE3 spot price (15-minute intervals). Energy Dashboard compatible.
- **Contracts** -- Overview of your grid, trading, and waste contracts with dates and identifiers.
- **Password and BankID login** -- Password is recommended for automatic reconnection.

## Installation

1. Add this repository as a **Custom Repository** in HACS (category: Integration).
   - Repository URL: `https://github.com/krissen/karlstadsenergi-homeassistant`
2. Install **Karlstadsenergi**.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for `Karlstadsenergi`.
3. Choose **Kundnummer & lösenord** (recommended) or **Mobilt BankID** and follow the prompts.

## Notes

- **Password login is strongly recommended.** BankID requires manual re-authentication (QR scan) after every HA restart.
- This integration is not affiliated with Karlstads Energi AB.
- The API is reverse-engineered from the customer portal and may change without notice.
