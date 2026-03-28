"""Tests for pure helper functions in sensor.py.

All functions tested here are module-level (no HA instance required).
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.karlstadsenergi.sensor import (
    _extract_fee_months,
    _extract_fee_series,
    _slug_for_contract,
)
from custom_components.karlstadsenergi.const import (
    CONTRACT_TYPE_SLUG,
    FEE_CONSUMPTION,
    FEE_POWER,
    FEE_VAT,
    WASTE_TYPE_SLUG,
    slug_for_waste_type,
)


# ---------------------------------------------------------------------------
# Helpers duplicated here for clarity (match conftest shape exactly)
# ---------------------------------------------------------------------------


def _make_fee_data(series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"DetailedConsumptionChart": {"SeriesList": series}}


def _make_series(series_id: str, points: list[tuple[str, float]]) -> dict[str, Any]:
    return {"id": series_id, "data": [{"dateInterval": d, "y": v} for d, v in points]}


# ---------------------------------------------------------------------------
# _extract_fee_series
# ---------------------------------------------------------------------------


class TestExtractFeeSeries:
    def test_typical_three_series(self, fee_data_typical) -> None:
        fees = _extract_fee_series(fee_data_typical)
        # ConsumptionFee: 150.50 + 200.00 = 350.50
        assert fees[FEE_CONSUMPTION] == pytest.approx(350.50, abs=0.01)
        # PowerFee: 80.00
        assert fees[FEE_POWER] == pytest.approx(80.00, abs=0.01)
        # VAT: 57.625 -> round(57.625, 2) = 57.62 (banker's rounding)
        assert fees[FEE_VAT] == pytest.approx(57.62, abs=0.01)

    def test_empty_fee_data(self, fee_data_empty) -> None:
        fees = _extract_fee_series(fee_data_empty)
        assert fees == {}

    def test_series_with_no_id_is_skipped(self) -> None:
        data = _make_fee_data(
            [
                {"id": "", "data": [{"dateInterval": "2026-02-01", "y": 100.0}]},
                _make_series("ConsumptionFee", [("2026-02-01", 50.0)]),
            ]
        )
        fees = _extract_fee_series(data)
        assert "" not in fees
        assert fees[FEE_CONSUMPTION] == pytest.approx(50.0)

    def test_series_with_empty_data_list(self) -> None:
        data = _make_fee_data([{"id": "ConsumptionFee", "data": []}])
        fees = _extract_fee_series(data)
        assert fees[FEE_CONSUMPTION] == 0.0

    def test_single_data_point_rounded_to_two_decimals(self) -> None:
        data = _make_fee_data([_make_series("ConsumptionFee", [("2026-02-01", 1.005)])])
        fees = _extract_fee_series(data)
        # round(1.005, 2) in Python is 1.0 due to float representation; check it rounds
        assert round(fees[FEE_CONSUMPTION], 2) == round(1.005, 2)

    def test_missing_y_key_defaults_to_zero(self) -> None:
        data = _make_fee_data(
            [
                {
                    "id": "ConsumptionFee",
                    "data": [
                        {"dateInterval": "2026-02-01"},  # no 'y' key
                        {"dateInterval": "2026-02-02", "y": 50.0},
                    ],
                }
            ]
        )
        fees = _extract_fee_series(data)
        # Missing 'y' returns dict.get default 0; total = 0 + 50 = 50
        assert fees[FEE_CONSUMPTION] == pytest.approx(50.0)

    def test_returns_only_series_present_in_data(self) -> None:
        data = _make_fee_data([_make_series("ConsumptionFee", [("2026-02-01", 200.0)])])
        fees = _extract_fee_series(data)
        assert list(fees.keys()) == [FEE_CONSUMPTION]

    def test_multi_month_data_summed_to_single_total(
        self, fee_data_multi_month
    ) -> None:
        fees = _extract_fee_series(fee_data_multi_month)
        # Jan 100 + Feb 200 = 300
        assert fees[FEE_CONSUMPTION] == pytest.approx(300.0)

    def test_missing_chart_key_returns_empty(self) -> None:
        fees = _extract_fee_series({})
        assert fees == {}


# ---------------------------------------------------------------------------
# _extract_fee_months
# ---------------------------------------------------------------------------


class TestExtractFeeMonths:
    def test_typical_single_month(self, fee_data_typical) -> None:
        months = _extract_fee_months(fee_data_typical)
        assert months == {"2026-02"}

    def test_multi_month_returns_both(self, fee_data_multi_month) -> None:
        months = _extract_fee_months(fee_data_multi_month)
        assert months == {"2026-01", "2026-02"}

    def test_empty_fee_data(self, fee_data_empty) -> None:
        months = _extract_fee_months(fee_data_empty)
        assert months == set()

    def test_deduplicates_same_month_across_series(self) -> None:
        data = _make_fee_data(
            [
                _make_series(
                    "ConsumptionFee", [("2026-02-01", 100.0), ("2026-02-15", 200.0)]
                ),
                _make_series("PowerFee", [("2026-02-01", 80.0)]),
            ]
        )
        months = _extract_fee_months(data)
        assert months == {"2026-02"}

    def test_month_key_is_first_seven_chars(self) -> None:
        data = _make_fee_data([_make_series("ConsumptionFee", [("2026-11-30", 50.0)])])
        months = _extract_fee_months(data)
        assert "2026-11" in months

    def test_short_date_interval_is_skipped(self) -> None:
        data = _make_fee_data(
            [
                {
                    "id": "ConsumptionFee",
                    "data": [
                        {"dateInterval": "2026-0", "y": 10.0},  # only 6 chars
                        {"dateInterval": "2026-02-01", "y": 50.0},
                    ],
                }
            ]
        )
        months = _extract_fee_months(data)
        # "2026-0" has length 6 < 7, so it IS skipped; "2026-02-01" passes
        assert "2026-02" in months
        # "2026-0" would produce "2026-0" (6 chars) -- the guard is len >= 7
        assert "2026-0" not in months

    def test_missing_date_interval_key_is_skipped(self) -> None:
        data = _make_fee_data(
            [
                {
                    "id": "ConsumptionFee",
                    "data": [
                        {"y": 10.0},  # no dateInterval
                        {"dateInterval": "2026-03-01", "y": 20.0},
                    ],
                }
            ]
        )
        months = _extract_fee_months(data)
        assert months == {"2026-03"}


# ---------------------------------------------------------------------------
# slug_for_waste_type  (lives in const.py, imported into sensor.py)
# ---------------------------------------------------------------------------


class TestSlugForWasteType:
    @pytest.mark.parametrize("swedish_name,expected_slug", WASTE_TYPE_SLUG.items())
    def test_known_waste_types_return_correct_slug(
        self, swedish_name: str, expected_slug: str
    ) -> None:
        assert slug_for_waste_type(swedish_name) == expected_slug

    def test_unknown_type_falls_back_to_sanitized_lowercase(self) -> None:
        result = slug_for_waste_type("Ny Fraktion 2026")
        # Spaces -> underscores, lowercase, leading/trailing underscores stripped
        assert result == "ny_fraktion_2026"

    def test_fallback_strips_leading_trailing_underscores(self) -> None:
        result = slug_for_waste_type("!Special!")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_fallback_replaces_slash_with_underscore(self) -> None:
        result = slug_for_waste_type("Typ/Undertyp")
        assert "/" not in result
        assert "_" in result

    def test_empty_string_fallback(self) -> None:
        result = slug_for_waste_type("")
        # All chars stripped -> empty string after strip("_")
        assert isinstance(result, str)

    def test_exact_map_lookup_case_sensitive(self) -> None:
        # The known key is "Mat- och restavfall" (specific casing)
        # Wrong case should NOT return the mapped slug
        result = slug_for_waste_type("mat- och restavfall")
        assert result != "food_and_residual_waste"


# ---------------------------------------------------------------------------
# _slug_for_contract
# ---------------------------------------------------------------------------


class TestSlugForContract:
    @pytest.mark.parametrize("utility_name,expected_slug", CONTRACT_TYPE_SLUG.items())
    def test_known_contract_types_return_correct_slug(
        self, utility_name: str, expected_slug: str
    ) -> None:
        assert _slug_for_contract(utility_name) == expected_slug

    def test_unknown_type_falls_back_to_sanitized_lowercase(self) -> None:
        result = _slug_for_contract("Okänd Tjänst")
        # Swedish chars ä/ö are alphanumeric in Python, so they're kept
        assert result == "okänd_tjänst"

    def test_fallback_strips_non_alnum(self) -> None:
        result = _slug_for_contract("Typ - Med Bindestreck")
        assert "-" not in result

    def test_empty_string_returns_empty_or_underscore_stripped(self) -> None:
        result = _slug_for_contract("")
        assert isinstance(result, str)

    def test_exact_map_lookup_case_sensitive(self) -> None:
        # Wrong case -> fallback
        result = _slug_for_contract("elnät - nätavtal")
        assert result != "grid"
