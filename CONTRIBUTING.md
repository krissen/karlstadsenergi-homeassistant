# Contributing to Karlstadsenergi for Home Assistant

First of all, **thank you for considering contributing to this project!**
Everyone is welcome to participate, regardless of experience level or background.

We appreciate all kinds of contributions: code, documentation, bug reports, feature requests, and ideas for improvements.

---

## How to contribute

- **Fork** the repository and create your own feature branch from the latest `main`.
- **Open your pull request against `main`.** That is the primary branch for this repository.
- **Describe your changes clearly** in your pull request. Include motivation and context where helpful.
- **Follow the existing code style** and try to keep your changes focused (one thing per PR).
- If you're unsure about a change or want feedback before implementing, feel free to [open an issue](../../issues/new) for discussion.

---

## Development setup

### Prerequisites

- Python 3.13+ (`requirements_test.txt` pins `homeassistant==2026.7.1`,
  which requires Python >=3.14.2 for the test venv specifically)
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
   pip install -r requirements_test.txt -r requirements_dev.txt
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

For detailed architecture notes, coordinator design, and API internals, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Reverse-engineering notes and any large/binary artifacts used to derive the
API (e.g. a decompiled reference copy of the vendor app) belong in the
gitignored `research/` directory, never in the tracked tree -- see
`research/debug/README.md`.

---

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Format then lint (always format first)
ruff format .
ruff check . --fix
```

### General conventions

- Python 3.13+ with `from __future__ import annotations`
- Type hints on all public functions
- Use `aiohttp` for async HTTP (bundled with Home Assistant)
- No third-party libraries without prior discussion
- Follow [Home Assistant integration development guidelines](https://developers.home-assistant.io/docs/creating_integration_manifest)

---

## Before opening a PR

```bash
.venv/bin/pip install -r requirements_dev.txt -r requirements_test.txt
make check
```

`make check` runs the same lint/format/secret checks as the commit hook and
CI (see GUIDELINES.md's "Quality Gates" section) plus the test suite, and
prints one line on success. See GUIDELINES.md for one-time hook setup
(`make setup`) and the `SKIP_PREK` / `SKIP=<hook-id>` escape hatches.

Commit messages follow Conventional Commits with a mandatory scope --
see GUIDELINES.md's "Commit Messages" section.

Pull requests need at least one label (`bug`, `enhancement`, `documentation`,
etc.) for the repository's own workflows to treat them as triaged.

---

## Running tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
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
