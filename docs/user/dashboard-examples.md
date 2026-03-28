# Dashboard examples

Examples for displaying waste collection data on your Home Assistant dashboard. All examples use the entity IDs created by the Karlstadsenergi integration.

> **Tip:** The examples below use Swedish labels to match the waste type names from Karlstads Energi. Change them to whatever language you prefer.

---

## Prerequisites

Some examples require custom frontend cards from HACS:

| Card | HACS name | Required by |
|------|-----------|-------------|
| [Mushroom](https://github.com/piitaya/lovelace-mushroom) | `lovelace-mushroom` | Approach 1 |
| [card-mod](https://github.com/thomasloven/lovelace-card-mod) | `lovelace-card-mod` | Approach 1b (background tinting) |
| [Custom Button Card](https://github.com/custom-cards/button-card) | `lovelace-button-card` | Approach 2 |

Approach 3 uses only built-in HA cards -- no HACS frontend dependencies.

---

## 1. Mushroom Cards (recommended)

The most popular approach in the HA community. Clean design with color-coded urgency.

**Color logic:** green (7+ days), yellow (2--6 days), orange (tomorrow), red (today).

### 1a. Template card grid

Three cards in a grid, one per waste type.

```yaml
type: grid
columns: 3
square: false
cards:

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_food_and_residual_waste
    primary: Mat- och restavfall
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon ({{ states('sensor.karlstadsenergi_food_and_residual_waste') }})
      {% elif d is not none %}Om {{ d }} dagar ({{ states('sensor.karlstadsenergi_food_and_residual_waste') }})
      {% else %}Okänt datum{% endif %}
    icon: mdi:trash-can
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d is none %}disabled
      {% elif d == 0 %}red
      {% elif d == 1 %}orange
      {% elif d <= 6 %}yellow
      {% else %}green{% endif %}

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_glass_metal
    primary: Glas/Metall
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon ({{ states('sensor.karlstadsenergi_glass_metal') }})
      {% elif d is not none %}Om {{ d }} dagar ({{ states('sensor.karlstadsenergi_glass_metal') }})
      {% else %}Okänt datum{% endif %}
    icon: mdi:recycle
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d is none %}disabled
      {% elif d == 0 %}red
      {% elif d == 1 %}orange
      {% elif d <= 6 %}yellow
      {% else %}green{% endif %}

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_plastic_paper_packaging
    primary: Plast- och pappersförpackningar
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon ({{ states('sensor.karlstadsenergi_plastic_paper_packaging') }})
      {% elif d is not none %}Om {{ d }} dagar ({{ states('sensor.karlstadsenergi_plastic_paper_packaging') }})
      {% else %}Okänt datum{% endif %}
    icon: mdi:package-variant
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d is none %}disabled
      {% elif d == 0 %}red
      {% elif d == 1 %}orange
      {% elif d <= 6 %}yellow
      {% else %}green{% endif %}
```

### 1b. With card-mod background tinting

Same layout but tints the entire card background. Requires card-mod in addition to Mushroom.

```yaml
type: grid
columns: 3
square: false
cards:

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_food_and_residual_waste
    primary: Mat- och restavfall
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon · {{ states('sensor.karlstadsenergi_food_and_residual_waste') }}
      {% elif d is not none %}Om {{ d }} dagar · {{ states('sensor.karlstadsenergi_food_and_residual_waste') }}
      {% else %}Okänt datum{% endif %}
    icon: mdi:trash-can
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}
    card_mod:
      style: >
        {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
        ha-card {
          {% if d is none %}background: rgba(128,128,128,0.08);
          {% elif d == 0 %}background: rgba(var(--rgb-red), 0.12);
          {% elif d == 1 %}background: rgba(var(--rgb-orange), 0.10);
          {% elif d <= 6 %}background: rgba(var(--rgb-yellow), 0.08);
          {% else %}background: rgba(var(--rgb-green), 0.06);
          {% endif %}
        }

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_glass_metal
    primary: Glas/Metall
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon · {{ states('sensor.karlstadsenergi_glass_metal') }}
      {% elif d is not none %}Om {{ d }} dagar · {{ states('sensor.karlstadsenergi_glass_metal') }}
      {% else %}Okänt datum{% endif %}
    icon: mdi:recycle
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}
    card_mod:
      style: >
        {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
        ha-card {
          {% if d is none %}background: rgba(128,128,128,0.08);
          {% elif d == 0 %}background: rgba(var(--rgb-red), 0.12);
          {% elif d == 1 %}background: rgba(var(--rgb-orange), 0.10);
          {% elif d <= 6 %}background: rgba(var(--rgb-yellow), 0.08);
          {% else %}background: rgba(var(--rgb-green), 0.06);
          {% endif %}
        }

  - type: custom:mushroom-template-card
    entity: sensor.karlstadsenergi_plastic_paper_packaging
    primary: Plast- och pappersförpackningar
    secondary: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d == 0 %}Hämtas IDAG
      {% elif d == 1 %}Imorgon · {{ states('sensor.karlstadsenergi_plastic_paper_packaging') }}
      {% elif d is not none %}Om {{ d }} dagar · {{ states('sensor.karlstadsenergi_plastic_paper_packaging') }}
      {% else %}Okänt datum{% endif %}
    icon: mdi:package-variant
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}
    card_mod:
      style: >
        {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
        ha-card {
          {% if d is none %}background: rgba(128,128,128,0.08);
          {% elif d == 0 %}background: rgba(var(--rgb-red), 0.12);
          {% elif d == 1 %}background: rgba(var(--rgb-orange), 0.10);
          {% elif d <= 6 %}background: rgba(var(--rgb-yellow), 0.08);
          {% else %}background: rgba(var(--rgb-green), 0.06);
          {% endif %}
        }
```

> **Note:** `--rgb-red`, `--rgb-orange` etc. are CSS variables defined by HA's default theme and most popular themes. If your theme doesn't define them, replace with hex values (e.g., `rgba(220,38,38,0.12)`).

### 1c. Chips (compact status bar)

A single row for the top of a view. Each chip shows the icon and days remaining.

```yaml
type: custom:mushroom-chips-card
chips:

  - type: template
    entity: sensor.karlstadsenergi_food_and_residual_waste
    icon: mdi:trash-can
    content: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d == 0 %}Idag!{% elif d == 1 %}Imorgon{% elif d is not none %}{{ d }}d{% else %}-{% endif %}
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_food_and_residual_waste', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}

  - type: template
    entity: sensor.karlstadsenergi_glass_metal
    icon: mdi:recycle
    content: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d == 0 %}Idag!{% elif d == 1 %}Imorgon{% elif d is not none %}{{ d }}d{% else %}-{% endif %}
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_glass_metal', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}

  - type: template
    entity: sensor.karlstadsenergi_plastic_paper_packaging
    icon: mdi:package-variant
    content: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d == 0 %}Idag!{% elif d == 1 %}Imorgon{% elif d is not none %}{{ d }}d{% else %}-{% endif %}
    icon_color: >-
      {% set d = state_attr('sensor.karlstadsenergi_plastic_paper_packaging', 'days_until_pickup') %}
      {% if d is none %}disabled{% elif d == 0 %}red{% elif d == 1 %}orange{% elif d <= 6 %}yellow{% else %}green{% endif %}
```

---

## 2. Custom Button Card

Three-state card with distinct styling per urgency level. Uses button-card's JavaScript templates.

```yaml
type: grid
columns: 3
square: false
cards:

  - type: custom:button-card
    entity: sensor.karlstadsenergi_food_and_residual_waste
    name: Mat- och restavfall
    icon: mdi:trash-can
    show_icon: true
    show_name: true
    show_label: true
    show_state: false
    size: 40%
    label: >
      [[[
        const d = entity.attributes.days_until_pickup;
        if (d === undefined || d === null) return 'Okänt datum';
        if (d === 0) return 'Hämtas IDAG';
        if (d === 1) return 'Imorgon · ' + entity.state;
        return 'Om ' + d + ' dagar · ' + entity.state;
      ]]]
    styles:
      card:
        - border-radius: 12px
        - padding: 16px 12px
        - background: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'rgba(128,128,128,0.1)';
              if (d === 0) return 'rgba(220,38,38,0.18)';
              if (d === 1) return 'rgba(234,88,12,0.16)';
              if (d <= 6) return 'rgba(202,138,4,0.12)';
              return 'rgba(22,163,74,0.10)';
            ]]]
      icon:
        - color: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'var(--disabled-color)';
              if (d === 0) return 'var(--error-color)';
              if (d === 1) return '#ea580c';
              if (d <= 6) return '#ca8a04';
              return 'var(--success-color)';
            ]]]
      name:
        - font-size: 13px
        - font-weight: 500
        - margin-top: 8px
      label:
        - font-size: 12px
        - opacity: '0.75'

  - type: custom:button-card
    entity: sensor.karlstadsenergi_glass_metal
    name: Glas/Metall
    icon: mdi:recycle
    show_icon: true
    show_name: true
    show_label: true
    show_state: false
    size: 40%
    label: >
      [[[
        const d = entity.attributes.days_until_pickup;
        if (d === undefined || d === null) return 'Okänt datum';
        if (d === 0) return 'Hämtas IDAG';
        if (d === 1) return 'Imorgon · ' + entity.state;
        return 'Om ' + d + ' dagar · ' + entity.state;
      ]]]
    styles:
      card:
        - border-radius: 12px
        - padding: 16px 12px
        - background: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'rgba(128,128,128,0.1)';
              if (d === 0) return 'rgba(220,38,38,0.18)';
              if (d === 1) return 'rgba(234,88,12,0.16)';
              if (d <= 6) return 'rgba(202,138,4,0.12)';
              return 'rgba(22,163,74,0.10)';
            ]]]
      icon:
        - color: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'var(--disabled-color)';
              if (d === 0) return 'var(--error-color)';
              if (d === 1) return '#ea580c';
              if (d <= 6) return '#ca8a04';
              return 'var(--success-color)';
            ]]]
      name:
        - font-size: 13px
        - font-weight: 500
        - margin-top: 8px
      label:
        - font-size: 12px
        - opacity: '0.75'

  - type: custom:button-card
    entity: sensor.karlstadsenergi_plastic_paper_packaging
    name: Plast/Papper
    icon: mdi:package-variant
    show_icon: true
    show_name: true
    show_label: true
    show_state: false
    size: 40%
    label: >
      [[[
        const d = entity.attributes.days_until_pickup;
        if (d === undefined || d === null) return 'Okänt datum';
        if (d === 0) return 'Hämtas IDAG';
        if (d === 1) return 'Imorgon · ' + entity.state;
        return 'Om ' + d + ' dagar · ' + entity.state;
      ]]]
    styles:
      card:
        - border-radius: 12px
        - padding: 16px 12px
        - background: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'rgba(128,128,128,0.1)';
              if (d === 0) return 'rgba(220,38,38,0.18)';
              if (d === 1) return 'rgba(234,88,12,0.16)';
              if (d <= 6) return 'rgba(202,138,4,0.12)';
              return 'rgba(22,163,74,0.10)';
            ]]]
      icon:
        - color: >
            [[[
              const d = entity.attributes.days_until_pickup;
              if (d === undefined || d === null) return 'var(--disabled-color)';
              if (d === 0) return 'var(--error-color)';
              if (d === 1) return '#ea580c';
              if (d <= 6) return '#ca8a04';
              return 'var(--success-color)';
            ]]]
      name:
        - font-size: 13px
        - font-weight: 500
        - margin-top: 8px
      label:
        - font-size: 12px
        - opacity: '0.75'
```

> **Tip:** To reduce repetition, button-card supports shared templates via `button_card_templates`. See the [button-card documentation](https://github.com/custom-cards/button-card#configuration-templates) for details.

---

## 3. Built-in HA cards (no HACS required)

### 3a. Calendar card

Shows all waste calendars in HA's native calendar view.

```yaml
type: calendar
entities:
  - calendar.karlstadsenergi_food_and_residual_waste_calendar
  - calendar.karlstadsenergi_glass_metal_calendar
  - calendar.karlstadsenergi_plastic_paper_packaging_calendar
initial_view: listWeek
```

### 3b. Entities card with conditional rows

Pickup dates always visible; alert rows appear only when a pickup is tomorrow.

```yaml
type: entities
title: Sophämtning
entities:
  - entity: sensor.karlstadsenergi_food_and_residual_waste
    name: Mat- och restavfall
    icon: mdi:trash-can
  - entity: sensor.karlstadsenergi_glass_metal
    name: Glas/Metall
    icon: mdi:recycle
  - entity: sensor.karlstadsenergi_plastic_paper_packaging
    name: Plast/Papper
    icon: mdi:package-variant
  - type: divider
  - type: conditional
    conditions:
      - condition: state
        entity: binary_sensor.karlstadsenergi_food_and_residual_waste_pickup_tomorrow
        state: "on"
    row:
      entity: binary_sensor.karlstadsenergi_food_and_residual_waste_pickup_tomorrow
      name: Mat- och restavfall hämtas imorgon
      icon: mdi:alert
  - type: conditional
    conditions:
      - condition: state
        entity: binary_sensor.karlstadsenergi_glass_metal_pickup_tomorrow
        state: "on"
    row:
      entity: binary_sensor.karlstadsenergi_glass_metal_pickup_tomorrow
      name: Glas/Metall hämtas imorgon
      icon: mdi:alert
  - type: conditional
    conditions:
      - condition: state
        entity: binary_sensor.karlstadsenergi_plastic_paper_packaging_pickup_tomorrow
        state: "on"
    row:
      entity: binary_sensor.karlstadsenergi_plastic_paper_packaging_pickup_tomorrow
      name: Plast/Papper hämtas imorgon
      icon: mdi:alert
```

### 3c. Glance card (most compact)

```yaml
type: glance
title: Sophämtning
columns: 3
show_state: true
entities:
  - entity: sensor.karlstadsenergi_food_and_residual_waste
    name: Mat/Rest
    icon: mdi:trash-can
  - entity: sensor.karlstadsenergi_glass_metal
    name: Glas/Metall
    icon: mdi:recycle
  - entity: sensor.karlstadsenergi_plastic_paper_packaging
    name: Plast/Papper
    icon: mdi:package-variant
```

---

## Other options

### TrashCard

[TrashCard](https://github.com/idaho/hassio-trash-card) is a dedicated waste collection card that works with HA calendar entities. It can consume the calendar entities from this integration directly. However, as of early 2026, the project has not seen a release or maintainer activity in over a year. It may still work, but consider the approaches above as more actively maintained alternatives.

---

## Design notes

**Color thresholds.** All examples above use this scheme:

| Days until pickup | Color | Meaning |
|-------------------|-------|---------|
| 7+ | Green | Normal |
| 2--6 | Yellow | Coming up |
| 1 | Orange | Tomorrow |
| 0 | Red | Today |

Adjust `d <= 6` to `d <= 13` if your waste is collected every two weeks and you want the yellow warning earlier.

**Edge cases.** The `days_until_pickup` attribute is absent when the coordinator has no data yet. All templates above handle this gracefully (neutral grey / "Okänt datum").

**Binary sensors vs. `days_until_pickup`.** The binary sensors (`pickup_tomorrow`) are best for automations (notifications). For dashboard display, `days_until_pickup` is more flexible since it drives a color gradient rather than just on/off.
