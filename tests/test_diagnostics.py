"""Tests for diagnostics.py redaction logic.

Tests import async_redact_data from HA and exercise the TO_REDACT_* sets
directly -- no config entry or HA runtime needed.
"""

from __future__ import annotations


from homeassistant.components.diagnostics import async_redact_data

from custom_components.karlstadsenergi.diagnostics import (
    TO_REDACT_CONFIG,
    TO_REDACT_DATA,
)


_REDACTED = "**REDACTED**"


# ---------------------------------------------------------------------------
# TO_REDACT_CONFIG -- config entry fields
# ---------------------------------------------------------------------------


class TestConfigRedaction:
    def test_personnummer_is_redacted(self) -> None:
        data = {"personnummer": "199001011234"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["personnummer"] == _REDACTED

    def test_password_is_redacted(self) -> None:
        data = {"password": "hunter2"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["password"] == _REDACTED

    def test_session_cookies_is_redacted(self) -> None:
        data = {"session_cookies": {"ASP.NET_SessionId": "abc123"}}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["session_cookies"] == _REDACTED

    def test_customer_id_is_redacted(self) -> None:
        data = {"customer_id": "cid-999"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["customer_id"] == _REDACTED

    def test_sub_user_id_is_redacted(self) -> None:
        data = {"sub_user_id": "sub-42"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["sub_user_id"] == _REDACTED

    def test_customer_code_is_redacted(self) -> None:
        data = {"customer_code": "CC123"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["customer_code"] == _REDACTED

    def test_gsrn_number_in_config_is_redacted(self) -> None:
        data = {"GsrnNumber": "735999999000000001"}
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["GsrnNumber"] == _REDACTED

    def test_non_sensitive_config_keys_are_preserved(self) -> None:
        data = {
            "auth_method": "password",
            "non_sensitive": "visible",
            "personnummer": "199001011234",
        }
        result = async_redact_data(data, TO_REDACT_CONFIG)
        assert result["auth_method"] == "password"
        assert result["non_sensitive"] == "visible"

    def test_all_sensitive_keys_in_one_payload(self) -> None:
        data = {
            "personnummer": "199001011234",
            "password": "secret",
            "session_cookies": {},
            "customer_id": "cid",
            "sub_user_id": "sub",
            "customer_code": "CC123",
            "GsrnNumber": "735999999000000001",
            "auth_method": "password",
        }
        result = async_redact_data(data, TO_REDACT_CONFIG)
        for key in (
            "personnummer",
            "password",
            "session_cookies",
            "customer_id",
            "sub_user_id",
            "customer_code",
            "GsrnNumber",
        ):
            assert result[key] == _REDACTED, f"Expected {key} to be redacted"
        assert result["auth_method"] == "password"


# ---------------------------------------------------------------------------
# TO_REDACT_CONFIG -- set membership (guard against regressions)
# ---------------------------------------------------------------------------


class TestConfigRedactSet:
    def test_personnummer_in_set(self) -> None:
        assert "personnummer" in TO_REDACT_CONFIG

    def test_password_in_set(self) -> None:
        assert "password" in TO_REDACT_CONFIG

    def test_session_cookies_in_set(self) -> None:
        assert "session_cookies" in TO_REDACT_CONFIG

    def test_customer_id_in_set(self) -> None:
        assert "customer_id" in TO_REDACT_CONFIG

    def test_sub_user_id_in_set(self) -> None:
        assert "sub_user_id" in TO_REDACT_CONFIG

    def test_customer_code_in_set(self) -> None:
        assert "customer_code" in TO_REDACT_CONFIG

    def test_gsrn_number_in_config_set(self) -> None:
        assert "GsrnNumber" in TO_REDACT_CONFIG


# ---------------------------------------------------------------------------
# TO_REDACT_DATA -- coordinator data fields
# ---------------------------------------------------------------------------


class TestDataRedaction:
    def test_flex_service_place_address_is_redacted(self) -> None:
        data = {"FlexServicePlaceAddress": "Testgatan 1"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["FlexServicePlaceAddress"] == _REDACTED

    def test_site_name_is_redacted(self) -> None:
        data = {"SiteName": "Mätarpunkt 123"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["SiteName"] == _REDACTED

    def test_gsrn_number_in_data_is_redacted(self) -> None:
        data = {"GsrnNumber": "735999999000000001"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["GsrnNumber"] == _REDACTED

    def test_meter_number_is_redacted(self) -> None:
        data = {"MeterNumber": "M-12345"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["MeterNumber"] == _REDACTED

    def test_service_identifier_is_redacted(self) -> None:
        data = {"ServiceIdentifier": "SI-999"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["ServiceIdentifier"] == _REDACTED

    def test_net_area_id_is_redacted(self) -> None:
        data = {"NetAreaId": "NAI-001"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["NetAreaId"] == _REDACTED

    def test_address_is_redacted(self) -> None:
        data = {"Address": "Storgatan 99"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["Address"] == _REDACTED

    def test_site_id_is_redacted(self) -> None:
        data = {"SiteId": "SID-42"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["SiteId"] == _REDACTED

    def test_contract_code_is_redacted(self) -> None:
        data = {"ContractCode": "KC-777"}
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["ContractCode"] == _REDACTED

    def test_non_sensitive_data_fields_are_preserved(self) -> None:
        data = {
            "FlexServiceContainTypeValue": "Mat- och restavfall",
            "FetchFrequency": "Varannan vecka",
            "FlexServicePlaceAddress": "Testgatan 1",
        }
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["FlexServiceContainTypeValue"] == "Mat- och restavfall"
        assert result["FetchFrequency"] == "Varannan vecka"
        assert result["FlexServicePlaceAddress"] == _REDACTED

    def test_nested_data_redaction(self) -> None:
        """Redaction must work inside nested dicts (HA async_redact_data is recursive)."""
        data = {
            "services": [
                {
                    "FlexServicePlaceAddress": "Testgatan 1",
                    "FlexServiceContainTypeValue": "Mat- och restavfall",
                }
            ]
        }
        result = async_redact_data(data, TO_REDACT_DATA)
        assert result["services"][0]["FlexServicePlaceAddress"] == _REDACTED
        assert (
            result["services"][0]["FlexServiceContainTypeValue"]
            == "Mat- och restavfall"
        )


# ---------------------------------------------------------------------------
# TO_REDACT_DATA -- set membership
# ---------------------------------------------------------------------------


class TestDataRedactSet:
    def test_flex_service_place_address_in_set(self) -> None:
        assert "FlexServicePlaceAddress" in TO_REDACT_DATA

    def test_site_name_in_set(self) -> None:
        assert "SiteName" in TO_REDACT_DATA

    def test_gsrn_number_in_data_set(self) -> None:
        assert "GsrnNumber" in TO_REDACT_DATA

    def test_meter_number_in_set(self) -> None:
        assert "MeterNumber" in TO_REDACT_DATA

    def test_service_identifier_in_set(self) -> None:
        assert "ServiceIdentifier" in TO_REDACT_DATA

    def test_net_area_id_in_set(self) -> None:
        assert "NetAreaId" in TO_REDACT_DATA

    def test_address_in_set(self) -> None:
        assert "Address" in TO_REDACT_DATA

    def test_site_id_in_set(self) -> None:
        assert "SiteId" in TO_REDACT_DATA

    def test_contract_code_in_set(self) -> None:
        assert "ContractCode" in TO_REDACT_DATA

    def test_net_area_code_in_set(self) -> None:
        # NetAreaCode is a PII field (network area identifier).
        # If this assertion fails, NetAreaCode should be added to TO_REDACT_DATA.
        assert "NetAreaCode" in TO_REDACT_DATA, (
            "NetAreaCode is missing from TO_REDACT_DATA. "
            "Add it to prevent area code leakage in diagnostics."
        )
