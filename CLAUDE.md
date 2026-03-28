# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: karlstadsenergi-ha

Home Assistant custom integration for Karlstadsenergi. Reverse-engineered from the Karlstadsenergi customer portal (minasidor.karlstadsenergi.se) to expose waste collection schedules and other utility data as HA entities.

**Product owner:** Kristian Niemi (https://github.com/krissen)
**Supervisor:** Claude (this agent)
**Language:** English in documentation and code

---

## Development Commands

```bash
# Lint and format
ruff format . && ruff check . --fix

# Validate Python syntax
python3 -m py_compile custom_components/karlstadsenergi/<file>.py

# Validate JSON files
python3 -c "import json; json.load(open('custom_components/karlstadsenergi/manifest.json'))"

# Run tests
pytest tests/
```

Note: No build process - this is a pure Python Home Assistant integration.

---

## Architecture

### Core Files (`custom_components/karlstadsenergi/`)

Structure mirrors the polleninformation integration (see `../polleninformation/`):

- **`__init__.py`**: Integration setup and DataUpdateCoordinator
- **`api.py`**: Async HTTP client for the Karlstadsenergi Flex API
- **`sensor.py`**: Sensor entities (waste collection dates, etc.)
- **`config_flow.py`**: UI configuration flow
- **`const.py`**: Constants

### Data Flow

1. User configures via UI (address/customer credentials)
2. Coordinator fetches from Karlstadsenergi Flex API
3. Sensors expose waste collection schedules and other utility data
4. Calendar entities for scheduled collections

### Reference Projects

- **`../polleninformation/`** - Our other HA integration (use as structural reference)
- **`../hass-test/`** - Local HA test instance for development

---

## Code Conventions

- **Python** with modern conventions (3.12+)
- Follow Home Assistant integration development guidelines
- Document public APIs
- No third-party libraries without approval (use HA's bundled deps where possible)
- Code style: KISS/DRY principles; all comments in English

---

## Subagents

This project uses Claude Code's built-in subagent system. Agents are defined in
`.claude/agents/` with YAML frontmatter and are auto-discovered.

### Available Roles

| Role | File | Responsibility |
|------|------|----------------|
| HR | `.claude/agents/hr.md` | Role profiles, team composition |
| Backend Developer | `.claude/agents/backend-developer.md` | API reverse-engineering, Python, HA integration |
| UI Developer | `.claude/agents/ui-developer.md` | Config flow, options flow, HA frontend |
| QA Tester | `.claude/agents/qa-tester.md` | Integration testing, entity validation |
| Security Specialist | `.claude/agents/security-specialist.md` | Auth handling, credential security |
| Technical Writer | `.claude/agents/technical-writer.md` | README, HACS docs, installation guide |
| HA Expert | `.claude/agents/ha-expert.md` | HA architecture, best practices, entity/flow design |

### Permissions

**Without approval:**
- Delegate to subagents
- Make technical decisions within scope
- Read documentation and research

**Requires product owner approval:**
- Scope changes
- Architectural decisions affecting UX
- Release

---

## Acceptance Criteria

| Requirement | Goal | Metric |
|-------------|------|--------|
| Waste collection | Expose scheduled pickup dates | Calendar + sensor entities |
| Authentication | Secure credential handling | HA config entry encryption |
| Reliability | Graceful API failure handling | Coordinator retry logic |
| HACS | Installable via HACS | Valid hacs.json + manifest |
