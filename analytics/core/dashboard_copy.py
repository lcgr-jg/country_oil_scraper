"""
User-facing captions for the Streamlit demand dashboard.

Country-specific notes live here; reference modules may override via
``JODI_COMPARE_CAPTION`` / ``SEASONALITY_CAPTION`` / ``KAYRROS_JET_CAPTION``.
"""

from __future__ import annotations

from typing import Any

_DEFAULT_JODI = (
    "Both series are TOTDEMO in kbd. Level gaps often reflect coverage "
    "(bunkers, refinery fuel) or product definitions — not necessarily errors."
)

_DEFAULT_KAYRROS = (
    "Kayrros tracks in-flight burn; official stats report product sales or "
    "deliveries. Expect a structural level gap — use for trend sanity checks."
)

_DEFAULT_SEASONALITY = (
    "Each line is one calendar year (Jan–Dec). The bold red line is the latest "
    "year; compare its shape to prior years to spot seasonal anomalies."
)

_JODI_BY_COUNTRY: dict[str, str] = {
    "india": (
        "PPAC reports inland POL consumption; JODI TOTDEMO also includes bunkers "
        "and refinery fuel, so JODI is often higher. SKO is compared to JODI "
        "X_OTHKERO (total kerosene minus jet). The Other products panel sums "
        "PPAC lines that map to JODI ONONSPEC."
    ),
    "thailand": (
        "EPPO kerosene rolls up J.P. (jet) and KEROSENE to match JODI's parent "
        "KEROSENE aggregate. Gasoline sums REGULAR + PREMIUM. Both sides in kbd."
    ),
    "australia": (
        "DCCEEW uses headline native totals (e.g. Diesel oil: total). JODI side "
        "is KBD from the secondary parquet. Volumes are comparable in kbd after "
        "warehouse conversion from DCCEEW megalitres."
    ),
    "italy": (
        "MASE domestic delivery vs JODI TOTDEMO. Fuel oil on the MASE side uses "
        "the scattered industrial/bunker adapter; gasoil/diesel may not map 1:1 "
        "to JODI GASDIES without the notebook rollups."
    ),
    "norway": (
        "Kerosene panel: JODI X_OTHKERO (non-jet) vs official heating kerosene "
        "(jet kept separate). Diesel includes auto and marine gasoil natives."
    ),
    "uk": (
        "DESNZ consumption vs JODI. 'Other products' on the official side is a "
        "derived residual — treat level gaps cautiously."
    ),
    "japan": (
        "METI domestic sales (kL converted to kbd) vs JODI. Naphtha and petchem "
        "feedstocks are included in METI headline totals but not in all JODI panels."
    ),
    "korea": (
        "KNOC product consumption vs JODI. Korea maps native CSV columns directly "
        "to JODI product codes."
    ),
}

_KAYRROS_BY_COUNTRY: dict[str, str] = {
    "thailand": (
        "Kayrros: jet burned on departures from Thailand. EPPO J.P.: jet fuel "
        "sold/delivered (Table 2.3-4). Sales exceed burn; trends should still align."
    ),
    "australia": (
        "Kayrros: domestic + international departures from Australia. DCCEEW: "
        "aviation turbine fuel total (domestic + international sales)."
    ),
}

_SEASONALITY_BY_COUNTRY: dict[str, str] = {
    "thailand": (
        "Observed EPPO months only (provisional Q1 2025 imputations excluded). "
        "LSD omitted — subsumed in HSD for seasonality."
    ),
    "australia": "Last seven calendar years shown to keep the chart readable.",
    "italy": "Includes MASE preliminary months — they carry the timely signal.",
    "india": "PPAC fiscal-year reporting; calendar dates are assigned in the processor.",
}


def _ref_caption(ref_mod: Any | None, attr: str) -> str | None:
    if ref_mod is None:
        return None
    val = getattr(ref_mod, attr, None)
    return str(val).strip() if val else None


def jodi_compare_caption(country_id: str, ref_mod: Any | None = None) -> str:
    return _ref_caption(ref_mod, "JODI_COMPARE_CAPTION") or _JODI_BY_COUNTRY.get(
        country_id, _DEFAULT_JODI
    )


def kayrros_jet_caption(country_id: str, ref_mod: Any | None = None) -> str:
    return _ref_caption(ref_mod, "KAYRROS_JET_CAPTION") or _KAYRROS_BY_COUNTRY.get(
        country_id, _DEFAULT_KAYRROS
    )


def seasonality_caption(country_id: str, ref_mod: Any | None = None) -> str:
    extra = _ref_caption(ref_mod, "SEASONALITY_CAPTION") or _SEASONALITY_BY_COUNTRY.get(
        country_id
    )
    if extra:
        return f"{_DEFAULT_SEASONALITY} {extra}"
    return _DEFAULT_SEASONALITY


__all__ = [
    "jodi_compare_caption",
    "kayrros_jet_caption",
    "seasonality_caption",
]
