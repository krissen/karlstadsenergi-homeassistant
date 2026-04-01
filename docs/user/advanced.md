# Advanced usage

Service calls, template sensors, and automation examples for the Karlstadsenergi integration.

---

## Trigger a manual data refresh

All coordinators update on a schedule, but you can force an immediate refresh with the `homeassistant.update_entity` service.

### From Developer Tools

1. Go to **Developer Tools -> Services**.
2. Choose `homeassistant.update_entity`.
3. Pick any entity from the coordinator you want to refresh (e.g. a waste sensor refreshes the waste coordinator).

### Script example

```yaml
script:
  refresh_waste_data:
    alias: "Refresh waste data now"
    sequence:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.karlstadsenergi_testgatan_1_mat_och_restavfall
```

> **Note:** Replace the entity ID with your actual entity ID from **Settings -> Devices & Services -> Karlstadsenergi**.

### Refresh all Karlstadsenergi data at once

```yaml
script:
  refresh_all_karlstadsenergi:
    alias: "Refresh all Karlstadsenergi data"
    sequence:
      - action: homeassistant.update_entity
        target:
          entity_id:
            # One entity per coordinator is enough -- the whole coordinator refreshes
            - sensor.karlstadsenergi_testgatan_1_mat_och_restavfall  # waste
            - sensor.karlstadsenergi_electricity_consumption          # consumption + price
            - sensor.karlstadsenergi_spot_price                       # spot price
```

---

## Automation: refresh data at a specific time

If you want data to be fresh for a morning dashboard check:

```yaml
automation:
  - alias: "Refresh Karlstadsenergi before morning"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.karlstadsenergi_testgatan_1_mat_och_restavfall
```

---

## Template sensors

### Human-readable pickup countdown

```yaml
template:
  - sensor:
      - name: "Waste pickup countdown"
        state: >
          {% set days = state_attr('sensor.karlstadsenergi_testgatan_1_mat_och_restavfall', 'days_until_pickup') %}
          {% if days == 0 %}
            Today
          {% elif days == 1 %}
            Tomorrow
          {% elif days is not none %}
            In {{ days }} days
          {% else %}
            Unknown
          {% endif %}
        icon: mdi:trash-can
```

### Monthly electricity cost estimate

```yaml
template:
  - sensor:
      - name: "Estimated monthly electricity cost"
        unit_of_measurement: "SEK"
        state: >
          {% set daily = state_attr('sensor.karlstadsenergi_electricity_consumption', 'average_daily') %}
          {% set price = states('sensor.karlstadsenergi_spot_price') | float(0) %}
          {% if daily and price > 0 %}
            {{ (daily * price * 30) | round(0) }}
          {% else %}
            unknown
          {% endif %}
        icon: mdi:cash
```

### Monthly cost trend

```yaml
template:
  - sensor:
      - name: "Power fee trend"
        unit_of_measurement: "SEK"
        state: >
          {% set breakdown = state_attr('sensor.karlstadsenergi_power_fee', 'monthly_breakdown') %}
          {% if breakdown %}
            {% set values = breakdown.values() | list %}
            {{ values[-1] | round(0) }}
          {% else %}
            unknown
          {% endif %}
        icon: mdi:transmission-tower
```

### Spot price status (cheap/normal/expensive)

```yaml
template:
  - sensor:
      - name: "Electricity price level"
        state: >
          {% set price = states('sensor.karlstadsenergi_spot_price') | float(0) %}
          {% set avg = state_attr('sensor.karlstadsenergi_spot_price', 'today_average') | float(0) %}
          {% if price <= 0 or avg <= 0 %}
            unknown
          {% elif price < avg * 0.7 %}
            Cheap
          {% elif price > avg * 1.3 %}
            Expensive
          {% else %}
            Normal
          {% endif %}
        icon: >
          {% set price = states('sensor.karlstadsenergi_spot_price') | float(0) %}
          {% set avg = state_attr('sensor.karlstadsenergi_spot_price', 'today_average') | float(0) %}
          {% if price > 0 and avg > 0 and price < avg * 0.7 %}
            mdi:arrow-down-bold
          {% elif price > 0 and avg > 0 and price > avg * 1.3 %}
            mdi:arrow-up-bold
          {% else %}
            mdi:minus
          {% endif %}
```

---

## Conditional notifications based on spot price

Notify when the spot price drops below a threshold (good time to run dishwasher/laundry):

```yaml
automation:
  - alias: "Cheap electricity alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.karlstadsenergi_spot_price
        below: 0.30
    condition:
      - condition: time
        after: "06:00:00"
        before: "23:00:00"
    action:
      - action: notify.mobile_app
        data:
          title: "Low electricity price"
          message: >
            Spot price is {{ states('sensor.karlstadsenergi_spot_price') }} SEK/kWh.
            Good time to run heavy appliances.
```

---

## Combine with other integrations

### Use spot price to control a smart plug

```yaml
automation:
  - alias: "Smart plug follows spot price"
    trigger:
      - platform: state
        entity_id: sensor.karlstadsenergi_spot_price
    action:
      - choose:
          - conditions:
              - condition: numeric_state
                entity_id: sensor.karlstadsenergi_spot_price
                below: 0.40
            sequence:
              - action: switch.turn_on
                target:
                  entity_id: switch.water_heater
          - conditions:
              - condition: numeric_state
                entity_id: sensor.karlstadsenergi_spot_price
                above: 0.80
            sequence:
              - action: switch.turn_off
                target:
                  entity_id: switch.water_heater
```

