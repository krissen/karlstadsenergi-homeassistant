# Release Smoke Report (Template)

Use this report before tagging a release. Keep it short, factual, and reproducible.

## Metadata

- Release candidate: `vX.Y.Z`
- Date:
- Tester:
- Home Assistant version (test venv):
- Home Assistant version (live instance):
- Installation type (Container / Core / OS / Supervised):
- Integration commit/tag tested:

## Environment

- Karlstadsenergi account type: `Password` / `BankID` / `Both`
- Number of configured Karlstadsenergi entries:
- Notes about test environment:

## Automated Tests

### Unit tests (pytest)

- Test count:
- Result: `PASS` / `FAIL`
- Command: `source .venv/bin/activate && pytest tests/ --ignore=tests/test_live.py -q`
- Failures (if any):

### Lint and formatting (ruff)

- Result: `PASS` / `FAIL`
- Command: `ruff check . && ruff format --check .`

### Live smoke tests (pytest against running HA)

- Test count:
- Result: `PASS` / `FAIL`
- Command: `pytest tests/test_live.py -v`
- Failures (if any):

## Manual Smoke Checklist

### 1) Password setup

- [ ] Add integration with customer number + password
- [ ] Setup completes without errors
- [ ] Expected entities are created (sensor/calendar/binary_sensor)
- Evidence:

### 2) Entity updates

- [ ] Waste entities update at configured interval
- [ ] Consumption/price entities update as expected
- [ ] Spot price updates (or gracefully unavailable if upstream issue)
- Evidence:

### 3) HA restart recovery

- [ ] Restart Home Assistant
- [ ] Integration reloads successfully
- [ ] Entities recover (not all unavailable/unknown)
- Evidence:

### 4) Re-auth flow

- [ ] Simulate expired session (for example clear saved cookies)
- [ ] Re-auth flow is triggered
- [ ] Re-auth completes and data resumes
- Evidence:

### 5) BankID setup (if included in release scope)

- [ ] BankID personnummer step works
- [ ] BankID app sign-in via deep link works
- [ ] Account selection works (if multiple accounts)
- [ ] Entities appear after setup
- Evidence:

### 6) Options flow

- [ ] Change update interval
- [ ] Entry reloads
- [ ] New interval takes effect
- Evidence:

### 7) Diagnostics redaction

- [ ] Download diagnostics
- [ ] Sensitive fields are redacted (personnummer, ContractId, cookies, etc.)
- Evidence:

### 8) Energy Dashboard (if price/consumption sensors in scope)

- [ ] Price sensors visible in Energy Dashboard configuration
- [ ] Consumption sensor selectable as grid consumption
- Evidence:

## Result Summary

- Overall verdict: `GO` / `NOGO`
- Blocking issues (if any):
  -
- Non-blocking notes:
  -

## Sign-off

- Reviewer name:
- Decision date:
- Approved for tag: `Yes` / `No`
