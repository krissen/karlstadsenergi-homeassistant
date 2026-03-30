"""Tests validating the integration's parsing against realistic API fixtures.

These fixtures mirror the actual response format from the Karlstadsenergi
portal (Evado MFR) and the public Evado spot price API. Each test feeds
the raw fixture through the same code path the integration uses, and
asserts that the resulting data matches expectations.

This catches regressions from field name changes, ASP.NET wrapper
variations, and parsing assumptions that hand-crafted mocks might miss.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi.api import (
    BANKID_COMPLETE,
    BANKID_OUTSTANDING,
    BANKID_USER_SIGN,
    KarlstadsenergiApi,
    KarlstadsenergiAuthError,
    _parse_aspnet_response,
)
from custom_components.karlstadsenergi.const import (
    FEE_CONSUMPTION,
    FEE_ENERGY_TAX,
    FEE_FIXED,
    FEE_POWER,
    FEE_SUM,
    FEE_VAT,
    SKIP_GROUP_NAMES,
    pickup_date_for_service,
    pickup_date_for_type,
    slug_for_waste_type,
)
from custom_components.karlstadsenergi.sensor import (
    _extract_fee_months,
    _extract_fee_series,
)

from .conftest import load_fixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(fixture_data: Any, status: int = 200) -> AsyncMock:
    """Build an aiohttp response mock returning the given fixture data."""
    resp = AsyncMock()
    resp.status = status
    resp.headers = {"Content-Type": "application/json"}
    resp.json = AsyncMock(return_value=fixture_data)
    resp.raise_for_status = MagicMock()
    resp.release = AsyncMock()
    return resp


# ---------------------------------------------------------------------------
# ASP.NET response parsing with real fixtures
# ---------------------------------------------------------------------------


class TestAspnetParsingFixtures:
    """Validate _parse_aspnet_response against realistic API wrappers."""

    def test_password_auth_success_double_parsed(self) -> None:
        raw = load_fixture("password_auth_success")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, dict)
        assert result["Result"] is True
        assert result["LoginResultStatus"] == "OK"

    def test_password_auth_boolean_true(self) -> None:
        raw = load_fixture("password_auth_boolean")
        result = _parse_aspnet_response(raw)
        assert result is True

    def test_password_auth_failure_parsed(self) -> None:
        raw = load_fixture("password_auth_failure")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, dict)
        assert result["Result"] is False
        assert result["LoginResultStatus"] == "AuthenticationFailed"

    def test_flex_services_double_parsed(self) -> None:
        raw = load_fixture("flex_services")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_flex_dates_double_parsed(self) -> None:
        raw = load_fixture("flex_dates")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, dict)
        assert "42" in result
        assert result["42"] == "2026-04-15"

    def test_next_flex_fetch_date_double_parsed(self) -> None:
        raw = load_fixture("next_flex_fetch_date")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["Type"] == "Mat- och restavfall"

    def test_consumption_onload_double_parsed(self) -> None:
        raw = load_fixture("consumption_onload")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, dict)
        assert "ConsumptionModel" in result
        assert "CompareModel" in result
        assert result["CompareModel"]["CurrYearValue"] == 5432.1

    def test_consumption_fee_double_parsed(self) -> None:
        raw = load_fixture("consumption_fee")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, dict)
        series = result["DetailedConsumptionChart"]["SeriesList"]
        ids = [s["id"] for s in series]
        assert "ConsumptionFee" in ids
        assert "SUM" in ids

    def test_contract_details_double_parsed(self) -> None:
        raw = load_fixture("contract_details")
        result = _parse_aspnet_response(raw)
        assert isinstance(result, list)
        assert len(result) == 3
        # Preserve upstream typo
        assert result[0]["ElecticityRegion"] == "SE3"


# ---------------------------------------------------------------------------
# Waste data flow: fixture -> coordinator filter -> sensor lookup
# ---------------------------------------------------------------------------


class TestWasteFixtureFlow:
    """Test the full waste data flow from raw API fixture to sensor values."""

    @pytest.fixture
    def raw_services(self) -> list[dict]:
        return _parse_aspnet_response(load_fixture("flex_services"))

    @pytest.fixture
    def raw_dates(self) -> dict[str, str]:
        return _parse_aspnet_response(load_fixture("flex_dates"))

    @pytest.fixture
    def raw_next_dates(self) -> list[dict]:
        return _parse_aspnet_response(load_fixture("next_flex_fetch_date"))

    def test_service_filtering_removes_grundavgft(self, raw_services) -> None:
        """Grundavgft group must be filtered out (billing only, no pickup)."""
        active_services = [
            s
            for s in raw_services
            if s.get("FSStatusName") == "Aktiv"
            and s.get("FlexServiceGroupName") not in SKIP_GROUP_NAMES
        ]
        # 5 total: 3 active household + 1 Grundavgft + 1 Avslutad
        # Filter keeps: 3 active household (Grundavgft skipped, Avslutad skipped)
        assert len(active_services) == 3
        group_names = {s["FlexServiceGroupName"] for s in active_services}
        assert "Grundavgft" not in group_names

    def test_service_filtering_removes_inactive(self, raw_services) -> None:
        """Avslutad (terminated) services must be filtered out."""
        active = [s for s in raw_services if s.get("FSStatusName") == "Aktiv"]
        assert len(active) == 4  # 3 household + 1 Grundavgft
        for s in active:
            assert s["FSStatusName"] == "Aktiv"

    def test_service_ids_match_date_keys(self, raw_services, raw_dates) -> None:
        """Service IDs from fixture must have matching date entries."""
        active_services = [
            s
            for s in raw_services
            if s.get("FSStatusName") == "Aktiv"
            and s.get("FlexServiceGroupName") not in SKIP_GROUP_NAMES
        ]
        for svc in active_services:
            sid = str(svc["FlexServiceId"])
            assert sid in raw_dates, f"Service {sid} has no date entry"

    def test_pickup_date_for_service(self, raw_dates) -> None:
        """pickup_date_for_service parses ISO dates from fixture correctly."""
        data = {"dates": raw_dates, "services": [], "next_dates": []}
        date = pickup_date_for_service(data, 42)
        assert date == datetime.date(2026, 4, 15)
        date2 = pickup_date_for_service(data, 43)
        assert date2 == datetime.date(2026, 5, 10)

    def test_pickup_date_for_type_from_summary(self, raw_next_dates) -> None:
        """pickup_date_for_type finds date by waste type name in summary data."""
        data = {"services": [], "dates": {}, "next_dates": raw_next_dates}
        date = pickup_date_for_type(data, "Mat- och restavfall")
        assert date == datetime.date(2026, 4, 15)
        date2 = pickup_date_for_type(data, "Glas/Metall")
        assert date2 == datetime.date(2026, 5, 10)

    def test_slug_generation_for_known_types(self, raw_services) -> None:
        """Known waste types get their predefined English slugs."""
        known_types = [
            s["FlexServiceContainTypeValue"]
            for s in raw_services
            if s.get("FlexServiceContainTypeValue")
        ]
        expected = {
            "Mat- och restavfall": "food_and_residual_waste",
            "Glas/Metall": "glass_metal",
            "Plast- och pappersförpackningar": "plastic_paper_packaging",
        }
        for wt in known_types:
            if wt in expected:
                assert slug_for_waste_type(wt) == expected[wt]

    def test_slug_generation_for_unknown_type(self, raw_services) -> None:
        """Unknown waste types get sanitized slugs (Swedish chars are alphanumeric in Unicode)."""
        unknown = [
            s
            for s in raw_services
            if s.get("FlexServiceContainTypeValue") == "Trädgårdsavfall"
        ]
        assert len(unknown) == 1
        slug = slug_for_waste_type("Trädgårdsavfall")
        # Swedish å, ä are alphanumeric in Python (Unicode-aware isalnum())
        assert slug == "trädgårdsavfall"

    def test_service_address_and_metadata_present(self, raw_services) -> None:
        """Services from fixture have all expected metadata fields."""
        for svc in raw_services:
            if svc.get("FSStatusName") != "Aktiv":
                continue
            if svc.get("FlexServiceGroupName") in SKIP_GROUP_NAMES:
                continue
            assert "FlexServiceId" in svc
            assert "FlexServiceContainTypeValue" in svc
            assert "FlexServicePlaceAddress" in svc
            assert svc["FlexServicePlaceAddress"] == "Testgatan 1"
            assert "FetchFrequency" in svc
            assert "FlexServicePlaceId" in svc
            assert "SizeOfFlexIndividual" in svc


# ---------------------------------------------------------------------------
# Consumption data flow: fixture -> sensor extraction
# ---------------------------------------------------------------------------


class TestConsumptionFixtureFlow:
    """Test consumption data parsing from realistic fixtures."""

    @pytest.fixture
    def consumption_data(self) -> dict:
        return _parse_aspnet_response(load_fixture("consumption_onload"))

    @pytest.fixture
    def hourly_data(self) -> dict:
        return _parse_aspnet_response(load_fixture("consumption_hourly"))

    @pytest.fixture
    def fee_data(self) -> dict:
        return _parse_aspnet_response(load_fixture("consumption_fee"))

    def test_curr_year_value_extraction(self, consumption_data) -> None:
        """CurrYearValue is the primary consumption sensor state."""
        compare = consumption_data["CompareModel"]
        assert compare["CurrYearValue"] == 5432.1
        assert compare["LastYearValue"] == 4900.0
        assert compare["DifferencePercentage"] == 10.9
        assert compare["CurrYearAvg"] == 14.9

    def test_consumption_model_has_site_id(self, consumption_data) -> None:
        """SiteId is required for contract coordinator."""
        model = consumption_data["ConsumptionModel"]
        assert model["SiteId"] == "site-99"
        assert model["SiteName"] == "Testgatan 1"

    def test_monthly_chart_data_parseable(self, consumption_data) -> None:
        """Monthly chart data has correct structure for sensor attributes."""
        chart = consumption_data["DetailedConsumptionChart"]
        series = chart["SeriesList"]
        assert len(series) >= 1
        data = series[0]["data"]
        assert len(data) == 3
        # Verify dateInterval format
        for point in data:
            assert "dateInterval" in point
            assert "y" in point
            datetime.date.fromisoformat(point["dateInterval"])

    def test_hourly_chart_points(self, hourly_data) -> None:
        """Hourly data has timestamped points."""
        chart = hourly_data["DetailedConsumptionChart"]
        data = chart["SeriesList"][0]["data"]
        assert len(data) == 12
        assert data[0]["dateInterval"] == "2026-03-30T00:00:00"
        assert data[0]["y"] == 0.8
        assert data[-1]["y"] == 0.7

    def test_fee_series_extraction(self, fee_data) -> None:
        """_extract_fee_series produces totals per fee type."""
        fees = _extract_fee_series(fee_data)
        assert FEE_CONSUMPTION in fees
        assert FEE_POWER in fees
        assert FEE_FIXED in fees
        assert FEE_ENERGY_TAX in fees
        assert FEE_VAT in fees
        assert FEE_SUM in fees
        # ConsumptionFee: 487.50 + 412.30 + 198.00 = 1097.80
        assert fees[FEE_CONSUMPTION] == pytest.approx(1097.80)
        # SUM: 1041.38 + 915.63 + 466.38 = 2423.39
        assert fees[FEE_SUM] == pytest.approx(2423.39)

    def test_fee_months_extraction(self, fee_data) -> None:
        """_extract_fee_months finds correct month keys."""
        months = _extract_fee_months(fee_data)
        assert months == {"2026-01", "2026-02", "2026-03"}

    def test_price_calculation_from_fixture(self, consumption_data, fee_data) -> None:
        """End-to-end: fee + consumption -> effective price in SEK/kWh."""
        fees = _extract_fee_series(fee_data)
        fee_months = _extract_fee_months(fee_data)

        chart = consumption_data["DetailedConsumptionChart"]
        data_points = chart["SeriesList"][0]["data"]
        total_kwh = sum(
            p["y"] for p in data_points if p["dateInterval"][:7] in fee_months
        )
        # 320.5 + 285.0 + 120.0 = 725.5 kWh
        assert total_kwh == pytest.approx(725.5)

        consumption_fee = fees[FEE_CONSUMPTION]
        price = round(consumption_fee / total_kwh, 4)
        # 1097.80 / 725.5 = ~1.5132 SEK/kWh
        assert price == pytest.approx(1.5132, abs=0.001)


# ---------------------------------------------------------------------------
# Contract data flow
# ---------------------------------------------------------------------------


class TestContractFixtureFlow:
    """Test contract data parsing from realistic fixtures."""

    @pytest.fixture
    def contracts(self) -> list[dict]:
        return _parse_aspnet_response(load_fixture("contract_details"))

    def test_three_contracts_parsed(self, contracts) -> None:
        assert len(contracts) == 3

    def test_contract_fields_present(self, contracts) -> None:
        """All expected fields from the API are present."""
        required = {
            "ContractId",
            "UtilityName",
            "ContractAlternative",
            "ContractStartDate",
            "ContractEndDate",
            "NetAreaCode",
            "ElecticityRegion",  # upstream typo preserved
        }
        for c in contracts:
            assert required.issubset(c.keys()), f"Missing fields in {c}"

    def test_contract_alternative_is_state_value(self, contracts) -> None:
        """ContractAlternative || UtilityName is the sensor state."""
        for c in contracts:
            value = c.get("ContractAlternative") or c.get("UtilityName")
            assert value  # never empty in fixture

    def test_grid_contract_has_region(self, contracts) -> None:
        grid = [c for c in contracts if "Elnät" in c["UtilityName"]]
        assert len(grid) == 1
        assert grid[0]["ElecticityRegion"] == "SE3"
        assert grid[0]["NetAreaCode"] == "SE3"

    def test_waste_contract_has_empty_region(self, contracts) -> None:
        waste = [c for c in contracts if "Renhållning" in c["UtilityName"]]
        assert len(waste) == 1
        assert waste[0]["ElecticityRegion"] == ""
        assert waste[0]["NetAreaCode"] == ""

    def test_upstream_typo_preserved(self, contracts) -> None:
        """The misspelled 'ElecticityRegion' must be preserved -- it's the real API key."""
        for c in contracts:
            assert "ElecticityRegion" in c
            assert "ElectricityRegion" not in c


