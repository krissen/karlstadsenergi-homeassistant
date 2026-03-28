# Karlstadsenergi for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]

A Home Assistant integration for [Karlstads Energi](https://www.karlstadsenergi.se/) customers. Track your waste collection pickup dates and monitor electricity consumption -- all from within Home Assistant.

> **Note:** This integration communicates with the Karlstads Energi customer portal ("Mina sidor") and requires a valid customer account.

---

## Features

- **Waste collection sensors** -- Next pickup date for each waste type (food & residual waste, glass/metal, plastic & paper packaging)
- **Waste collection calendar** -- Calendar entities compatible with [TrashCard](https://github.com/idaho/hassio-trash-card) and HA's built-in Calendar card
- **Pickup reminders** -- Binary sensors for "pickup tomorrow" per waste type
- **Electricity consumption** -- Daily and hourly consumption data with year-over-year comparison, Energy Dashboard compatible
- **Computed attributes** -- `days_until_pickup`, `pickup_is_today`, `pickup_is_tomorrow` for easy automations
- **Session management** -- Automatic session keepalive (heartbeat), cookie persistence across restarts, and re-authentication on session expiry
- **Configurable update interval** -- Set how often data is refreshed (1--24 hours)

---

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** and click the three-dot menu in the top right.
3. Select **Custom repositories**.
4. Add `https://github.com/krissen/karlstadsenergi-homeassistant` as an **Integration**.
5. Search for **Karlstadsenergi** and install it.
6. Restart Home Assistant.

### Manual

1. Copy the `custom_components/karlstadsenergi` directory into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for `Karlstadsenergi`.
3. Choose your authentication method (see below).

### Authentication methods

The integration supports two login methods. **Customer number & password is strongly recommended.**

| | Customer number & password | Mobile BankID |
|---|---|---|
| **Recommended** | **Yes** | **No** -- avoid if possible |
| Auto-reconnect on HA restart | **Yes** -- seamless | **No** -- requires manual re-scan |
| Session handling | Automatic re-login | Heartbeat keep-alive only |
| Setup complexity | Simple | Requires QR scan within 30s |
| Multi-account | Logs in directly | Must select account each time |

#### Customer number & password (recommended)

1. Select **Kundnummer & lösenord**.
2. Enter your Karlstads Energi customer number and password.

> **Don't have a password yet?** Go to [Karlstadsenergi Password Reset](https://minasidor.karlstadsenergi.se/Customer/PasswordReset.aspx). Have your customer number ready (found on your invoice). Enter the customer number and a password reset link will be sent to the email address Karlstads Energi has on file for your account. Then you're good to go!

#### Mobile BankID (not recommended)

> **Warning:** BankID is available but **we do not recommend using it.** When Home Assistant restarts, the session expires and **you must scan a new QR code manually** every time to reconnect. There is no way to automate BankID re-authentication. It is only included as a fallback for users who cannot set up password login. If at all possible, set up customer number & password instead.

1. Select **Mobilt BankID**.
2. Enter your personnummer (Swedish personal identity number).
3. A QR code will be displayed -- scan it with your BankID app and sign.
4. If your personnummer is linked to multiple accounts, select which one to use.

### Options

After setup, go to **Settings -> Devices & Services -> Karlstadsenergi -> Configure** to change the update interval (default: 6 hours, range: 1--24 hours).

> **Tip:** Waste pickup dates rarely change, so 6--12 hours is usually sufficient. Electricity consumption updates more frequently (1/6 of the waste interval, minimum 1 hour).

---

## Entities

### Waste collection sensors

One sensor is created per active waste collection service at your address.

| Sensor | Entity ID example | State | Device class |
|--------|-------------------|-------|--------------|
| Food & residual waste | `sensor.karlstadsenergi_food_and_residual_waste` | Next pickup date | `date` |
| Glass/Metal | `sensor.karlstadsenergi_glass_metal` | Next pickup date | `date` |
| Plastic & paper packaging | `sensor.karlstadsenergi_plastic_paper_packaging` | Next pickup date | `date` |

#### Waste sensor attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `address` | string | Pickup address |
| `container_size` | string | Container size (e.g. "240 L") |
| `frequency` | string | Pickup frequency (e.g. "Varannan vecka") |
| `service_id` | int | Internal service identifier |
| `days_until_pickup` | int | Days remaining until next pickup |
| `pickup_is_today` | bool | `true` if pickup is today |
| `pickup_is_tomorrow` | bool | `true` if pickup is tomorrow |

### Waste collection calendar

One calendar entity per waste type, compatible with [TrashCard](https://github.com/idaho/hassio-trash-card) and HA's built-in Calendar card.

| Calendar | Entity ID example | Event |
|----------|-------------------|-------|
| Food & residual waste | `calendar.karlstadsenergi_food_and_residual_waste_calendar` | All-day event on pickup date |
| Glass/Metal | `calendar.karlstadsenergi_glass_metal_calendar` | All-day event on pickup date |
| Plastic & paper packaging | `calendar.karlstadsenergi_plastic_paper_packaging_calendar` | All-day event on pickup date |

### Pickup tomorrow binary sensors

| Binary sensor | Entity ID example | State |
|---------------|-------------------|-------|
| Food & residual waste | `binary_sensor.karlstadsenergi_food_and_residual_waste_pickup_tomorrow` | `on` if pickup is tomorrow |
| Glass/Metal | `binary_sensor.karlstadsenergi_glass_metal_pickup_tomorrow` | `on` if pickup is tomorrow |
| Plastic & paper packaging | `binary_sensor.karlstadsenergi_plastic_paper_packaging_pickup_tomorrow` | `on` if pickup is tomorrow |

### Electricity consumption sensor

| Sensor | Entity ID example | State | Unit | Device class |
|--------|-------------------|-------|------|--------------|
| Electricity consumption | `sensor.karlstadsenergi_electricity_consumption` | Latest day's kWh | kWh | `energy` |

#### Electricity sensor attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `meter_number` | string | Electricity meter number |
| `service_identifier` | string | Service/contract identifier |
| `net_area` | string | Network area ID |
| `total_this_period` | float | Total consumption this period |
| `total_last_year_period` | float | Same period last year |
| `difference_percentage` | float | Year-over-year change (%) |
| `average_daily` | float | Average daily consumption (current) |
| `average_daily_last_year` | float | Average daily consumption (last year) |
| `monthly_consumption` | dict | Monthly breakdown (`{"2026-01": 450.2, ...}`) |
| `latest_date` | string | Date of the latest data point |
| `hourly_consumption` | list | Last 24 hours (`[{"time": "...", "kWh": 1.2}, ...]`) |
| `hourly_data_points` | int | Total number of hourly data points |

---

## Automation examples

### Notify when pickup is tomorrow

```yaml
automation:
  - alias: "Waste pickup reminder"
    trigger:
      - platform: state
        entity_id: sensor.karlstadsenergi_food_and_residual_waste
    condition:
      - condition: state
        entity_id: sensor.karlstadsenergi_food_and_residual_waste
        attribute: pickup_is_tomorrow
        state: true
    action:
      - service: notify.mobile_app
        data:
          title: "Waste pickup tomorrow"
          message: >
            {{ state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'address') }}:
            Food & residual waste pickup is tomorrow.
```

### Template sensor for days until pickup

```yaml
template:
  - sensor:
      - name: "Days until waste pickup"
        state: >
          {{ state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') }}
        unit_of_measurement: "days"
```

---

## Troubleshooting

### BankID authentication fails

- Make sure you are signing with the correct personnummer in BankID.
- The QR code has a limited validity window. If it expires, click Submit again to generate a new one.
- If re-authentication is triggered (session expired), you will need to scan a new QR code.

### Sensors show "unavailable"

- The Karlstads Energi portal may be temporarily down for maintenance.
- Your session may have expired. The integration will attempt to re-authenticate automatically. For BankID users, a re-authentication prompt will appear in Home Assistant notifications.
- Check the Home Assistant logs for error details.

### Consumption data is missing

- Electricity consumption data requires that the server-side session state is properly initialized. The integration handles this by visiting required pages before making API calls.
- Not all customer accounts have electricity services. If you only have waste collection, this is expected.

### Update interval

- Waste data updates at the configured interval (default: 6 hours).
- Electricity consumption updates 6x more frequently (default: 1 hour).
- To trigger an immediate refresh, use the `homeassistant.update_entity` service.

---

## Data source

All data is retrieved from the [Karlstads Energi customer portal](https://minasidor.karlstadsenergi.se). This integration is not affiliated with or endorsed by Karlstads Energi AB.

---

[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/krissen/karlstadsenergi-homeassistant.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40krissen-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/krissen/karlstadsenergi-homeassistant.svg?style=for-the-badge
[releases]: https://github.com/krissen/karlstadsenergi-homeassistant/releases
[user_profile]: https://github.com/krissen
