"""
reference.italy
───────────────
MASE consumi petroliferi product-label helpers.

Italian workbooks use inconsistent spellings across definitive (2002–2025)
and preliminary (2022+) files. ``product_map.csv`` defines the unified product
set; this module normalizes raw group/sub labels to those ``Product_name`` keys.

Used by ``scrapers/italy_mase.py`` (parse) and the future Italy processor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from reference.loaders import is_aggregate, is_primary, load_product_map

# Agency key in product_map.csv (matches sources.yaml / processors).
MASE_AGENCY_SOURCE = "MASE"

# Dataset key in metric_types.yaml source_mappings.
MASE_DATASET_SOURCE = "mase_consumi_petroliferi"
SOURCE_ID = MASE_DATASET_SOURCE

MASE_METRIC_TYPE = "TOTDEMO"
MASE_UNIT_NATIVE = "kt"

# Headline native rows for Italy-vs-JODI dashboards (one per product family).
# Values must match Product_name keys in product_map.csv exactly.
REPORTING_PRODUCTS: dict[str, str] = {
    "gasoline": "BENZINA | AUTO TOTALE",
    "jet_fuel": "CARBOTURBO | TOTALE (A)",
    "diesel": "GASOLIO | MOTORI",
    "gasoil_total": "GASOLIO | TOTALE GASOLI",
    "lpg": "GPL",
    "bitumen": "BITUMI",
    "lubricants": "LUBRIFICANTI TOTALE",
    "fuel_oil": "OLIO COMB.LE | TOTALE",
    "other_kerosene": "PETROLIO | TOTALE",
    "naphtha_feedstock": "CARICA PETROLCHIMICA NETTA",
}

_CHART_PRODUCT_KEYS: tuple[str, ...] = (
    "gasoline",
    "jet_fuel",
    "diesel",
    "lpg",
    "fuel_oil",
    "bitumen",
    "lubricants",
    "other_kerosene",
)

CHART_PRODUCTS: tuple[str, ...] = tuple(
    REPORTING_PRODUCTS[k] for k in _CHART_PRODUCT_KEYS
)

DISPLAY_LABELS: dict[str, str] = {
    REPORTING_PRODUCTS["gasoline"]: "Gasoline",
    REPORTING_PRODUCTS["jet_fuel"]: "Jet fuel",
    REPORTING_PRODUCTS["diesel"]: "Diesel",
    REPORTING_PRODUCTS["lpg"]: "LPG",
    REPORTING_PRODUCTS["fuel_oil"]: "Fuel oil",
    REPORTING_PRODUCTS["bitumen"]: "Bitumen",
    REPORTING_PRODUCTS["lubricants"]: "Lubricants",
    REPORTING_PRODUCTS["other_kerosene"]: "Kerosene",
}

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = CHART_PRODUCTS
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Jet fuel",
    "Diesel",
    "LPG",
    "Fuel oil",
    "Bitumen",
    "Lubes & greases",
    "Kerosene",
)

# Canonical Sub-category used to discover scattered fuel-oil rows in workbooks.
FUEL_OIL_SUBCATEGORY = "Fuel Oil"

# Native rows excluded from domestic delivery headline totals (still stored in parquet).
DELIVERY_EXCLUDED_NATIVE: frozenset[str] = frozenset(
    {
        "CARICA PETROLCHIMICA NETTA",
        "CARICA PETROLCHIMICA LORDA",
        "CONSUMI E PERDITE DI RAFFINERIA",
        "CONSUMI PROD.NE EN. EL.",
        "PRODUZIONE ENERGIA ELETTRICA E TERMICA",
        "BUNKERS | T O T A L E",
        "BUNKERS TOTALE",
        "BUNKERS | GASOLIO",
        "BUNKERS | OLIO COMB.LE",
        "BUNKERS | OLIO COMB.",
        "BUNKERS | LUBRIFICANTI",
        "TOTALE PRODOTTI PRINCIPALI",
        "TOTALE VENDITE",
        "TOTALE IMMISSIONI AL CONSUMO",
        "TOTALE CONSUMI",
        "TOTALE | CONSUMI",
        "DELTA SCORTE CONSUMATORI",
        "DELTA SCORTE CONSUMATORI | GASOLIO RISCALDAMENTO",
        "DELTA SCORTE CONSUMATORI | OLIO COMBUSTIBILE",
        "GASOLIO RISCALDAMENTO",
        "OLIO COMBUSTIBILE",
    }
)

# Consumer inventory change rows (additive for JODI-style demand, not physical sales).
STOCK_DELTA_NATIVE: frozenset[str] = frozenset(
    {
        "DELTA SCORTE CONSUMATORI | GASOLIO RISCALDAMENTO",
        "GASOLIO RISCALDAMENTO",
        "DELTA SCORTE CONSUMATORI | OLIO COMBUSTIBILE",
        "OLIO COMBUSTIBILE",
    }
)

# MASE headline delivery rows used for domestic charts (non-overlapping set).
DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    k
    for k in (
        "gasoline",
        "jet_fuel",
        "gasoil_total",
        "lpg",
        "bitumen",
        "lubricants",
        "fuel_oil",
        "other_kerosene",
    )
    if (v := REPORTING_PRODUCTS.get(k)) is not None
)

# Simple sum composites for Italy-vs-JODI compare (country-specific views).
GASOIL_JODI_COMPONENTS: tuple[str, ...] = (
    "GASOLIO | TOTALE GASOLI",
    "BUNKERS | GASOLIO",
    "DELTA SCORTE CONSUMATORI | GASOLIO RISCALDAMENTO",
    "GASOLIO RISCALDAMENTO",
)

FUEL_OIL_HEADLINE_NATIVE: frozenset[str] = frozenset(
    {
        "OLIO COMB.LE | TOTALE",
        "OLIO COMB. | TOTALE",
        "TOTALE O.C. ALTRI USI",
    }
)

FUEL_OIL_BUNKER_NATIVE: frozenset[str] = frozenset(
    {
        "BUNKERS | OLIO COMB.LE",
        "BUNKERS | OLIO COMB.",
    }
)


@dataclass(frozen=True)
class JodiCompareSeries:
    """One MASE-vs-JODI panel definition."""

    key: str
    jodi_energy_product: str
    panel: str
    product_kind: str
    mode: str = "reporting"  # reporting | sum | fuel_oil_scattered
    components: tuple[str, ...] = ()


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        key="gasoline",
        jodi_energy_product="GASOLINE",
        panel="Gasoline",
        product_kind="gasoline",
        mode="reporting",
    ),
    "jet_fuel": JodiCompareSeries(
        key="jet_fuel",
        jodi_energy_product="JETKERO",
        panel="Jet fuel",
        product_kind="jet",
        mode="reporting",
    ),
    "gasoil": JodiCompareSeries(
        key="gasoil",
        jodi_energy_product="GASDIES",
        panel="Gasoil / diesel",
        product_kind="diesel",
        mode="sum",
        components=GASOIL_JODI_COMPONENTS,
    ),
    "lpg": JodiCompareSeries(
        key="lpg",
        jodi_energy_product="LPG",
        panel="LPG",
        product_kind="lpg",
        mode="reporting",
    ),
    "fuel_oil": JodiCompareSeries(
        key="fuel_oil",
        jodi_energy_product="RESFUEL",
        panel="Fuel oil",
        product_kind="fuel_oil",
        mode="fuel_oil_scattered",
    ),
}

# Raw product-group labels -> normalized group (before combining with sub-line).
_GROUP_ALIASES: dict[str, str] = {
    "CARBOT.": "CARBOTURBO",
    "CARBOT": "CARBOTURBO",
    "G.P.L.": "GPL",
    "G.P.L": "GPL",
    "OLIO COMB.": "OLIO COMB.LE",
    "OLIO COMB": "OLIO COMB.LE",
    "TOT.": "TOTALE",
    "TOT": "TOTALE",
}

# Sub-line labels -> normalized sub-line (after strip/upper).
_SUB_ALIASES: dict[str, str] = {
    "TERMOELETT.": "TERMOELETTRICA",
    "TERMOELETTR.": "TERMOELETTRICA",
    "TERMOELETTICA": "TERMOELETTRICA",
    "RETE AUTOSTRAD.": "RETE AUTOSTRADALE",
    "ATZ": "A.T.Z.",
    "BTZ": "B.T.Z.",
}

# Full Product_name keys after group|sub assembly — spelling/layout variants only.
_FULL_KEY_ALIASES: dict[str, str] = {
    "BENZINA RETE AUTOSTRAD.": "BENZINA | RETE AUTOSTRAD.",
    "BENZINA RETE AUTOSTRADALE": "BENZINA | RETE AUTOSTRADALE",
    "GASOLIO RETE AUTOSTRAD.": "GASOLIO | RETE AUTOSTRAD.",
    "GASOLIO RETE AUTOSTRADALE": "GASOLIO | RETE AUTOSTRADALE",
    "CARICA PETROLCHIM. NETTA": "CARICA PETROLCHIMICA NETTA",
    "PETROLCHIMICA C. LORDA": "CARICA PETROLCHIMICA LORDA",
    "CONSUMI E PERDITE DI RAFF.": "CONSUMI E PERDITE DI RAFFINERIA",
    "CONSUMI PROD. EN. EL.": "CONSUMI PROD.NE EN. EL.",
    "TOT. IMMISSIONI AL CONSUMO": "TOTALE IMMISSIONI AL CONSUMO",
    "TOTALE O.C. ALTRI USI": "OLIO COMB.LE | TOTALE",
    "LUBRIFICANTI TOTALE | MOTORI": "LUBRIFICANTI MOTORI",
    "GASOLIO | GASOLIO EXTRARETE": "GASOLIO | EXTRARETE",
    "GASOLIO | GASOLIO RETE": "GASOLIO | GASOLIO RETE",
    "GASOLIO | RETE": "GASOLIO | GASOLIO RETE",
    "CONSUMI OLIO COMB. TERMOELETTRICA | A.T.Z.": "OLIO COMB.LE | A.T.Z.",
    "CONSUMI OLIO COMB. TERMOELETTRICA | ATZ": "OLIO COMB.LE | A.T.Z.",
    "CONSUMI OLIO COMB. TERMOELETTRICA | B.T.Z.": "OLIO COMB.LE | B.T.Z.",
    "CONSUMI OLIO COMB. TERMOELETTRICA | BTZ": "OLIO COMB.LE | B.T.Z.",
    "CONSUMI OLIO COMB. TERMOELETTRICA": "OLIO COMB.LE | TERMOELETTRICA",
}

# Parser noise — column headers, not product rows.
_SKIP_LABELS = frozenset({"PRODOTTO", "PRODUCT"})

# Rows that mean "di cui" / breakdown — parser sets group; sub comes from col 1.
_DICUI_PREFIXES = ("DI CUI", "DI CUI:", "DI CUI :", "DICUI")

# Footnote markers and trailing enumerators in MASE labels.
_FOOTNOTE_RE = re.compile(r"\(\*+\)|#|°|\d+\)")


def _mase_product_names() -> frozenset[str]:
    pm = load_product_map()
    mask = pm["Source"] == MASE_AGENCY_SOURCE
    return frozenset(pm.loc[mask, "Product_name"].astype(str).tolist())


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = _FOOTNOTE_RE.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


def _dedupe_subline_prefix(group: str, subline: str) -> str:
    """Preliminary rows repeat the group in the sub-line (e.g. GASOLIO EXTRARETE)."""
    if not group or not subline:
        return subline
    prefix = f"{group} "
    if subline.startswith(prefix):
        return subline[len(prefix) :]
    return subline


def _resolve_mase_product_key(key: str, known: frozenset[str]) -> str:
    """Map assembled label to a ``product_map.csv`` Product_name if possible."""
    # Prefer explicit aliases (e.g. preliminary TOTALE O.C. -> headline row).
    alt = _FULL_KEY_ALIASES.get(key)
    if alt and alt in known:
        return alt

    if key in known:
        return key

    # Abbreviated group embedded in a single cell (no pipe).
    for src, dst in _FULL_KEY_ALIASES.items():
        if "|" not in src and key == src and dst in known:
            return dst

    # Strip trailing footnote markers from combined keys (e.g. NETTA #).
    trimmed = re.sub(r"\s+#$", "", key).strip()
    alt = _FULL_KEY_ALIASES.get(trimmed)
    if alt and alt in known:
        return alt

    if trimmed in known:
        return trimmed

    return key


def normalize_mase_group(label: object) -> str:
    """Normalize a product-group cell (column 0) from a MASE workbook."""
    text = _clean_text(label)
    if not text:
        return ""
    if any(text.startswith(p) for p in _DICUI_PREFIXES):
        return ""
    if text.startswith("="):
        return ""
    return _GROUP_ALIASES.get(text, text)


def normalize_mase_subline(label: object) -> str:
    """Normalize a sub-line cell (column 1) from a MASE workbook."""
    text = _clean_text(label)
    if not text or text == "=":
        return ""
    if text.startswith("= "):
        text = text[2:].strip()
    return _SUB_ALIASES.get(text, text)


def normalize_mase_product_name(
    group: object,
    subline: object = None,
    *,
    known_group: str = "",
) -> str:
    """
    Map raw (group, sub-line) cells to a ``product_map.csv`` Product_name key.

    Args:
        group: Column-0 product group from the workbook.
        subline: Column-1 sub-line (optional).
        known_group: Forward-filled group when column 0 is blank (di cui rows).

    Returns:
        Normalized key, e.g. ``BENZINA | AUTO TOTALE`` or ``GPL``.
    """
    g = normalize_mase_group(group)
    if not g:
        g = _clean_text(known_group)
        g = _GROUP_ALIASES.get(g, g)

    if g in _SKIP_LABELS:
        return ""

    s = normalize_mase_subline(subline)
    s = _dedupe_subline_prefix(g, s)

    # Preliminary: BENZINA (*) with blank sub = headline gasoline total.
    if g == "BENZINA" and not s:
        key = "BENZINA | AUTO TOTALE"
    # Preliminary: CARBOTURBO with blank sub = jet total (TOTALE (A)).
    elif g == "CARBOTURBO" and not s:
        key = "CARBOTURBO | TOTALE (A)"
    elif g == "CARBOTURBO" and s == "TOTALE":
        key = "CARBOTURBO | TOTALE (A)"
    elif g == "GASOLIO" and s == "TOTALE":
        key = "GASOLIO | TOTALE GASOLI"
    elif s:
        key = f"{g} | {s}"
    else:
        key = g

    known = _mase_product_names()
    return _resolve_mase_product_key(key, known)


def is_mase_reporting_product(product_name: str) -> bool:
    """True if ``product_name`` is one of the headline REPORTING_PRODUCTS values."""
    return product_name in set(REPORTING_PRODUCTS.values())


def is_mase_stored_primary(product_name: str) -> bool:
    """
    True if this row should receive canonical columns and default demand sums.

    Excludes [AGG] super-rows tagged for exclusion and unknown labels.
    """
    try:
        if is_aggregate(product_name, MASE_AGENCY_SOURCE):
            # Headline [AGG] rows (Gasoline, Diesel, …) still have Sub-category set.
            return is_primary(product_name, MASE_AGENCY_SOURCE)
        return is_primary(product_name, MASE_AGENCY_SOURCE)
    except KeyError:
        return False


def reporting_product_for_kind(kind: str) -> Optional[str]:
    """Return the native Product_name used for dashboard/JODI compare."""
    return REPORTING_PRODUCTS.get(kind)


def _fuel_oil_detail_native() -> frozenset[str]:
    """Fuel-oil grade/use rows from product_map (excl. headline, bunker, stock delta)."""
    pm = load_product_map()
    mask = (pm["Source"] == MASE_AGENCY_SOURCE) & (
        pm["Sub-category"] == FUEL_OIL_SUBCATEGORY
    )
    names = frozenset(pm.loc[mask, "Product_name"].astype(str).tolist())
    return names - FUEL_OIL_HEADLINE_NATIVE - FUEL_OIL_BUNKER_NATIVE - STOCK_DELTA_NATIVE


def fuel_oil_jodi_native_labels() -> dict[str, frozenset[str]]:
    """Grouped native labels for the scattered fuel-oil JODI composite."""
    return {
        "headline": FUEL_OIL_HEADLINE_NATIVE,
        "details": _fuel_oil_detail_native(),
        "bunker": FUEL_OIL_BUNKER_NATIVE,
        "stock_delta": STOCK_DELTA_NATIVE,
    }


def _sum_native_by_date(
    demand: pd.DataFrame,
    product_names: frozenset[str] | set[str],
) -> pd.DataFrame:
    """Sum ``value`` (kt) for native products by date and provisional flag."""
    if demand.empty or not product_names:
        return pd.DataFrame(columns=["date", "is_provisional", "value_kt"])

    sl = demand.loc[demand["product_native"].isin(product_names)].copy()
    if sl.empty:
        return pd.DataFrame(columns=["date", "is_provisional", "value_kt"])

    return (
        sl.groupby(["date", "is_provisional"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "value_kt"})
    )


def compute_gasoil_jodi_kt(demand: pd.DataFrame) -> pd.DataFrame:
    """
    JODI-comparable gasoil/diesel demand (kt).

    MASE domestic gasoil deliveries plus bunker gasoil and consumer heating-oil
    stock change. Does not add ``GASOLIO | RISCALDAMENTO`` (already in TOTALE GASOLI).
    """
    return _sum_native_by_date(demand, frozenset(GASOIL_JODI_COMPONENTS))


def compute_fuel_oil_jodi_kt(demand: pd.DataFrame) -> pd.DataFrame:
    """
    JODI-comparable fuel-oil demand (kt).

    Sums scattered Fuel Oil sub-category rows without double-counting the
    headline total when grade/use splits are present:

    * domestic = sum(detail rows) when any detail exists for the month, else headline
    * plus bunker fuel oil and consumer fuel-oil stock delta
    """
    groups = fuel_oil_jodi_native_labels()
    all_names = (
        groups["headline"]
        | groups["details"]
        | groups["bunker"]
        | groups["stock_delta"]
    )
    sl = demand.loc[demand["product_native"].isin(all_names)].copy()
    if sl.empty:
        return pd.DataFrame(columns=["date", "is_provisional", "value_kt"])

    rows: list[dict] = []
    for (date, is_provisional), month in sl.groupby(["date", "is_provisional"]):
        details = month.loc[month["product_native"].isin(groups["details"]), "value"]
        headlines = month.loc[month["product_native"].isin(groups["headline"]), "value"]
        # Use scattered grade/use rows when any carry volume; else the headline total.
        if len(details) > 0 and details.abs().sum() > 0:
            domestic = float(details.sum())
        else:
            domestic = float(headlines.sum())
        bunker = float(
            month.loc[month["product_native"].isin(groups["bunker"]), "value"].sum()
        )
        stock_delta = float(
            month.loc[
                month["product_native"].isin(groups["stock_delta"]), "value"
            ].sum()
        )
        rows.append(
            {
                "date": date,
                "is_provisional": is_provisional,
                "value_kt": domestic + bunker + stock_delta,
            }
        )
    return pd.DataFrame(rows)


def compute_jodi_compare_kt(
    demand: pd.DataFrame,
    series_key: str,
) -> pd.DataFrame:
    """
    Build one MASE-side JODI compare series in kt.

    ``demand`` should already be filtered to ``metric_type == TOTDEMO``.
    """
    spec = JODI_COMPARE_SERIES.get(series_key)
    if spec is None:
        raise KeyError(
            f"Unknown JODI compare series {series_key!r}. "
            f"Valid keys: {sorted(JODI_COMPARE_SERIES)}"
        )

    if spec.mode == "reporting":
        native = REPORTING_PRODUCTS.get(spec.key)
        if native is None:
            raise KeyError(f"No REPORTING_PRODUCTS entry for {spec.key!r}")
        return _sum_native_by_date(demand, frozenset({native}))

    if spec.mode == "sum":
        return _sum_native_by_date(demand, frozenset(spec.components))

    if spec.mode == "fuel_oil_scattered":
        return compute_fuel_oil_jodi_kt(demand)

    raise ValueError(f"Unsupported JODI compare mode: {spec.mode!r}")


def delivery_headline_frame(demand: pd.DataFrame) -> pd.DataFrame:
    """Filter demand rows to domestic delivery headline natives."""
    return demand.loc[demand["product_native"].isin(DELIVERY_HEADLINE_NATIVE)].copy()


def is_mase_stock_delta(product_name: str) -> bool:
    """True if ``product_name`` is a consumer stock-change row."""
    return product_name in STOCK_DELTA_NATIVE


def is_mase_delivery_excluded(product_name: str) -> bool:
    """True if row should not appear in domestic delivery headline sums."""
    return product_name in DELIVERY_EXCLUDED_NATIVE


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    from reference.dashboard_helpers import default_seasonality_chart_inputs

    return default_seasonality_chart_inputs(
        demand,
        demand_canonical,
        view=view,
        value_col=value_col,
        native_products=SEASONALITY_NATIVE_PRODUCTS,
        display_labels=DISPLAY_LABELS,
        canonical_panels=SEASONALITY_PANELS_CANONICAL,
    )


__all__ = [
    "CHART_PRODUCTS",
    "DISPLAY_LABELS",
    "MASE_AGENCY_SOURCE",
    "MASE_DATASET_SOURCE",
    "MASE_METRIC_TYPE",
    "MASE_UNIT_NATIVE",
    "REPORTING_PRODUCTS",
    "FUEL_OIL_SUBCATEGORY",
    "DELIVERY_EXCLUDED_NATIVE",
    "STOCK_DELTA_NATIVE",
    "DELIVERY_HEADLINE_NATIVE",
    "GASOIL_JODI_COMPONENTS",
    "FUEL_OIL_HEADLINE_NATIVE",
    "FUEL_OIL_BUNKER_NATIVE",
    "JodiCompareSeries",
    "JODI_COMPARE_SERIES",
    "normalize_mase_group",
    "normalize_mase_subline",
    "normalize_mase_product_name",
    "is_mase_reporting_product",
    "is_mase_stored_primary",
    "reporting_product_for_kind",
    "fuel_oil_jodi_native_labels",
    "compute_gasoil_jodi_kt",
    "compute_fuel_oil_jodi_kt",
    "compute_jodi_compare_kt",
    "delivery_headline_frame",
    "is_mase_stock_delta",
    "is_mase_delivery_excluded",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "seasonality_chart_inputs",
]