# ---------------------------------------------------------------------------
# Spot price data flow: fixture -> _parse_spot_data
# ---------------------------------------------------------------------------


class TestSpotPriceFixtureFlow:
    """Test spot price parsing from Evado fixture."""

    @pytest.fixture
    def raw_spot(self) -> dict:
        return load_fixture("spot_prices")

    def test_parse_produces_all_price_points(self, raw_spot) -> None:
        from custom_components.karlstadsenergi import (
            KarlstadsenergiSpotPriceCoordinator,
        )

        result = KarlstadsenergiSpotPriceCoordinator._parse_spot_data(raw_spot)
        assert len(result["prices"]) == 8
        assert result["region"] == "SE3"

    def test_prices_in_sek_per_kwh(self, raw_spot) -> None:
        from custom_components.karlstadsenergi import (
            KarlstadsenergiSpotPriceCoordinator,
        )

        result = KarlstadsenergiSpotPriceCoordinator._parse_spot_data(raw_spot)
        # First bucket: 45.120 öre/kWh -> 0.4512 SEK/kWh
        assert result["prices"][0]["price_sek"] == 0.4512
        assert result["prices"][0]["price_ore"] == 45.120

    def test_prices_sorted_ascending(self, raw_spot) -> None:
        from custom_components.karlstadsenergi import (
            KarlstadsenergiSpotPriceCoordinator,
        )

        result = KarlstadsenergiSpotPriceCoordinator._parse_spot_data(raw_spot)
        starts = [p["start"] for p in result["prices"]]
        assert starts == sorted(starts)

    def test_utc_plus_0000_parsed_correctly(self, raw_spot) -> None:
        """The +0000 format (not +00:00) must be handled."""
        from custom_components.karlstadsenergi import (
            KarlstadsenergiSpotPriceCoordinator,
        )

        result = KarlstadsenergiSpotPriceCoordinator._parse_spot_data(raw_spot)
        first = result["prices"][0]
        assert first["start"].tzinfo is not None
        assert first["start"].utcoffset().total_seconds() == 0

    def test_price_range(self, raw_spot) -> None:
        """Spot prices in fixture have realistic range for SE3."""
        from custom_components.karlstadsenergi import (
            KarlstadsenergiSpotPriceCoordinator,
        )

        result = KarlstadsenergiSpotPriceCoordinator._parse_spot_data(raw_spot)
        all_sek = [p["price_sek"] for p in result["prices"]]
        assert min(all_sek) == 0.395  # 39.5 öre
        assert max(all_sek) == 0.558  # 55.8 öre


