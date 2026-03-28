"""Constants for the Karlstadsenergi integration."""

DOMAIN = "karlstadsenergi"
NAME = "Karlstadsenergi"
VERSION = "0.2.0"

PLATFORMS = ["sensor", "calendar", "binary_sensor"]

# URLs
BASE_URL = "https://minasidor.karlstadsenergi.se"
URL_LOGIN = f"{BASE_URL}/default.aspx/Authenticate"
URL_HEARTBEAT = f"{BASE_URL}/heart.beat"
URL_FLEX_SERVICES = f"{BASE_URL}/Flex/FlexServices.aspx/GetFlexServices"
URL_FLEX_DATES = (
    f"{BASE_URL}/Flex/FlexServices.aspx"
    "/GetNextPlannedFetchDatesOrPrintNameByFlexServiceIds"
)
URL_FLEX_NEXT = f"{BASE_URL}/Start.aspx/GetNextFlexFetchDate"
URL_CONSUMPTION = f"{BASE_URL}/consumption/consumption.aspx/GetConsumption"
URL_SERVICE_INFO = f"{BASE_URL}/consumption/consumption.aspx/GetServiceInfo"
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

# Fee series IDs from GetConsumption IsFeeTypeRequest response
FEE_CONSUMPTION = "ConsumptionFee"
FEE_POWER = "PowerFee"
FEE_FIXED = "FixFee"
FEE_ENERGY_TAX = "EnergyTax"
FEE_VAT = "VAT"
FEE_SUM = "SUM"
