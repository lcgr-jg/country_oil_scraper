"""
Constants and lookups for the European Commission's Weekly Oil Bulletin.

Prices are consumer pump prices (EUR) with and without taxes; tax sheets carry
VAT / excise / other indirect taxes. Demand for elasticity work still comes
from Eurostat / national scrapers — the bulletin's Consumption sheet is annual
only and is stored separately for reference.
"""

from __future__ import annotations

AGENCY_SOURCE = "OilBulletin"  # product_map.csv Source column
SOURCE_ID = "eu_oil_bulletin_prices"
PAGE_URL = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"

# Filename fragments used to discover download links on the bulletin page.
HISTORY_FILENAME_HINT = "Weekly_Oil_Bulletin_Prices_History"
DUTIES_FILENAME_HINT = "Oil_Bulletin_Duties_and_taxes"

# Fallback direct links (UUIDs verified 2026-09 from the public bulletin page).
# Scraper prefers live page discovery; these keep offline / page-layout breaks
# from blocking a bootstrap.
FALLBACK_HISTORY_URL = (
    "https://energy.ec.europa.eu/document/download/"
    "906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)
FALLBACK_DUTIES_URL = (
    "https://energy.ec.europa.eu/document/download/"
    "ccdc6e96-6792-40cb-b0b4-b6609f1e30d0_en"
    "?filename=Oil_Bulletin_Duties_and_taxes.xlsx"
)

HISTORY_SHEET_WITH_TAX = "Prices with taxes"
HISTORY_SHEET_WO_TAX = "Prices wo taxes"
HISTORY_SHEET_CONSUMPTION = "Consumption"
HISTORY_SHEET_VAT = "VAT"
HISTORY_SHEET_EXCISE = "Excise duties"
HISTORY_SHEET_OTHER_TAX = "Other Indirect Taxes"

# Bulletin product code → (product_native label, unit family)
# Units in the workbook: liquids EUR / 1000 l ; fuel oils EUR / t.
PRODUCT_CODES: dict[str, str] = {
    "euro95": "Euro-super 95",
    "diesel": "Automotive gas oil",
    "heating_oil": "Heating gas oil",
    "fuel_oil_1": "Fuel oil sulphur <=1%",
    "fuel_oil_2": "Fuel oil sulphur >1%",
    "LPG": "LPG motor fuel",
}

PRODUCT_UNIT: dict[str, str] = {
    "euro95": "EUR/1000l",
    "diesel": "EUR/1000l",
    "heating_oil": "EUR/1000l",
    "fuel_oil_1": "EUR/t",
    "fuel_oil_2": "EUR/t",
    "LPG": "EUR/1000l",
}

# Metric codes written by the scraper/processor (also registered in metric_types.yaml).
METRIC_PRICE_WITH_TAX = "X_PRICE_WITH_TAX"
METRIC_PRICE_WO_TAX = "X_PRICE_WO_TAX"
METRIC_TAX_WEDGE = "X_TAX_WEDGE"
METRIC_VAT_RATE = "X_VAT_RATE"
METRIC_EXCISE = "X_EXCISE"
METRIC_OTHER_TAX = "X_OTHER_INDIRECT_TAX"
METRIC_FX = "X_FX_TO_EUR"
METRIC_CONSUMPTION_ANNUAL = "X_BULLETIN_CONSUMPTION"

# Bulletin geo code → (country_id slug, display name).
# GR is Greece in the bulletin; Eurostat uses EL — join via country_id.
# EU / EUR are aggregates (EU-27 weighted / euro-area), not single countries.
GEO_CATALOG: dict[str, tuple[str, str]] = {
    "AT": ("austria", "Austria"),
    "BE": ("belgium", "Belgium"),
    "BG": ("bulgaria", "Bulgaria"),
    "CY": ("cyprus", "Cyprus"),
    "CZ": ("czechia", "Czechia"),
    "DE": ("germany", "Germany"),
    "DK": ("denmark", "Denmark"),
    "EE": ("estonia", "Estonia"),
    "ES": ("spain", "Spain"),
    "FI": ("finland", "Finland"),
    "FR": ("france", "France"),
    "GR": ("greece", "Greece"),
    "HR": ("croatia", "Croatia"),
    "HU": ("hungary", "Hungary"),
    "IE": ("ireland", "Ireland"),
    "IT": ("italy", "Italy"),
    "LT": ("lithuania", "Lithuania"),
    "LU": ("luxembourg", "Luxembourg"),
    "LV": ("latvia", "Latvia"),
    "MT": ("malta", "Malta"),
    "NL": ("netherlands", "Netherlands"),
    "PL": ("poland", "Poland"),
    "PT": ("portugal", "Portugal"),
    "RO": ("romania", "Romania"),
    "SE": ("sweden", "Sweden"),
    "SI": ("slovenia", "Slovenia"),
    "SK": ("slovakia", "Slovakia"),
    "UK": ("uk", "United Kingdom"),
    "EU": ("eu27", "EU aggregate"),
    "EUR": ("euro_area", "Euro area aggregate"),
}

# Larger markets — default emphasis in the elasticity notebook / summaries.
LARGE_MARKETS: frozenset[str] = frozenset(
    {
        "DE",
        "FR",
        "IT",
        "ES",
        "NL",
        "PL",
        "BE",
        "SE",
        "AT",
        "RO",
        "CZ",
        "PT",
        "GR",
        "HU",
        "DK",
        "FI",
        "IE",
    }
)

# Shock windows for demand–price studies (inclusive). Kept mutually exclusive
# so a month maps to one primary regime; refine as the analysis iterates.
SHOCK_WINDOWS: list[dict[str, str]] = [
    {
        "id": "covid",
        "label": "COVID-19 demand shock",
        "start": "2020-03-01",
        "end": "2021-12-31",
    },
    {
        "id": "russia_ukraine",
        "label": "Russia–Ukraine invasion",
        "start": "2022-02-01",
        "end": "2023-09-30",
    },
    {
        "id": "israel_hamas",
        "label": "Israel–Hamas / broader ME risk",
        "start": "2023-10-01",
        "end": "2023-11-30",
    },
    {
        "id": "red_sea",
        "label": "Red Sea / Houthi disruption",
        "start": "2023-12-01",
        "end": "2024-03-31",
    },
    {
        "id": "iran_israel",
        "label": "Iran–Israel escalations",
        "start": "2024-04-01",
        "end": "2026-01-31",
    },
    {
        "id": "usa_iran",
        "label": "USA–Iran war",
        "start": "2026-02-01",
        "end": None,  # open-ended — charts/panels clamp to observed data end
    },
]

# Bloomberg futures / assessments used for pass-through vs Oil Bulletin retail.
# GNEBM1 = Eurobob oxygenated gasoline FOB Rotterdam barges (USD/t), generic M1.
# QS1    = ICE Low Sulphur Gasoil front-month future (USD/t).
FUTURES_TICKERS: dict[str, dict[str, str]] = {
    "Gasoline": {
        "ticker": "GNEBM1 Index",
        "label": "Eurobob oxy FOB ARA barges (GNEBM1)",
        "unit": "USD/t",
    },
    "Diesel": {
        "ticker": "QS1 Comdty",
        "label": "ICE LS Gasoil M1 (QS1)",
        "unit": "USD/t",
    },
}

CANONICAL_COLUMNS: list[str] = [
    "date",
    "country",
    "country_name",
    "country_id",
    "source",
    "metric_type",
    "product_native",
    "product",
    "value",
    "unit",
    "is_provisional",
    "source_file",
    "updated_at",
]

MASTER_PARQUET_REL = "eu_oil_bulletin/eu_oil_bulletin_prices.parquet"
TAX_PARQUET_REL = "eu_oil_bulletin/eu_oil_bulletin_taxes.parquet"
CONSUMPTION_PARQUET_REL = "eu_oil_bulletin/eu_oil_bulletin_consumption_annual.parquet"
