# Troubleshooting

This guide covers common issues with the Karlstadsenergi integration and how to resolve them. If your issue is not listed here, please [open a GitHub issue](https://github.com/krissen/karlstadsenergi-homeassistant/issues/new/choose) with the diagnostic information described in [Collecting diagnostic information](#collecting-diagnostic-information).

## Before you report an issue

Most issues fall into a few known categories. Please work through this checklist before opening an issue:

1. **Verify your integration version** (see [How to find your integration version](#1-integration-version-required))
2. **Check the Karlstads Energi portal** -- go to [minasidor.karlstadsenergi.se](https://minasidor.karlstadsenergi.se) and log in. If the portal itself is down or returning errors, the integration cannot fetch data either.
3. **Check Home Assistant logs** -- go to Settings > System > Logs and search for `karlstadsenergi`. Copy any error messages.
4. **Check your entity states** -- go to Developer Tools > States (Settings > Developer Tools > States in HA 2026.2+) and search for `karlstadsenergi`. Note whether sensors show "unavailable", "unknown", or have values.
5. **Restart Home Assistant** -- Settings > System > three-dot menu (top right) > Restart Home Assistant

If the issue persists after these steps, open an issue with the diagnostic info from the template.

> **Note:** This integration uses a reverse-engineered API from the Karlstads Energi customer portal. The API is undocumented and could change at any time. Some issues may be caused by changes on the portal side rather than bugs in the integration.

---

## Common issues

### Sensors show "unavailable"

All or some sensors show "unavailable" in Home Assistant.

**Likely causes:**

1. **The Karlstads Energi portal is down.** Check by logging in at [minasidor.karlstadsenergi.se](https://minasidor.karlstadsenergi.se). If you cannot log in there either, the issue is on their end. Wait and the integration will recover automatically when the portal comes back.

2. **Your session has expired.** The portal uses ASP.NET session cookies with a short server-side lifetime.
   - As of the latest version, entities **keep their last values** when a session expires (instead of going `unavailable`) and set the `data_stale` attribute to `true`. These cached values also survive a Home Assistant restart or an integration reload, so a restart no longer blanks the sensors. So if your sensors are genuinely `unavailable`, the cause is usually the portal being down or a first-time setup that never succeeded -- not an expired session.
   - **Password users:** The integration re-authenticates automatically; sessions rarely go stale. Check the HA logs for re-authentication errors.
   - **BankID users:** BankID sessions expire after only ~15 minutes and cannot be kept alive, so you will see a recurring re-authentication ("Reconfigure") prompt. Sensors keep showing their last values (marked `data_stale`) in the meantime. Go to Settings > Devices & Services > Karlstadsenergi > Reconfigure and sign in with BankID again to refresh. See the BankID section below.

3. **Orphaned entities from a mode switch.** The integration creates waste entities in one of two modes (detailed per-service-line or summary per-waste-type) depending on what data the Flex API returns. If the mode changes between restarts, the old set of entities becomes "unavailable".
   - **How to fix:** Go to Settings > Devices & Services > Entities, filter by "unavailable", and delete the stale karlstadsenergi entities. The current entities will continue working normally.

4. **Home Assistant was recently updated.** Occasionally, a new HA version changes internal APIs that integrations depend on. Check the [CHANGELOG](https://github.com/krissen/karlstadsenergi-homeassistant/blob/HEAD/CHANGELOG.md) for compatibility notes, and update the integration to the latest version via HACS.

---

### Electricity price sensor shows "unknown"

The Electricity price sensor (e.g. `sensor.karlstadsenergi_electricity_price_12345`; entity IDs vary by installation) stays at "unknown" instead of showing a value.

**Why this happens:**

The price sensor calculates an effective energy price (SEK/kWh) from your invoice fee breakdown. Fee data is invoice-based and typically lags about one month behind. This means:

- **Right after installation**, the price sensor may show "unknown" until the integration has fetched fee data that overlaps with available consumption data.
- **At the start of a new billing period**, the most recent month may not yet have fee data available. The sensor will fall back to the period average. If no fee data at all is available yet, the sensor shows "unknown".

**What to check:**

1. Look at the sensor's attributes in Developer Tools > States. The `price_source` attribute tells you whether the price is based on `latest_month` or `period_average`.
2. If you only recently set up electricity services with Karlstads Energi, fee data may simply not exist yet on the portal.
3. Verify that you can see invoice/fee data when you log in to the portal directly.

---

### Electricity consumption data missing or lagging

The consumption sensor shows old data, or consumption values are missing.

**Important to understand:** The Karlstads Energi portal provides **historical** consumption data, not real-time metering. Data typically lags days or even weeks behind, depending on your meter and billing cycle.

**What to check:**

1. Look at the `latest_date` attribute on the consumption sensor. This shows the actual date of the most recent data point. If this is a few days old, that is normal behavior.
2. Not all customer accounts have electricity services. If you only have a waste collection contract, the consumption sensor will not appear at all. This is expected.
3. Verify that consumption data appears when you log in to the portal directly.

**Update frequency:** The consumption coordinator updates at 1/6 of your configured waste update interval (default: once per hour when the waste interval is 6 hours). You can trigger an immediate refresh using the `homeassistant.update_entity` service call on the consumption sensor.

---

### BankID authentication problems

**Common issues:**

1. **BankID token expired.** The BankID start token has a limited validity window. If it expires before you sign, click Submit again to start a new attempt.

2. **Wrong personnummer.** Make sure the personnummer you entered matches the one linked to your Karlstads Energi account.

3. **Session expired, need to sign in again (frequently).** A BankID session on this portal expires after only **~15 minutes** and **cannot be kept alive or renewed automatically** -- this was verified by extensive testing (HTTP keepalives, the durable token the official app uses, and a SignalR connection all expire on the same 15-minute limit). So Home Assistant will prompt you to re-scan the BankID QR roughly every ~15 minutes of operation. To soften this, sensors keep their last values (marked `data_stale`) between re-scans -- and those values are cached on disk, so they also survive a Home Assistant restart or an integration reload instead of going `unavailable`. Each re-scan refreshes them and backfills missing energy history. The "Reconfigure" prompt still appears whenever a re-scan is actually needed (the cache never hides it). There is no way to make BankID unattended; it is a last resort.

4. **The "Open BankID app" link does nothing / returns to Home Assistant (on a phone).** Inside the Home Assistant Companion app, the in-app link may not launch BankID. Scan the QR code from a computer instead, or open the config page in your phone's regular browser. Cross-device (HA on a computer, BankID app on your phone) is the most reliable.

**Strong recommendation:** If at all possible, switch to customer number and password authentication instead. It re-authenticates silently and indefinitely and is far more reliable for long-term use. See the [README](https://github.com/krissen/karlstadsenergi-homeassistant/blob/HEAD/README.md#authentication-methods) for setup instructions. You can set up a password at [Karlstadsenergi Password Reset](https://minasidor.karlstadsenergi.se/Customer/PasswordReset.aspx).

---

### Energy Dashboard shows incorrect consumption or cost values

**Possible causes:**

1. **Statistics sum reset (fixed in v0.2.0).** In earlier versions, subsequent coordinator refreshes could reset the cumulative sum to near-zero, causing negative energy readings in the Energy Dashboard. Update to v0.2.0 or later.

2. **Retroactive billing corrections.** If Karlstads Energi retroactively adjusts your consumption data downward (e.g., a billing correction), HA's long-term statistics may show inflated totals. This is a known limitation of how `total_increasing` works with API data sources. No such corrections have been observed in practice, but it is theoretically possible.

3. **Wrong statistic selected.** The integration provides two kinds of data:
   - The **consumption sensor entity** (`sensor.karlstadsenergi_electricity_consumption_*`) shows the portal's year-to-date total. This entity intentionally has no `state_class` because the portal provides delayed historical data, not real-time metering.
   - The **external statistic** (`karlstadsenergi:electricity_consumption_*`) contains hourly consumption data imported into HA long-term statistics. This is the one to use in the Energy Dashboard.

   When configuring the Energy Dashboard, make sure you select the external statistic (shown under "External statistics" in the Energy Dashboard setup), not the entity sensor.

---

### Waste pickup dates not updating

**Normal behavior:** Waste data updates at the configured interval (default: every 6 hours). Pickup schedules rarely change, so infrequent updates are expected.

**If dates seem stuck:**

1. Trigger a manual refresh: call the `homeassistant.update_entity` service on a waste sensor.
2. Check the HA logs for errors from the waste coordinator.
3. Verify that waste pickup dates are visible on the Karlstads Energi portal.

---

### Spot price sensor shows stale data

The spot price sensor (e.g. `sensor.karlstadsenergi_spot_price`) updates every 15 minutes from a public Evado API endpoint. This sensor does not require authentication.

**If the spot price stops updating:**

1. The Evado API may be temporarily unavailable. This is independent of the Karlstads Energi portal.
2. Check the `stale` attribute on the sensor. If it shows `true`, the last API call did not return fresh data.
3. Tomorrow's prices are typically published around 13:00 CET. The `tomorrow_available` attribute indicates whether tomorrow's prices have been fetched yet.

---

## Collecting diagnostic information

When reporting an issue, include the following. This lets us diagnose the problem without multiple rounds of follow-up questions.

### 1. Integration version (required)

Go to Settings > Devices & Services > click **Karlstadsenergi** > three-dot menu (top right) > **About**. The version number is shown there.

### 2. Home Assistant version (required)

Found in Settings > About, or click the version number at the bottom of the sidebar.

### 3. Authentication method (required)

Which login method are you using?
- Customer number and password (recommended)
- Mobile BankID

### 4. Feature area (required)

Which part of the integration is affected?
- Waste collection (pickup dates, calendar, pickup-tomorrow alerts)
- Electricity consumption
- Electricity price
- Cost breakdown
- Spot price
- Contracts
- Other / general

### 5. Home Assistant logs (required for error issues)

Go to Settings > System > Logs. Search for `karlstadsenergi` and copy all relevant log entries as text.

### 6. Entity states (helpful)

Go to Developer Tools > States (Settings > Developer Tools > States in HA 2026.2+). Search for `karlstadsenergi` and note the state and attributes of affected entities. Copy as text, not screenshots.

### 7. Affected entity IDs (helpful)

List the specific entity IDs that are affected. Find your actual entity IDs in Developer Tools > States. Examples:
```
sensor.karlstadsenergi_mat_och_restavfall
sensor.karlstadsenergi_electricity_consumption_12345
sensor.karlstadsenergi_electricity_price_12345
```

---

## Is it an integration issue or something else?

| Check | If yes | Likely cause |
|-------|--------|--------------|
| Cannot log in to the portal at [minasidor.karlstadsenergi.se](https://minasidor.karlstadsenergi.se) | Portal itself is down | **External** (Karlstads Energi) |
| Portal works, but all sensors are unavailable | Session or authentication problem | **Integration** (check logs) |
| Only electricity sensors are affected, waste sensors work | Consumption/fee data issue | **Integration** or **data lag** |
| Only waste sensors are affected, electricity works | Flex API issue | **Integration** (check logs) |
| Issue started after a Home Assistant update | HA compatibility | **Integration** (update via HACS) |
| Data values look wrong compared to the portal | Parsing or calculation bug | **Integration** (report with portal comparison) |
| Spot price not updating, everything else works | Evado API issue | **External** (independent API) |

If the issue is external (portal or Evado API down), there is nothing the integration can do. Wait for the service to recover, and the integration will resume automatically.