---

## Update intervals reference

| Data | Default interval | Configurable | Notes |
|------|-----------------|--------------|-------|
| Waste collection | 6 hours | Yes (1--24h via Options) | Pickup dates rarely change |
| Electricity consumption | 1 hour | Indirectly (waste interval / 6, min 1h) | Historical data, may lag |
| Fee breakdown | 1 hour | Same as consumption | Updated with consumption |
| Contracts | 24 hours | No | Changes very rarely |
| Spot price | 15 minutes | No | Public API, no auth |

## Statistics history setting

Controls how far back hourly consumption and monthly cost data is imported into HA's long-term statistics.

| Setting | Default | Range | Notes |
|---------|---------|-------|-------|
| Statistics history | 2 years | 1--10 years | Configured via Options flow |

The portal API typically has data going back to the start of the customer contract (up to ~7 years observed). The first import after changing this setting fetches all historical data within the new window. Subsequent refreshes only add new data points.

| History depth | Approx. hourly data points | Approx. monthly cost points |
|---------------|---------------------------|----------------------------|
| 1 year | ~9,000 | ~12 per fee type |
| 2 years (default) | ~19,000 | ~25 per fee type |
| 5 years | ~44,000 | ~60 per fee type |
| 10 years | ~88,000 | ~120 per fee type |

> **Note:** If you increase the history depth after the initial import, you need to clear the existing statistics via **Developer Tools -> Statistics** to trigger a full reimport. Otherwise the integration only adds data points newer than what's already been imported.

---

## Visualizing cost data with Plotly Graph Card

The built-in `statistics-graph` card is limited to **12 months** of data (`days_to_show: 365`). If you have imported several years of cost statistics and want to see the full picture, [Plotly Graph Card](https://github.com/dbuezas/lovelace-plotly-graph-card) is a good alternative. It reads the same `monthly_breakdown` attributes from the cost sensors and can display any time range.

<p align="center">
  <img width="500" alt="Monthly electricity cost breakdown (Plotly)" src="../images/cost-monthly-plotly.png" />
</p>

Install Plotly Graph Card via HACS (`lovelace-plotly-graph-card`), then add the following card:

```yaml
type: custom:plotly-graph
title: Elkostnader per månad (Karlstadsenergi)
raw_plotly_config: true
fn: |
  $ex {
    const ids = [
      'sensor.karlstadsenergi_testgatan_1_energiavgift',
      'sensor.karlstadsenergi_testgatan_1_effektavgift',
      'sensor.karlstadsenergi_testgatan_1_fast_avgift',
      'sensor.karlstadsenergi_testgatan_1_energiskatt',
      'sensor.karlstadsenergi_testgatan_1_moms'
    ];
    const bd0 = hass.states[ids[0]]?.attributes?.monthly_breakdown || {};
    vars.months = Object.keys(bd0).sort().slice(-12);
    vars.d = ids.map(id => {
      const bd = hass.states[id]?.attributes?.monthly_breakdown || {};
      return vars.months.map(m => bd[m] || 0);
    });
  }
entities:
  - entity: sensor.karlstadsenergi_testgatan_1_energiavgift
    name: Energiavgift
    type: bar
    x: $ex vars.months
    y: $ex vars.d[0]
    marker:
      color: "#2196F3"
  - entity: sensor.karlstadsenergi_testgatan_1_effektavgift
    name: Effektavgift
    type: bar
    x: $ex vars.months
    y: $ex vars.d[1]
    marker:
      color: "#FF9800"
  - entity: sensor.karlstadsenergi_testgatan_1_fast_avgift
    name: Fast avgift
    type: bar
    x: $ex vars.months
    y: $ex vars.d[2]
    marker:
      color: "#4CAF50"
  - entity: sensor.karlstadsenergi_testgatan_1_energiskatt
    name: Energiskatt
    type: bar
    x: $ex vars.months
    y: $ex vars.d[3]
    marker:
      color: "#F44336"
  - entity: sensor.karlstadsenergi_testgatan_1_moms
    name: Moms
    type: bar
    x: $ex vars.months
    y: $ex vars.d[4]
    marker:
      color: "#9C27B0"
layout:
  height: 450
  barmode: stack
  bargap: 0.15
  xaxis:
    title: ""
    fixedrange: true
  yaxis:
    title: SEK
    fixedrange: true
  paper_bgcolor: rgba(0,0,0,0)
  plot_bgcolor: rgba(0,0,0,0)
  legend:
    orientation: h
    y: -0.15
  margin:
    t: 30
    b: 80
```

> **Note:** Replace the entity IDs with your actual cost sensor IDs. The `fn` block reads the `monthly_breakdown` attribute from each cost sensor and builds the stacked bar chart. Adjust `.slice(-12)` to `.slice(-24)` (or remove it entirely) to show more months -- this is where Plotly shines over `statistics-graph`, which caps out at 12 months.

> **Tip:** To change the time window, edit the `.slice(-12)` in the `fn` block. For example, `.slice(-24)` shows two years, and removing `.slice(...)` entirely shows all available data.
