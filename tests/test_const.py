"""Tests for pure helpers in const.py.

Tests slug_for_waste_type, pickup_date_for_service and pickup_date_for_type.
No HA instance required.
"""

from __future__ import annotations

import datetime

import pytest

from custom_components.karlstadsenergi.const import (
    WASTE_TYPE_SLUG,
    pickup_date_for_service,
    pickup_date_for_type,
    slug_for_waste_type,
)


# ---------------------------------------------------------------------------
# slug_for_waste_type
# ---------------------------------------------------------------------------


class TestSlugForWasteType:
    @pytest.mark.parametrize("swedish_name,expected_slug", WASTE_TYPE_SLUG.items())
    def test_known_waste_types_return_mapped_slug(
        self, swedish_name: str, expected_slug: str
    ) -> None:
        assert slug_for_waste_type(swedish_name) == expected_slug

    def test_unknown_type_returns_sanitized_slug(self) -> None:
        result = slug_for_waste_type("Ny Fraktion 2026")
        assert result == "ny_fraktion_2026"

    def test_spaces_replaced_with_underscores(self) -> None:
        result = slug_for_waste_type("Typ Med Mellanslag")
        assert " " not in result
        assert "_" in result

    def test_slash_replaced_with_underscore(self) -> None:
        result = slug_for_waste_type("Typ/Undertyp")
        assert "/" not in result

    def test_uppercase_converted_to_lowercase(self) -> None:
        result = slug_for_waste_type("AVGIFTSAVFALL")
        assert result == result.lower()

    def test_leading_trailing_underscores_stripped(self) -> None:
        result = slug_for_waste_type("!Special!")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_empty_string_returns_hash_slug(self) -> None:
        result = slug_for_waste_type("")
        # Empty string produces a hash-based slug to avoid collisions
        assert result.startswith("waste_")
        assert len(result) > len("waste_")

    def test_all_special_chars_returns_hash_slug(self) -> None:
        # String with only non-alphanumeric chars -> all stripped -> hash-based slug
        result = slug_for_waste_type("!!!###")
        assert result.startswith("waste_")

    def test_different_empty_inputs_produce_different_slugs(self) -> None:
        assert slug_for_waste_type("") != slug_for_waste_type("!!!")

    def test_case_sensitive_lookup(self) -> None:
        # Wrong case must NOT return the mapped slug
        result = slug_for_waste_type("mat- och restavfall")
        assert result != "food_and_residual_waste"

    def test_returns_string_always(self) -> None:
        result = slug_for_waste_type("Anything")
        assert isinstance(result, str)

    def test_hyphen_in_unknown_type_becomes_underscore(self) -> None:
        result = slug_for_waste_type("My-Type")
        assert "-" not in result


# ---------------------------------------------------------------------------
# pickup_date_for_service
# ---------------------------------------------------------------------------


class TestPickupDateForService:
    def test_returns_date_for_known_service_id(self) -> None:
        data = {"dates": {"123": "2026-04-15"}}
        result = pickup_date_for_service(data, 123)
        assert result == datetime.date(2026, 4, 15)

    def test_returns_none_for_unknown_service_id(self) -> None:
        data = {"dates": {"999": "2026-04-15"}}
        result = pickup_date_for_service(data, 123)
        assert result is None

    def test_returns_none_when_data_is_none(self) -> None:
        assert pickup_date_for_service(None, 123) is None

    def test_returns_none_when_data_is_empty_dict(self) -> None:
        assert pickup_date_for_service({}, 123) is None

    def test_returns_none_when_dates_key_missing(self) -> None:
        data = {"services": []}
        assert pickup_date_for_service(data, 123) is None

    def test_returns_none_when_dates_is_explicit_null(self) -> None:
        data = {"dates": None}
        assert pickup_date_for_service(data, 123) is None

    def test_returns_none_for_invalid_date_string(self) -> None:
        data = {"dates": {"123": "not-a-date"}}
        assert pickup_date_for_service(data, 123) is None

    def test_returns_none_for_none_date_value(self) -> None:
        data = {"dates": {"123": None}}
        assert pickup_date_for_service(data, 123) is None

    def test_returns_none_for_empty_date_string(self) -> None:
        data = {"dates": {"123": ""}}
        assert pickup_date_for_service(data, 123) is None

    def test_service_id_matched_as_string(self) -> None:
        # dict keys are strings; service_id is int -- coercion must work
        data = {"dates": {"42": "2026-06-01"}}
        result = pickup_date_for_service(data, 42)
        assert result == datetime.date(2026, 6, 1)

    def test_returns_correct_date_when_multiple_services(self) -> None:
        data = {
            "dates": {
                "1": "2026-04-10",
                "2": "2026-04-20",
                "3": "2026-04-30",
            }
        }
        assert pickup_date_for_service(data, 2) == datetime.date(2026, 4, 20)
        assert pickup_date_for_service(data, 3) == datetime.date(2026, 4, 30)


# ---------------------------------------------------------------------------
# pickup_date_for_type
# ---------------------------------------------------------------------------


class TestPickupDateForType:
    def test_returns_date_for_matching_type(self) -> None:
        data = {
            "next_dates": [
                {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
            ]
        }
        result = pickup_date_for_type(data, "Mat- och restavfall")
        assert result == datetime.date(2026, 4, 15)

    def test_returns_none_when_no_match(self) -> None:
        data = {
            "next_dates": [
                {"Type": "Glas/Metall", "Date": "2026-04-22"},
            ]
        }
        result = pickup_date_for_type(data, "Mat- och restavfall")
        assert result is None

    def test_returns_none_when_data_is_none(self) -> None:
        assert pickup_date_for_type(None, "Mat- och restavfall") is None

    def test_returns_none_when_data_is_empty_dict(self) -> None:
        assert pickup_date_for_type({}, "Mat- och restavfall") is None

    def test_returns_none_when_next_dates_empty(self) -> None:
        assert pickup_date_for_type({"next_dates": []}, "Mat- och restavfall") is None

    def test_returns_none_for_invalid_date_string(self) -> None:
        data = {"next_dates": [{"Type": "Mat- och restavfall", "Date": "bad-date"}]}
        assert pickup_date_for_type(data, "Mat- och restavfall") is None

    def test_returns_none_when_date_key_missing(self) -> None:
        data = {"next_dates": [{"Type": "Mat- och restavfall"}]}
        assert pickup_date_for_type(data, "Mat- och restavfall") is None

    def test_returns_correct_type_when_multiple_present(self) -> None:
        data = {
            "next_dates": [
                {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
                {"Type": "Glas/Metall", "Date": "2026-04-22"},
                {"Type": "Plast- och pappersförpackningar", "Date": "2026-04-29"},
            ]
        }
        assert pickup_date_for_type(data, "Glas/Metall") == datetime.date(2026, 4, 22)
        assert pickup_date_for_type(
            data, "Plast- och pappersförpackningar"
        ) == datetime.date(2026, 4, 29)

    def test_type_match_is_exact(self) -> None:
        data = {
            "next_dates": [
                {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
            ]
        }
        # Case-sensitive -- wrong case returns None
        assert pickup_date_for_type(data, "mat- och restavfall") is None

    def test_returns_none_when_next_dates_key_missing(self) -> None:
        data = {"services": []}
        assert pickup_date_for_type(data, "Mat- och restavfall") is None

    def test_returns_none_when_next_dates_is_explicit_null(self) -> None:
        data = {"next_dates": None}
        assert pickup_date_for_type(data, "Mat- och restavfall") is None
