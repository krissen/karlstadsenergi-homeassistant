"""Live smoke tests against a real Home Assistant instance.

These tests require a running HA instance with the karlstadsenergi
integration configured. Connection details are read from .env:

    HA_URL=http://localhost:8123
    HA_TOKEN=<long-lived access token>

Run with:
    pytest tests/test_live.py -v

Skipped automatically when .env is missing or HA is unreachable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import aiohttp
import pytest

# ---------------------------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> dict[str, str]:
    """Parse .env file into a dict."""
    if not _ENV_PATH.exists():
        return {}
    env: dict[str, str] = {}
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


_env = _load_env()
HA_URL = _env.get("HA_URL", os.environ.get("HA_URL", ""))
HA_TOKEN = _env.get("HA_TOKEN", os.environ.get("HA_TOKEN", ""))

# Skip all tests in this module if no HA connection is configured
pytestmark = pytest.mark.skipif(
    not HA_URL or not HA_TOKEN,
    reason="Live HA tests require HA_URL and HA_TOKEN in .env",
)

DOMAIN = "karlstadsenergi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def ha_session():
    """Create an aiohttp session with HA auth headers."""
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    # Use ThreadedResolver to avoid aiodns compatibility issues in test venv
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(
        headers=headers, connector=connector
    ) as session:
        # Verify HA is reachable
        try:
            async with session.get(f"{HA_URL}/api/") as resp:
                if resp.status != 200:
                    pytest.skip(f"HA not reachable (status {resp.status})")
        except aiohttp.ClientError:
            pytest.skip("HA not reachable")
        yield session


async def _get_states(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    """Fetch all entity states from HA."""
    async with session.get(f"{HA_URL}/api/states") as resp:
        assert resp.status == 200
        return await resp.json()


async def _get_entity(
    session: aiohttp.ClientSession, entity_id: str
) -> dict[str, Any] | None:
    """Fetch a single entity state."""
    async with session.get(f"{HA_URL}/api/states/{entity_id}") as resp:
        if resp.status == 404:
            return None
        assert resp.status == 200
        return await resp.json()


async def _get_config_entries(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    """Fetch all config entries."""
    async with session.get(f"{HA_URL}/api/config/config_entries/entry") as resp:
        assert resp.status == 200
        return await resp.json()


def _ke_entities(states: list[dict]) -> list[dict]:
    """Filter states to karlstadsenergi entities only."""
    return [s for s in states if DOMAIN in s["entity_id"]]


# ---------------------------------------------------------------------------
# Tests: Integration is loaded
# ---------------------------------------------------------------------------


class TestIntegrationLoaded:
    """Verify the integration is set up and functional."""

    @pytest.mark.asyncio
    async def test_config_entry_exists(self, ha_session) -> None:
        """At least one karlstadsenergi config entry must be present."""
        entries = await _get_config_entries(ha_session)
        ke_entries = [e for e in entries if e.get("domain") == DOMAIN]
        assert len(ke_entries) >= 1, "No karlstadsenergi config entry found"

    @pytest.mark.asyncio
    async def test_config_entry_state_loaded(self, ha_session) -> None:
        """Config entry must be in 'loaded' state (not setup_error/retry)."""
        entries = await _get_config_entries(ha_session)
        ke_entries = [e for e in entries if e.get("domain") == DOMAIN]
        for entry in ke_entries:
            state = entry.get("state", "")
            assert state == "loaded", (
                f"Config entry '{entry.get('title')}' is in state '{state}', "
                f"reason: {entry.get('reason', 'unknown')}"
            )

    @pytest.mark.asyncio
    async def test_entities_exist(self, ha_session) -> None:
        """At least one karlstadsenergi entity must be registered."""
        states = await _get_states(ha_session)
        ke = _ke_entities(states)
        assert len(ke) >= 1, "No karlstadsenergi entities found"


# ---------------------------------------------------------------------------
# Tests: Waste collection
# ---------------------------------------------------------------------------


class TestWasteEntities:
    """Verify waste collection sensors, calendars, and binary sensors."""

    @pytest.mark.asyncio
    async def test_waste_sensors_exist(self, ha_session) -> None:
        """At least one waste sensor should be present."""
        states = await _get_states(ha_session)
        waste_sensors = [
            s
            for s in _ke_entities(states)
            if s["entity_id"].startswith("sensor.")
            and "electricity" not in s["entity_id"]
            and "spot" not in s["entity_id"]
            and "avtal" not in s["entity_id"]
            and "contract" not in s["entity_id"]
        ]
        assert len(waste_sensors) >= 1, "No waste sensors found"

    @pytest.mark.asyncio
    async def test_waste_sensor_has_date_state(self, ha_session) -> None:
        """Waste sensors should have a valid date or unavailable state."""
        states = await _get_states(ha_session)
        waste_sensors = [
            s
            for s in _ke_entities(states)
            if s["entity_id"].startswith("sensor.")
            and "electricity" not in s["entity_id"]
            and "spot" not in s["entity_id"]
            and "avtal" not in s["entity_id"]
            and "contract" not in s["entity_id"]
        ]
        for sensor in waste_sensors:
            state = sensor["state"]
            assert state != "unknown", (
                f"{sensor['entity_id']} has state 'unknown'"
            )
            # State should be a date (YYYY-MM-DD) or unavailable
            if state != "unavailable":
                assert len(state) == 10 and state[4] == "-", (
                    f"{sensor['entity_id']} state '{state}' is not a date"
                )

    @pytest.mark.asyncio
    async def test_waste_sensor_attributes(self, ha_session) -> None:
        """Waste sensors should have expected attributes."""
        states = await _get_states(ha_session)
        waste_sensors = [
            s
            for s in _ke_entities(states)
            if s["entity_id"].startswith("sensor.")
            and "electricity" not in s["entity_id"]
            and "spot" not in s["entity_id"]
            and "avtal" not in s["entity_id"]
            and "contract" not in s["entity_id"]
            and s["state"] != "unavailable"
        ]
        for sensor in waste_sensors:
            attrs = sensor.get("attributes", {})
            assert "days_until_pickup" in attrs, (
                f"{sensor['entity_id']} missing days_until_pickup"
            )
            assert "pickup_is_today" in attrs
            assert "pickup_is_tomorrow" in attrs

    @pytest.mark.asyncio
    async def test_calendar_entities_exist(self, ha_session) -> None:
        """Calendar entities for waste collection should be present."""
        states = await _get_states(ha_session)
        calendars = [
            s
            for s in _ke_entities(states)
            if s["entity_id"].startswith("calendar.")
        ]
        assert len(calendars) >= 1, "No calendar entities found"

    @pytest.mark.asyncio
    async def test_binary_sensors_exist(self, ha_session) -> None:
        """Binary sensors for pickup tomorrow should be present."""
        states = await _get_states(ha_session)
        binary = [
            s
            for s in _ke_entities(states)
            if s["entity_id"].startswith("binary_sensor.")
        ]
        assert len(binary) >= 1, "No binary sensor entities found"


# ---------------------------------------------------------------------------
# Tests: Electricity
# ---------------------------------------------------------------------------


class TestElectricityEntities:
    """Verify electricity consumption and price sensors."""

    @pytest.mark.asyncio
    async def test_consumption_sensor_exists(self, ha_session) -> None:
        states = await _get_states(ha_session)
        consumption = [
            s
            for s in _ke_entities(states)
            if "electricity_consumption" in s["entity_id"]
            and s["entity_id"].startswith("sensor.")
        ]
        assert len(consumption) >= 1, "No electricity consumption sensor found"

    @pytest.mark.asyncio
    async def test_consumption_sensor_numeric_or_unavailable(self, ha_session) -> None:
        states = await _get_states(ha_session)
        consumption = [
            s
            for s in _ke_entities(states)
            if "electricity_consumption" in s["entity_id"]
            and s["entity_id"].startswith("sensor.")
        ]
        for sensor in consumption:
            state = sensor["state"]
            if state not in ("unavailable", "unknown"):
                float(state)  # Should not raise

    @pytest.mark.asyncio
    async def test_spot_price_sensor_exists(self, ha_session) -> None:
        states = await _get_states(ha_session)
        spot = [
            s
            for s in _ke_entities(states)
            if "spot_price" in s["entity_id"]
            and s["entity_id"].startswith("sensor.")
        ]
        assert len(spot) >= 1, "No spot price sensor found"

    @pytest.mark.asyncio
    async def test_spot_price_has_region_attribute(self, ha_session) -> None:
        states = await _get_states(ha_session)
        spot = [
            s
            for s in _ke_entities(states)
            if "spot_price" in s["entity_id"]
            and s["entity_id"].startswith("sensor.")
            and s["state"] not in ("unavailable", "unknown")
        ]
        for sensor in spot:
            attrs = sensor.get("attributes", {})
            assert attrs.get("region") == "SE3", (
                f"{sensor['entity_id']} region is {attrs.get('region')}, expected SE3"
            )


# ---------------------------------------------------------------------------
# Tests: Diagnostics (PII redaction)
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Verify diagnostics endpoint redacts PII."""

    @pytest.mark.asyncio
    async def test_diagnostics_available(self, ha_session) -> None:
        """Diagnostics endpoint should return data."""
        entries = await _get_config_entries(ha_session)
        ke_entries = [e for e in entries if e.get("domain") == DOMAIN]
        if not ke_entries:
            pytest.skip("No config entry")
        entry_id = ke_entries[0]["entry_id"]
        async with ha_session.get(
            f"{HA_URL}/api/diagnostics/config_entry/{entry_id}"
        ) as resp:
            # 200 = diagnostics available, 404 = not supported in this HA version
            assert resp.status in (200, 404)
            if resp.status == 200:
                data = await resp.json()
                # Verify PII redaction
                config = data.get("data", {}).get("config_entry", {}).get("data", {})
                pnr = config.get("personnummer", "")
                if pnr:
                    assert pnr == "**REDACTED**", (
                        "personnummer not redacted in diagnostics"
                    )


# ---------------------------------------------------------------------------
# Tests: Session recovery
# ---------------------------------------------------------------------------


class TestSessionRecovery:
    """Test that the integration recovers after HA restart."""

    @pytest.mark.asyncio
    async def test_entities_not_all_unavailable(self, ha_session) -> None:
        """After restart, at least some entities should have real state."""
        states = await _get_states(ha_session)
        ke = _ke_entities(states)
        available = [s for s in ke if s["state"] not in ("unavailable", "unknown")]
        assert len(available) >= 1, (
            f"All {len(ke)} entities are unavailable/unknown after restart"
        )