# ---------------------------------------------------------------------------
# BankID fixtures
# ---------------------------------------------------------------------------


class TestBankIdFixtures:
    """Test BankID response parsing against realistic fixtures."""

    def test_initiate_response_fields(self) -> None:
        data = load_fixture("bankid_initiate")
        order = data.get("OrderResponseType", {})
        assert order["orderRefField"] == "e1d2c3b4-a5f6-7890-abcd-ef1234567890"
        assert order["autoStartTokenField"] == "start-token-abc123def456"
        assert order["qrStartTokenField"] == "qr-token-789xyz"
        assert data["QrCodeBase64"]  # non-empty base64

    def test_poll_complete_status(self) -> None:
        data = load_fixture("bankid_poll_complete")
        status = data["CollectResponseType"]["progressStatusField"]
        assert status == BANKID_COMPLETE

    def test_poll_pending_status(self) -> None:
        data = load_fixture("bankid_poll_pending")
        status = data["CollectResponseType"]["progressStatusField"]
        assert status == BANKID_OUTSTANDING

    def test_poll_user_sign_status(self) -> None:
        data = load_fixture("bankid_poll_user_sign")
        status = data["CollectResponseType"]["progressStatusField"]
        assert status == BANKID_USER_SIGN

    def test_poll_error_has_fault(self) -> None:
        data = load_fixture("bankid_poll_error")
        assert data["HasError"] is True
        assert data["GrpFault"]["faultStatusField"] == "CANCELLED"

    def test_customer_list(self) -> None:
        customers = load_fixture("bankid_customers")
        assert len(customers) == 1
        assert customers[0]["FullName"] == "Anna Svensson"
        assert customers[0]["CustomerCode"] == "123456"

    def test_sub_users_list(self) -> None:
        sub_users = load_fixture("bankid_sub_users")
        assert len(sub_users) == 1
        assert sub_users[0]["ParentFirstName"] == "Bo"
        assert sub_users[0]["ParentLastName"] == "Svensson"
        assert sub_users[0]["UserId"] == 99

    def test_login_success(self) -> None:
        data = load_fixture("bankid_login_success")
        assert data["Key"] is True

    def test_login_failure(self) -> None:
        data = load_fixture("bankid_login_failure")
        assert data["Key"] is False
        assert data["Value"] == "Login failed"


