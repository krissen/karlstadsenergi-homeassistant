"""Constants for the Karlstadsenergi integration."""

import datetime

from homeassistant.const import Platform

DOMAIN = "karlstadsenergi"
NAME = "Karlstadsenergi"
VERSION = "0.2.0"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR, Platform.BINARY_SENSOR]

# URLs
BASE_URL = "https://minasidor.karlstadsenergi.se"
URL_LOGIN = f"{BASE_URL}/default.aspx/Authenticate"
URL_FLEX_SERVICES = f"{BASE_URL}/Flex/FlexServices.aspx/GetFlexServices"
URL_FLEX_DATES = (
    f"{BASE_URL}/Flex/FlexServices.aspx"
    "/GetNextPlannedFetchDatesOrPrintNameByFlexServiceIds"
)
URL_CONTRACT_DETAILS = f"{BASE_URL}/Contract/Contracts.aspx/GetContractDetails"
URL_SPOT_PRICES = (
    "https://emc.evado.se/web/spotprices/find_spotprices.json"
    "?Company:name=karlstads_energi&Spotprice:region=SE3&_tree"
)

# Config keys
CONF_PERSONNUMMER = "personnummer"
CONF_AUTH_METHOD = "auth_method"
CONF_UPDATE_INTERVAL = "update_interval"

# Defaults
DEFAULT_UPDATE_INTERVAL = 6  # hours
MIN_UPDATE_INTERVAL = 1
MAX_UPDATE_INTERVAL = 24

# Waste type slug mapping (Swedish name -> English entity slug)
WASTE_TYPE_SLUG: dict[str, str] = {
    "Mat- och restavfall": "food_and_residual_waste",
    "Glas/Metall": "glass_metal",
    "Plast- och pappersförpackningar": "plastic_paper_packaging",
}

# Skip these service groups (billing only, no pickup dates)
# NOTE: "Grundavgft" matches the exact API response (not a typo for "Grundavgift")
SKIP_GROUP_NAMES = {"Grundavgft"}

# Contract type slug mapping (Swedish UtilityName -> English entity slug)
CONTRACT_TYPE_SLUG: dict[str, str] = {
    "Elnät - Nätavtal": "grid",
    "Elhandel - Handelsavtal": "trading",
    "Renhållning - Hushållsavfall": "waste",
}


def slug_for_waste_type(waste_type: str) -> str:
    """Get English slug for a Swedish waste type name."""
    slug = WASTE_TYPE_SLUG.get(waste_type)
    if slug:
        return slug
    result = "".join(c if c.isalnum() else "_" for c in waste_type.lower()).strip("_")
    return result or "unknown"


def pickup_date_for_service(data: dict | None, service_id: int) -> datetime.date | None:
    """Get next pickup date from detailed service data."""
    if not data:
        return None
    date_str = data.get("dates", {}).get(str(service_id))
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def pickup_date_for_type(data: dict | None, waste_type: str) -> datetime.date | None:
    """Get next pickup date from summary data."""
    if not data:
        return None
    for item in data.get("next_dates", []):
        if item.get("Type") == waste_type:
            try:
                return datetime.date.fromisoformat(item["Date"])
            except (ValueError, TypeError, KeyError):
                return None
    return None


# Fee series IDs from GetConsumption IsFeeTypeRequest response
FEE_CONSUMPTION = "ConsumptionFee"
FEE_POWER = "PowerFee"
FEE_FIXED = "FixFee"
FEE_ENERGY_TAX = "EnergyTax"
FEE_VAT = "VAT"
FEE_SUM = "SUM"
