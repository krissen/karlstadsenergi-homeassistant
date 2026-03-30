# Advanced usage

Tips and patterns for getting more out of the Karlstadsenergi integration.

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