# ---------------------------------------------------------------------------
# API method integration with fixtures (mocked HTTP layer)
# ---------------------------------------------------------------------------


class TestApiMethodsWithFixtures:
    """Test API methods using fixtures as mock HTTP responses.

    These tests feed the raw JSON fixture through the actual API method
    (with HTTP mocked), validating that the full parsing pipeline works
    with realistic response data.
    """

    @pytest.fixture
    def api(self) -> KarlstadsenergiApi:
        return KarlstadsenergiApi("199001011234", "password", "testpass")

    @pytest.mark.asyncio
    async def test_authenticate_password_with_fixture(self, api) -> None:
        fixture = load_fixture("password_auth_success")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            result = await api.authenticate_password()

        assert result is True
        assert api._authenticated is True

    @pytest.mark.asyncio
    async def test_authenticate_password_failure_with_fixture(self, api) -> None:
        fixture = load_fixture("password_auth_failure")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            with pytest.raises(KarlstadsenergiAuthError, match="Authentication failed"):
                await api.authenticate_password()

    @pytest.mark.asyncio
    async def test_bankid_initiate_with_fixture(self, api) -> None:
        fixture = load_fixture("bankid_initiate")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            result = await api.bankid_initiate()

        assert result["order_ref"] == "e1d2c3b4-a5f6-7890-abcd-ef1234567890"
        assert result["auto_start_token"] == "start-token-abc123def456"
        assert result["qr_code_base64"]

    @pytest.mark.asyncio
    async def test_bankid_poll_complete_with_fixture(self, api) -> None:
        fixture = load_fixture("bankid_poll_complete")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            result = await api.bankid_poll("test-order-ref")

        assert result["status"] == BANKID_COMPLETE

    @pytest.mark.asyncio
    async def test_bankid_poll_error_raises(self, api) -> None:
        fixture = load_fixture("bankid_poll_error")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            with pytest.raises(KarlstadsenergiAuthError, match="CANCELLED"):
                await api.bankid_poll("test-order-ref")

    @pytest.mark.asyncio
    async def test_bankid_get_customers_with_fixture(self, api) -> None:
        customers_fixture = load_fixture("bankid_customers")
        sub_users_fixture = load_fixture("bankid_sub_users")

        call_count = 0

        async def _mock_post(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "GetCustomerByPinCode" in url:
                return _mock_response(customers_fixture)
            return _mock_response(sub_users_fixture)

        with patch.object(api, "_post", side_effect=_mock_post):
            # Also need _parse_grp2_json to work
            with patch.object(
                api,
                "_parse_grp2_json",
                side_effect=[customers_fixture, sub_users_fixture],
            ):
                result = await api.bankid_get_customers("199001011234", "txn123")

        assert len(result) == 2
        assert result[0]["full_name"] == "Anna Svensson"
        assert result[0]["customer_code"] == "123456"
        assert result[1]["full_name"] == "Bo Svensson"
        assert result[1]["customer_code"] == "654321"
        assert result[1]["sub_user_id"] == "99"

    @pytest.mark.asyncio
    async def test_bankid_login_success_with_fixture(self, api) -> None:
        fixture = load_fixture("bankid_login_success")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            with patch.object(api, "_ensure_session", return_value=AsyncMock()):
                # Mock the session.get for start.aspx visit
                mock_session = AsyncMock()
                mock_get_resp = AsyncMock()
                mock_get_resp.status = 200
                mock_session.get = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_get_resp),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )
                with patch.object(api, "_ensure_session", return_value=mock_session):
                    result = await api.bankid_login("199001011234", "cust-id", "txn123")

        assert result is True

    @pytest.mark.asyncio
    async def test_bankid_login_failure_with_fixture(self, api) -> None:
        fixture = load_fixture("bankid_login_failure")
        resp = _mock_response(fixture)

        with patch.object(api, "_post", return_value=resp):
            with pytest.raises(KarlstadsenergiAuthError, match="Login failed"):
                await api.bankid_login("199001011234", "cust-id", "txn123")
