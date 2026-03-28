# Contributing to Karlstadsenergi for Home Assistant

First of all, **thank you for considering contributing to this project!**
Everyone is welcome to participate, regardless of experience level or background.

We appreciate all kinds of contributions: code, documentation, bug reports, feature requests, and ideas for improvements.

---

## How to contribute

- **Fork** the repository and create your own feature branch from the latest `main`.
- **Do _not_ create pull requests directly against `main`.**
  - Instead, open your PR against a development or feature branch.
  - Pull requests targeting `main` will be closed.
- **Describe your changes clearly** in your pull request. Include motivation and context where helpful.
- **Follow the existing code style** and try to keep your changes focused (one thing per PR).
- If you're unsure about a change or want feedback before implementing, feel free to [open an issue](../../issues/new) for discussion.

---

## Development setup

### Prerequisites

- Python 3.12+
- A working [Home Assistant development environment](https://developers.home-assistant.io/docs/development_environment) or a test instance

### Local development

1. Clone the repository:

   ```bash
   git clone https://github.com/krissen/karlstadsenergi-homeassistant.git
   cd karlstadsenergi-homeassistant
   ```

2. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install homeassistant aiohttp voluptuous ruff
   ```

### Test instance

The project uses a dedicated Home Assistant test instance at `../hass-test/config/`. To set up:

1. Symlink the integration into the test instance:

   ```bash
   ln -s "$(pwd)/custom_components/karlstadsenergi" \
     ../hass-test/config/custom_components/karlstadsenergi
   ```

2. Start the test instance:

   ```bash
   cd ../hass-test
   hass -c config/
   ```

3. Add the integration through the HA UI and verify your changes.

---

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check
ruff check custom_components/karlstadsenergi/

# Auto-fix
ruff check --fix custom_components/karlstadsenergi/

# Format
ruff format custom_components/karlstadsenergi/
```

### General conventions

- Python 3.12+ with `from __future__ import annotations`
- Type hints on all public functions
- Use `aiohttp` for async HTTP (bundled with Home Assistant)
- No third-party libraries without prior discussion
- Follow [Home Assistant integration development guidelines](https://developers.home-assistant.io/docs/creating_integration_manifest)

---

## Running tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt  # if available
pytest tests/
```

---

## Reporting issues

- If you find a bug or have an idea for an enhancement, please [open an issue](../../issues/new).
- Include steps to reproduce, screenshots, logs, or any context that may help.
- Home Assistant logs can be found in **Settings -> System -> Logs**, or by checking `home-assistant.log`.

---

## Code of conduct

We are committed to providing a welcoming, friendly, and harassment-free environment for all. Please treat everyone with respect and be constructive in discussions.

---

## Thank you

Your feedback and contributions help make this project better for everyone.
