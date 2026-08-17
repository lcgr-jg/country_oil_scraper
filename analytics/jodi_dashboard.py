"""
JODI multi-product dashboard — data slices, tables, and Plotly charts.

Call ``configure(df_sec, df_pri, country_names)`` once after loading the
secondary and primary JODI parquets (and a ref_area → display-name map).
Until then, module-level helpers raise ``RuntimeError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
import plotly.colors as _pcolors
import plotly.graph_objects as go

from analytics.charts import seasonality_by_year_chart

# --------------------------------------------------------------------------- #
# Constants (from notebooks/04_jodi_explore + 05_jodi_dashboard)
# --------------------------------------------------------------------------- #

PRODUCTS_PRIMARY = {
    "CRUDEOIL": "Crude oil",
    "NGL": "Natural gas liquids",
    "OTHERCRUDE": "Other crude",
    "TOTCRUDE": "Total crude",
}

PRODUCTS_SECONDARY = {
    "LPG": "LPG",
    "NAPHTHA": "Naphtha",
    "GASOLINE": "Motor & aviation gasoline",
    "KEROSENE": "Kerosenes",
    "JETKERO": "Jet kerosene (subset of kerosenes)",
    "GASDIES": "Gas/diesel oil",
    "RESFUEL": "Residual fuel oil",
    "ONONSPEC": "Other ref products",
    "TOTPRODS": "Total ref products",
}

PRODUCT_TO_DATASET: dict[str, str] = {
    **{c: "primary" for c in PRODUCTS_PRIMARY},
    **{c: "secondary" for c in PRODUCTS_SECONDARY},
}

REGION_MAP: dict[str, str] = {
    "US": "North America",
    "CA": "North America",
    "MX": "North America",
    "BM": "North America",
    "AR": "Central and South America",
    "BB": "Central and South America",
    "BO": "Central and South America",
    "BR": "Central and South America",
    "BZ": "Central and South America",
    "CL": "Central and South America",
    "CO": "Central and South America",
    "CR": "Central and South America",
    "CU": "Central and South America",
    "DO": "Central and South America",
    "EC": "Central and South America",
    "GT": "Central and South America",
    "HN": "Central and South America",
    "HT": "Central and South America",
    "JM": "Central and South America",
    "NI": "Central and South America",
    "PA": "Central and South America",
    "PE": "Central and South America",
    "PY": "Central and South America",
    "SV": "Central and South America",
    "TT": "Central and South America",
    "UY": "Central and South America",
    "VE": "Central and South America",
    "GY": "Central and South America",
    "SR": "Central and South America",
    "AL": "Europe",
    "AT": "Europe",
    "BA": "Europe",
    "BE": "Europe",
    "BG": "Europe",
    "CH": "Europe",
    "CY": "Europe",
    "CZ": "Europe",
    "DE": "Europe",
    "DK": "Europe",
    "EE": "Europe",
    "ES": "Europe",
    "FI": "Europe",
    "FR": "Europe",
    "GB": "Europe",
    "GR": "Europe",
    "HR": "Europe",
    "HU": "Europe",
    "IE": "Europe",
    "IS": "Europe",
    "IT": "Europe",
    "LT": "Europe",
    "LU": "Europe",
    "LV": "Europe",
    "MD": "Europe",
    "ME": "Europe",
    "MK": "Europe",
    "MT": "Europe",
    "NL": "Europe",
    "NO": "Europe",
    "PL": "Europe",
    "PT": "Europe",
    "RO": "Europe",
    "RS": "Europe",
    "SE": "Europe",
    "SI": "Europe",
    "SK": "Europe",
    "TR": "Europe",
    "GI": "Europe",
    "FO": "Europe",
    "AM": "CIS",
    "AZ": "CIS",
    "BY": "CIS",
    "GE": "CIS",
    "KG": "CIS",
    "KZ": "CIS",
    "RU": "CIS",
    "TJ": "CIS",
    "TM": "CIS",
    "UA": "CIS",
    "UZ": "CIS",
    "AE": "Middle East",
    "BH": "Middle East",
    "IL": "Middle East",
    "IQ": "Middle East",
    "IR": "Middle East",
    "JO": "Middle East",
    "KW": "Middle East",
    "LB": "Middle East",
    "OM": "Middle East",
    "PS": "Middle East",
    "QA": "Middle East",
    "SA": "Middle East",
    "SY": "Middle East",
    "YE": "Middle East",
    "AO": "Africa",
    "BJ": "Africa",
    "BW": "Africa",
    "CD": "Africa",
    "CG": "Africa",
    "CI": "Africa",
    "CM": "Africa",
    "DJ": "Africa",
    "DZ": "Africa",
    "EG": "Africa",
    "ER": "Africa",
    "ET": "Africa",
    "GA": "Africa",
    "GH": "Africa",
    "GM": "Africa",
    "GN": "Africa",
    "GQ": "Africa",
    "KE": "Africa",
    "LR": "Africa",
    "LS": "Africa",
    "LY": "Africa",
    "MA": "Africa",
    "MG": "Africa",
    "ML": "Africa",
    "MR": "Africa",
    "MU": "Africa",
    "MW": "Africa",
    "MZ": "Africa",
    "NA": "Africa",
    "NE": "Africa",
    "NG": "Africa",
    "RW": "Africa",
    "SC": "Africa",
    "SD": "Africa",
    "SL": "Africa",
    "SN": "Africa",
    "SO": "Africa",
    "SS": "Africa",
    "ST": "Africa",
    "SZ": "Africa",
    "TD": "Africa",
    "TG": "Africa",
    "TN": "Africa",
    "TZ": "Africa",
    "UG": "Africa",
    "ZA": "Africa",
    "ZM": "Africa",
    "ZW": "Africa",
    "BF": "Africa",
    "BI": "Africa",
    "CF": "Africa",
    "KM": "Africa",
    "CV": "Africa",
    "CN": "China",
    "IN": "India",
    "AU": "Other Asia Pacific",
    "BD": "Other Asia Pacific",
    "BN": "Other Asia Pacific",
    "BT": "Other Asia Pacific",
    "FJ": "Other Asia Pacific",
    "HK": "Other Asia Pacific",
    "ID": "Other Asia Pacific",
    "JP": "Other Asia Pacific",
    "KH": "Other Asia Pacific",
    "KR": "Other Asia Pacific",
    "KP": "Other Asia Pacific",
    "LA": "Other Asia Pacific",
    "LK": "Other Asia Pacific",
    "MM": "Other Asia Pacific",
    "MN": "Other Asia Pacific",
    "MO": "Other Asia Pacific",
    "MV": "Other Asia Pacific",
    "MY": "Other Asia Pacific",
    "NP": "Other Asia Pacific",
    "NZ": "Other Asia Pacific",
    "PG": "Other Asia Pacific",
    "PH": "Other Asia Pacific",
    "PK": "Other Asia Pacific",
    "SG": "Other Asia Pacific",
    "TH": "Other Asia Pacific",
    "TL": "Other Asia Pacific",
    "TW": "Other Asia Pacific",
    "VN": "Other Asia Pacific",
    "AF": "Other Asia Pacific",
}

_ASIA_PACIFIC_PARTS = frozenset({"China", "India", "Other Asia Pacific"})
CONSOLIDATED_ASIA_PACIFIC = "Asia Pacific"

REGION_ORDER = [
    CONSOLIDATED_ASIA_PACIFIC,
    "China",
    "India",
    "Other Asia Pacific",
    "CIS",
    "Middle East",
    "Africa",
    "Europe",
    "Central and South America",
    "North America",
]

GLOBAL_KEY = "__GLOBAL__"
REGION_PREFIX = "__REGION__"

# Common non-ISO inputs → JODI ref_area codes
GEO_ALIASES: dict[str, str] = {
    "UK": "GB",
}

METRIC_LABELS: dict[str, str] = {
    "demand": "Demand",
    "stocks": "Ending stocks",
    "cover": "Days of forward demand cover",
}

ALL_DASHBOARD_PRODUCT_CODES: list[str] = (
    ["TOTPRODS", "TOTCRUDE"]
    + sorted(
        [c for c in PRODUCTS_SECONDARY if c != "TOTPRODS"],
        key=lambda c: PRODUCTS_SECONDARY[c].lower(),
    )
    + sorted(
        [c for c in PRODUCTS_PRIMARY if c != "TOTCRUDE"],
        key=lambda c: PRODUCTS_PRIMARY[c].lower(),
    )
)

SEASONALITY_YEARS_BACK = 6
SNAPSHOT_HISTORY_YEARS = 5
DRIVER_LAG_MONTHS = 0

SECONDARY_DEMAND_PRODUCT_CODES: list[str] = [
    c for c in ALL_DASHBOARD_PRODUCT_CODES if PRODUCT_TO_DATASET[c] == "secondary"
]

# Secondary demand basket for product-change tables (exclude parent KEROSENE).
PRODUCT_CHANGE_DEMAND_CODES: list[str] = [
    c for c in SECONDARY_DEMAND_PRODUCT_CODES if c != "KEROSENE"
]

PanelMode = Literal["totprods_anchor", "intersection", "per_product"]

_CURRENT_YEAR_COLOR = "#2ca02c"
_PREV_YEAR_COLOR = "#d62728"
_OTHER_YEAR_PALETTE = _pcolors.qualitative.Set2
_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_NOT_CONFIGURED = (
    "jodi_dashboard is not configured; call configure(df_sec, df_pri, country_names) "
    "after loading parquet."
)


def _empty_freshness_df() -> pd.DataFrame:
    """Typed empty frame so .dt accessors work on latest_date when no rows."""
    return pd.DataFrame(
        {
            "ref_area": pd.Series(dtype="string"),
            "country": pd.Series(dtype="string"),
            "latest_date": pd.Series(dtype="datetime64[ns]"),
            "peer_latest": pd.Series(dtype="datetime64[ns]"),
            "months_behind_peer": pd.Series(dtype="float64"),
            "flag_lagging": pd.Series(dtype="bool"),
        }
    )


def _product_label(product: str) -> str:
    pool = {**PRODUCTS_PRIMARY, **PRODUCTS_SECONDARY}
    return f"{pool.get(product, product)} ({product})"


product_label = _product_label


def _slice(
    dataset_df: pd.DataFrame,
    product: str,
    flow: str,
    unit: str,
    geography_codes: set[str],
) -> pd.DataFrame:
    mask = (
        (dataset_df["energy_product"] == product)
        & (dataset_df["flow_breakdown"] == flow)
        & (dataset_df["unit_measure"] == unit)
        & (dataset_df["value_status"] == "valid")
        & (dataset_df["ref_area"].astype(str).isin(geography_codes))
    )
    return dataset_df.loc[mask, ["date", "ref_area", "obs_value"]]


def _months_between(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
    if pd.isna(later) or pd.isna(earlier):
        return 999
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _prior_calendar_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _vs_5y_range_label(
    current: float,
    hist_finite: list[float],
    pct_in_range: float | None = None,
) -> str:
    if pd.isna(current) or not hist_finite:
        return "—"
    hist_min, hist_max = min(hist_finite), max(hist_finite)
    if pd.notna(hist_max) and current > hist_max:
        return "Above 5y high"
    if pd.notna(hist_min) and current < hist_min:
        return "Below 5y low"
    if pct_in_range is not None and pd.notna(pct_in_range):
        return f"{pct_in_range:.0f}% of 5y range"
    return "—"


def _year_color(year: int, current_year: int) -> str:
    if year == current_year:
        return _CURRENT_YEAR_COLOR
    if year == current_year - 1:
        return _PREV_YEAR_COLOR
    return _OTHER_YEAR_PALETTE[year % len(_OTHER_YEAR_PALETTE)]


def metric_spec(product: str, metric: str) -> dict:
    dataset = PRODUCT_TO_DATASET[product]
    demand_flow = "TOTDEMO" if dataset == "secondary" else "REFINOBS"

    if metric == "demand":
        return {
            "kind": "flow",
            "flow": demand_flow,
            "unit": "KBD",
            "y_label": "Demand (kb/d)",
        }
    if metric == "stocks":
        return {
            "kind": "level",
            "flow": "CLOSTLV",
            "unit": "KBBL",
            "y_label": "Closing stocks (million bbl)",
            "scale": 1 / 1000,
        }
    if metric == "cover":
        return {
            "kind": "ratio",
            "stocks_flow": "CLOSTLV",
            "stocks_unit": "KBBL",
            "demand_flow": demand_flow,
            "demand_unit": "KBD",
            "y_label": "Days of forward demand cover",
        }
    raise ValueError(f"Unknown metric: {metric!r} (valid: {list(METRIC_LABELS)})")


@dataclass
class _DriverBundle:
    """One-scan secondary product slice for driver decomposition."""

    geography_codes: set[str]
    monthly: pd.DataFrame
    last_obs: pd.DataFrame
    metric: str
    value_scale: float = 1.0


class JodiDashboard:
    """Stateful JODI dashboard bound to loaded parquets."""

    def __init__(
        self,
        df_sec: pd.DataFrame,
        df_pri: pd.DataFrame,
        country_names: dict[str, str],
    ) -> None:
        self.df_sec = df_sec
        self.df_pri = df_pri
        self.country_names = country_names
        self._driver_cache: dict[tuple[str, int, str], _DriverBundle] = {}
        self._series_cache: dict[tuple, pd.DataFrame] = {}

    def resolve_geography(self, geography: str) -> tuple[set[str], str]:
        if geography == GLOBAL_KEY:
            codes = (
                set(self.df_sec["ref_area"].astype(str).unique())
                | set(self.df_pri["ref_area"].astype(str).unique())
            )
            return codes, "Global Total"

        if geography.startswith(REGION_PREFIX):
            region_label = geography[len(REGION_PREFIX) :]
            if region_label == CONSOLIDATED_ASIA_PACIFIC:
                codes = {
                    iso
                    for iso, region in REGION_MAP.items()
                    if region in _ASIA_PACIFIC_PARTS
                }
                return codes, CONSOLIDATED_ASIA_PACIFIC
            codes = {
                iso for iso, region in REGION_MAP.items() if region == region_label
            }
            return codes, region_label

        code = GEO_ALIASES.get(geography, geography)
        return {code}, self.country_names.get(code, code)

    def _latest_month_per_country(
        self,
        dataset_df: pd.DataFrame,
        product: str,
        spec: dict,
        geography_codes: set[str],
    ) -> pd.DataFrame:
        codes = {str(c) for c in geography_codes}
        base = pd.DataFrame({"ref_area": sorted(codes)})

        if spec["kind"] in ("flow", "level"):
            slc = _slice(dataset_df, product, spec["flow"], spec["unit"], codes)
            if slc.empty:
                per = base.assign(latest_date=pd.NaT)
            else:
                slc = slc.copy()
                slc["ref_area"] = slc["ref_area"].astype(str)
                agg = (
                    slc.assign(date=pd.to_datetime(slc["date"]))
                    .groupby("ref_area", as_index=False)["date"]
                    .max()
                    .rename(columns={"date": "latest_date"})
                )
                per = base.merge(agg, on="ref_area", how="left")
        else:
            stocks = _slice(
                dataset_df,
                product,
                spec["stocks_flow"],
                spec["stocks_unit"],
                codes,
            )
            demand = _slice(
                dataset_df,
                product,
                spec["demand_flow"],
                spec["demand_unit"],
                codes,
            )
            if stocks.empty and demand.empty:
                per = base.assign(latest_date=pd.NaT)
            else:
                stk_max = pd.DataFrame(columns=["ref_area", "stk_max"])
                dmd_max = pd.DataFrame(columns=["ref_area", "dmd_max"])
                if not stocks.empty:
                    stocks = stocks.copy()
                    stocks["ref_area"] = stocks["ref_area"].astype(str)
                    stk_max = (
                        stocks.assign(date=pd.to_datetime(stocks["date"]))
                        .groupby("ref_area", as_index=False)["date"]
                        .max()
                        .rename(columns={"date": "stk_max"})
                    )
                if not demand.empty:
                    demand = demand.copy()
                    demand["ref_area"] = demand["ref_area"].astype(str)
                    dmd_max = (
                        demand.assign(date=pd.to_datetime(demand["date"]))
                        .groupby("ref_area", as_index=False)["date"]
                        .max()
                        .rename(columns={"date": "dmd_max"})
                    )
                merged = base.merge(stk_max, on="ref_area", how="left").merge(
                    dmd_max, on="ref_area", how="left"
                )
                merged["latest_date"] = merged.apply(
                    lambda r: (
                        min(r["stk_max"], r["dmd_max"])
                        if pd.notna(r["stk_max"]) and pd.notna(r["dmd_max"])
                        else pd.NaT
                    ),
                    axis=1,
                )
                per = merged[["ref_area", "latest_date"]]

        per["country"] = per["ref_area"].map(
            lambda c: self.country_names.get(c, c)
        )
        return per

    def assess_reporter_freshness(
        self,
        geography: str,
        product: str,
        metric: str,
        *,
        lag_months: int = 2,
    ) -> pd.DataFrame:
        geography_codes, _ = self.resolve_geography(geography)
        empty_cols = [
            "ref_area",
            "country",
            "latest_date",
            "peer_latest",
            "months_behind_peer",
            "flag_lagging",
        ]
        if len(geography_codes) <= 1:
            return _empty_freshness_df()

        spec = metric_spec(product, metric)
        dataset_df = (
            self.df_sec
            if PRODUCT_TO_DATASET[product] == "secondary"
            else self.df_pri
        )
        per = self._latest_month_per_country(
            dataset_df, product, spec, geography_codes
        )
        peer_latest = per["latest_date"].max()
        if pd.isna(peer_latest):
            per = per.copy()
            per["peer_latest"] = pd.NaT
            per["months_behind_peer"] = np.nan
            per["flag_lagging"] = False
            return per

        per = per.copy()
        per["peer_latest"] = peer_latest
        per["months_behind_peer"] = per["latest_date"].apply(
            lambda d: _months_between(peer_latest, d)
        )
        per["flag_lagging"] = per["latest_date"].isna() | (
            per["months_behind_peer"] > lag_months
        )
        return per.sort_values(
            ["flag_lagging", "months_behind_peer"],
            ascending=[False, False],
        ).reset_index(drop=True)

    def _geography_codes_for_series(
        self,
        geography: str,
        product: str,
        metric: str,
        *,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> tuple[set[str], str]:
        codes, geo_label = self.resolve_geography(geography)
        if not exclude_lagging or len(codes) <= 1:
            return codes, geo_label
        fresh = self.assess_reporter_freshness(
            geography, product, metric, lag_months=lag_months
        )
        lagging = set(fresh.loc[fresh["flag_lagging"], "ref_area"].astype(str))
        active = codes - lagging
        if lagging:
            geo_label = f"{geo_label} (excl. {len(lagging)} lagging)"
        return active, geo_label

    def get_dashboard_series(
        self,
        product: str,
        geography: str,
        metric: str,
        *,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> pd.DataFrame:
        cache_key = (
            product,
            geography,
            metric,
            exclude_lagging,
            lag_months,
        )
        if cache_key in self._series_cache:
            return self._series_cache[cache_key]

        geography_codes, _ = self._geography_codes_for_series(
            geography,
            product,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        spec = metric_spec(product, metric)
        dataset_df = (
            self.df_sec
            if PRODUCT_TO_DATASET[product] == "secondary"
            else self.df_pri
        )

        if spec["kind"] in ("flow", "level"):
            slc = _slice(
                dataset_df, product, spec["flow"], spec["unit"], geography_codes
            )
            out = slc.groupby("date", as_index=False).agg(
                value=("obs_value", "sum"),
                n_countries=("ref_area", "nunique"),
            )
            if "scale" in spec:
                out["value"] = out["value"] * spec["scale"]
            out = out.sort_values("date").reset_index(drop=True)
            self._series_cache[cache_key] = out
            return out

        stocks = _slice(
            dataset_df,
            product,
            spec["stocks_flow"],
            spec["stocks_unit"],
            geography_codes,
        )
        demand = _slice(
            dataset_df,
            product,
            spec["demand_flow"],
            spec["demand_unit"],
            geography_codes,
        )
        stk = stocks.groupby("date", as_index=False).agg(
            stocks=("obs_value", "sum"),
            n_stk=("ref_area", "nunique"),
        )
        dmd = demand.groupby("date", as_index=False).agg(
            demand=("obs_value", "sum"),
            n_dmd=("ref_area", "nunique"),
        )
        merged = stk.merge(dmd, on="date", how="inner")
        merged["value"] = np.where(
            merged["demand"] > 0, merged["stocks"] / merged["demand"], np.nan
        )
        merged["n_countries"] = merged[["n_stk", "n_dmd"]].min(axis=1)
        out = merged[["date", "value", "n_countries"]].sort_values(
            "date"
        ).reset_index(drop=True)
        self._series_cache[cache_key] = out
        return out

    def render_chart(
        self,
        product: str,
        geography: str,
        metric: str,
        *,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> go.Figure:
        df = self.get_dashboard_series(
            product,
            geography,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        spec = metric_spec(product, metric)
        _, geo_label = self._geography_codes_for_series(
            geography,
            product,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        title = (
            f"{_product_label(product)} - {METRIC_LABELS[metric]} ({geo_label})"
        )

        fig = go.Figure()
        if df.empty or df["value"].dropna().empty:
            fig.add_annotation(
                text="No data for this selection",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="grey"),
            )
            fig.update_layout(
                title=title,
                height=420,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
            )
            return fig

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["value"],
                mode="lines",
                name=spec["y_label"],
                hovertemplate="%{x|%Y-%m}<br>%{y:,.2f}<extra></extra>",
            )
        )

        if geography == GLOBAL_KEY or geography.startswith(REGION_PREFIX):
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df["n_countries"],
                    mode="lines",
                    name="# countries reporting",
                    line=dict(dash="dot"),
                    opacity=0.4,
                    yaxis="y2",
                )
            )
            fig.update_layout(
                yaxis2=dict(
                    title="# countries reporting",
                    overlaying="y",
                    side="right",
                    showgrid=False,
                ),
            )

        fig.update_layout(
            title=title,
            xaxis_title="",
            yaxis_title=spec["y_label"],
            height=480,
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.18),
        )
        return fig

    def get_all_products_series(
        self,
        geography: str,
        metric: str,
        *,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for code in ALL_DASHBOARD_PRODUCT_CODES:
            slc = self.get_dashboard_series(
                code,
                geography,
                metric,
                exclude_lagging=exclude_lagging,
                lag_months=lag_months,
            )
            if slc.empty or slc["value"].dropna().empty:
                continue
            part = slc[["date", "value"]].copy()
            part["product_native"] = _product_label(code)
            frames.append(part)
        if not frames:
            return pd.DataFrame(columns=["date", "value", "product_native"])
        return (
            pd.concat(frames, ignore_index=True)
            .sort_values(["product_native", "date"])
            .reset_index(drop=True)
        )

    @staticmethod
    def _value_at_month(df: pd.DataFrame, year: int, month: int) -> float:
        if df.empty:
            return np.nan
        work = df.copy()
        work["date"] = pd.to_datetime(work["date"])
        slc = work[
            (work["date"].dt.year == year) & (work["date"].dt.month == month)
        ]
        if slc.empty or slc["value"].dropna().empty:
            return np.nan
        return float(slc["value"].iloc[-1])

    def _default_reference_month(
        self, geography: str, metric: str = "demand"
    ) -> tuple[int, int]:
        anchor = self.get_dashboard_series("TOTPRODS", geography, metric)
        if anchor.empty:
            today = pd.Timestamp.today()
            return today.year, today.month
        anchor["date"] = pd.to_datetime(anchor["date"])
        latest = anchor["date"].max()
        return int(latest.year), int(latest.month)

    def default_reference_month(
        self, geography: str, metric: str = "demand"
    ) -> tuple[int, int]:
        return self._default_reference_month(geography, metric)

    def snapshot_month_options(
        self, geography: str
    ) -> list[tuple[str, tuple[int, int]]]:
        """Year-months with TOTPRODS demand data (newest first)."""
        anchor = self.get_dashboard_series("TOTPRODS", geography, "demand")
        if anchor.empty:
            y, m = self._default_reference_month(geography)
            return [(f"{y}-{m:02d}", (y, m))]
        anchor["date"] = pd.to_datetime(anchor["date"])
        opts = sorted(
            {(int(d.year), int(d.month)) for d in anchor["date"]},
            reverse=True,
        )
        return [(f"{y}-{m:02d}", (y, m)) for y, m in opts]

    def build_product_snapshot_tables(
        self,
        geography: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        history_years: int = SNAPSHOT_HISTORY_YEARS,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> dict[str, pd.DataFrame]:
        """Demand + stocks snapshot tables; series fetched once per product/metric."""
        return {
            metric: self.build_product_snapshot_table(
                geography,
                metric,
                reference_year=reference_year,
                reference_month=reference_month,
                history_years=history_years,
                exclude_lagging=exclude_lagging,
                lag_months=lag_months,
            )
            for metric in ("demand", "stocks")
        }

    def build_product_snapshot_table(
        self,
        geography: str,
        metric: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        history_years: int = SNAPSHOT_HISTORY_YEARS,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> pd.DataFrame:
        if reference_year is None or reference_month is None:
            reference_year, reference_month = self._default_reference_month(
                geography, metric
            )

        month_label = f"{reference_year}-{reference_month:02d}"
        hist_years = list(range(reference_year - history_years, reference_year))
        rows: list[dict] = []

        for code in ALL_DASHBOARD_PRODUCT_CODES:
            df = self.get_dashboard_series(
                code,
                geography,
                metric,
                exclude_lagging=exclude_lagging,
                lag_months=lag_months,
            )
            current = self._value_at_month(df, reference_year, reference_month)
            prior = self._value_at_month(
                df, reference_year - 1, reference_month
            )
            hist = [self._value_at_month(df, y, reference_month) for y in hist_years]
            hist_finite = [v for v in hist if pd.notna(v)]

            yoy_abs = (
                current - prior
                if pd.notna(current) and pd.notna(prior)
                else np.nan
            )
            yoy_pct = (
                (yoy_abs / prior) * 100.0
                if pd.notna(yoy_abs) and pd.notna(prior) and prior != 0
                else np.nan
            )

            if hist_finite:
                hist_min, hist_max = min(hist_finite), max(hist_finite)
                hist_median = float(np.median(hist_finite))
            else:
                hist_min = hist_max = hist_median = np.nan

            if (
                pd.notna(current)
                and pd.notna(hist_min)
                and pd.notna(hist_max)
                and hist_max > hist_min
            ):
                pct_in_range = (current - hist_min) / (hist_max - hist_min) * 100.0
            elif pd.notna(current) and pd.notna(hist_max) and current > hist_max:
                pct_in_range = 100.0
            elif pd.notna(current) and pd.notna(hist_min) and current < hist_min:
                pct_in_range = 0.0
            else:
                pct_in_range = np.nan

            vs_5y = _vs_5y_range_label(current, hist_finite, pct_in_range)

            rows.append(
                {
                    "product": _product_label(code),
                    "month": month_label,
                    "current": current,
                    "prior_year": prior,
                    "yoy_change": yoy_abs,
                    "yoy_pct": yoy_pct,
                    "hist_5y_min": hist_min,
                    "hist_5y_max": hist_max,
                    "hist_5y_median": hist_median,
                    "pct_in_5y_range": pct_in_range,
                    "vs_5y_range": vs_5y,
                }
            )

        return pd.DataFrame(rows)

    def style_product_snapshot_table(
        self, tbl: pd.DataFrame, *, value_decimals: int = 1
    ):
        if tbl.empty:
            return tbl.style
        fmt = {
            "current": f"{{:,.{value_decimals}f}}",
            "prior_year": f"{{:,.{value_decimals}f}}",
            "yoy_change": f"{{:+,.{value_decimals}f}}",
            "yoy_pct": "{:+.1f}%",
            "hist_5y_min": f"{{:,.{value_decimals}f}}",
            "hist_5y_max": f"{{:,.{value_decimals}f}}",
            "hist_5y_median": f"{{:,.{value_decimals}f}}",
            "pct_in_5y_range": "{:.0f}%",
        }
        return (
            tbl.style.format(fmt, na_rep="—")
            .set_properties(
                **{"text-align": "right"},
                subset=[
                    "current",
                    "prior_year",
                    "yoy_change",
                    "yoy_pct",
                    "hist_5y_min",
                    "hist_5y_max",
                    "hist_5y_median",
                    "pct_in_5y_range",
                ],
            )
            .set_properties(
                **{"text-align": "left"},
                subset=["product", "month", "vs_5y_range"],
            )
        )

    def _driver_flow_spec(self, metric: str) -> tuple[str, str, float]:
        if metric not in METRIC_LABELS or metric == "cover":
            raise ValueError(
                f"Driver metric must be 'demand' or 'stocks', not {metric!r}"
            )
        spec = metric_spec("TOTPRODS", metric)
        if spec["kind"] == "flow":
            return spec["flow"], spec["unit"], 1.0
        return spec["flow"], spec["unit"], float(spec.get("scale", 1.0))

    def _driver_bundle(
        self, geography: str, lag_months: int, metric: str = "demand"
    ) -> _DriverBundle:
        key = (geography, lag_months, metric)
        cached = self._driver_cache.get(key)
        if cached is not None:
            return cached

        flow, unit, value_scale = self._driver_flow_spec(metric)
        codes, _ = self.resolve_geography(geography)
        products = SECONDARY_DEMAND_PRODUCT_CODES
        mask = (
            self.df_sec["energy_product"].isin(products)
            & (self.df_sec["flow_breakdown"] == flow)
            & (self.df_sec["unit_measure"] == unit)
            & (self.df_sec["value_status"] == "valid")
            & self.df_sec["ref_area"].astype(str).isin(codes)
        )
        raw = self.df_sec.loc[
            mask, ["ref_area", "energy_product", "date", "obs_value"]
        ].copy()

        if raw.empty:
            monthly = pd.DataFrame(
                columns=[
                    "ref_area",
                    "energy_product",
                    "year",
                    "month",
                    "obs_value",
                ]
            )
            last_obs = pd.DataFrame(
                columns=["energy_product", "ref_area", "date"]
            )
        else:
            # Plain str/int columns + observed=True: categorical groupby can mis-size
            # results (30513 values vs 51000 index) on some pandas builds.
            raw = raw.reset_index(drop=True)
            raw["ref_area"] = raw["ref_area"].astype(str)
            raw["energy_product"] = raw["energy_product"].astype(str)
            raw["date"] = pd.to_datetime(raw["date"])
            raw["obs_value"] = pd.to_numeric(raw["obs_value"], errors="coerce")
            raw["year"] = raw["date"].dt.year.astype(int)
            raw["month"] = raw["date"].dt.month.astype(int)
            monthly = (
                raw.groupby(
                    ["energy_product", "ref_area", "year", "month"],
                    as_index=False,
                    observed=True,
                )
                .agg(obs_value=("obs_value", "last"))
            )
            last_obs = (
                raw.groupby(
                    ["energy_product", "ref_area"], as_index=False, observed=True
                )["date"]
                .max()
            )
            if value_scale != 1.0:
                monthly["obs_value"] = monthly["obs_value"] * value_scale

        bundle = _DriverBundle(
            geography_codes=codes,
            monthly=monthly,
            last_obs=last_obs,
            metric=metric,
            value_scale=value_scale,
        )
        self._driver_cache[key] = bundle
        return bundle

    def _freshness_from_last_obs(
        self, last_obs: pd.DataFrame, lag_months: int
    ) -> pd.DataFrame:
        empty_cols = [
            "ref_area",
            "country",
            "latest_date",
            "peer_latest",
            "months_behind_peer",
            "flag_lagging",
        ]
        if last_obs.empty:
            return _empty_freshness_df()

        per = last_obs.rename(columns={"date": "latest_date"}).copy()
        per["country"] = per["ref_area"].map(
            lambda c: self.country_names.get(c, c)
        )
        peer_latest = per["latest_date"].max()
        if pd.isna(peer_latest):
            per["peer_latest"] = pd.NaT
            per["months_behind_peer"] = np.nan
            per["flag_lagging"] = False
            return per

        per["peer_latest"] = peer_latest
        per["months_behind_peer"] = per["latest_date"].apply(
            lambda d: _months_between(peer_latest, d)
        )
        per["flag_lagging"] = per["latest_date"].isna() | (
            per["months_behind_peer"] > lag_months
        )
        return per

    def _lookup_monthly(
        self,
        bundle: _DriverBundle,
        product: str,
        ref_area: str,
        year: int,
        month: int,
    ) -> float:
        m = bundle.monthly
        if m.empty:
            return np.nan
        row = m[
            (m["energy_product"] == product)
            & (m["ref_area"] == str(ref_area))
            & (m["year"] == year)
            & (m["month"] == month)
        ]
        if row.empty or row["obs_value"].dropna().empty:
            return np.nan
        return float(row["obs_value"].iloc[-1])

    def _panel_sum_at_month(
        self,
        bundle: _DriverBundle,
        product: str,
        panel: set[str],
        year: int,
        month: int,
    ) -> float:
        if not panel:
            return np.nan
        vals = [
            self._lookup_monthly(bundle, product, code, year, month)
            for code in panel
        ]
        if any(pd.isna(v) for v in vals):
            return np.nan
        return float(sum(vals))

    def build_balanced_panel(
        self,
        geography: str,
        product: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        metric: str = "demand",
    ) -> tuple[set[str], int, int, pd.Timestamp]:
        if PRODUCT_TO_DATASET[product] != "secondary":
            raise ValueError(f"{product!r} is not a secondary product")

        bundle = self._driver_bundle(geography, lag_months, metric=metric)
        codes = bundle.geography_codes
        last_p = bundle.last_obs[bundle.last_obs["energy_product"] == product]

        if last_p.empty:
            today = pd.Timestamp.today()
            ry = reference_year or today.year
            rm = reference_month or today.month
            return set(), ry, rm, pd.NaT

        peer_latest = last_p["date"].max()
        ry = reference_year or int(peer_latest.year)
        rm = reference_month or int(peer_latest.month)
        mom_y, mom_m = _prior_calendar_month(ry, rm)

        if len(codes) <= 1:
            active = {str(c) for c in codes}
        else:
            fresh = self._freshness_from_last_obs(last_p, lag_months)
            active = set(
                fresh.loc[~fresh["flag_lagging"], "ref_area"].astype(str)
            )

        mp = bundle.monthly[bundle.monthly["energy_product"] == product]
        needed = {(ry, rm), (ry - 1, rm), (mom_y, mom_m)}
        panel: set[str] = set()
        for code in active:
            if all(
                not mp[
                    (mp["ref_area"] == str(code))
                    & (mp["year"] == y)
                    & (mp["month"] == m)
                ].empty
                and mp[
                    (mp["ref_area"] == str(code))
                    & (mp["year"] == y)
                    & (mp["month"] == m)
                ]["obs_value"]
                .notna()
                .any()
                for y, m in needed
            ):
                panel.add(str(code))

        return panel, ry, rm, peer_latest

    def build_regional_driver_summary(
        self,
        geography: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        history_years: int = SNAPSHOT_HISTORY_YEARS,
        metric: str = "demand",
    ) -> pd.DataFrame:
        bundle = self._driver_bundle(geography, lag_months, metric=metric)
        codes_all = bundle.geography_codes
        rows: list[dict] = []

        for code in SECONDARY_DEMAND_PRODUCT_CODES:
            panel, ry, rm, _peer = self.build_balanced_panel(
                geography,
                code,
                reference_year=reference_year,
                reference_month=reference_month,
                lag_months=lag_months,
                metric=metric,
            )
            excluded_n = (
                max(len(codes_all) - len(panel), 0) if len(codes_all) > 1 else 0
            )
            mom_y, mom_m = _prior_calendar_month(ry, rm)
            month_label = f"{ry}-{rm:02d}"
            hist_years_list = list(range(ry - history_years, ry))

            current = self._panel_sum_at_month(bundle, code, panel, ry, rm)
            prior_yoy = self._panel_sum_at_month(
                bundle, code, panel, ry - 1, rm
            )
            prior_mom = self._panel_sum_at_month(bundle, code, panel, mom_y, mom_m)

            yoy_abs = (
                current - prior_yoy
                if pd.notna(current) and pd.notna(prior_yoy)
                else np.nan
            )
            mom_abs = (
                current - prior_mom
                if pd.notna(current) and pd.notna(prior_mom)
                else np.nan
            )
            yoy_pct = (
                (yoy_abs / prior_yoy) * 100.0
                if pd.notna(yoy_abs) and pd.notna(prior_yoy) and prior_yoy != 0
                else np.nan
            )
            mom_pct = (
                (mom_abs / prior_mom) * 100.0
                if pd.notna(mom_abs) and pd.notna(prior_mom) and prior_mom != 0
                else np.nan
            )

            hist = [
                self._panel_sum_at_month(bundle, code, panel, y, rm)
                for y in hist_years_list
            ]
            hist_finite = [v for v in hist if pd.notna(v)]
            if hist_finite:
                hist_min, hist_max = min(hist_finite), max(hist_finite)
                hist_median = float(np.median(hist_finite))
            else:
                hist_min = hist_max = hist_median = np.nan

            if (
                pd.notna(current)
                and pd.notna(hist_min)
                and pd.notna(hist_max)
                and hist_max > hist_min
            ):
                pct_in_range = (current - hist_min) / (hist_max - hist_min) * 100.0
            elif pd.notna(current) and pd.notna(hist_max) and current > hist_max:
                pct_in_range = 100.0
            elif pd.notna(current) and pd.notna(hist_min) and current < hist_min:
                pct_in_range = 0.0
            else:
                pct_in_range = np.nan

            vs_5y = _vs_5y_range_label(current, hist_finite, pct_in_range)

            rows.append(
                {
                    "product": _product_label(code),
                    "product_code": code,
                    "metric": metric,
                    "month": month_label,
                    "level_kb_d": current,
                    "yoy_change": yoy_abs,
                    "yoy_pct": yoy_pct,
                    "mom_change": mom_abs,
                    "mom_pct": mom_pct,
                    "hist_5y_min": hist_min,
                    "hist_5y_max": hist_max,
                    "hist_5y_median": hist_median,
                    "vs_5y_range": vs_5y,
                    "panel_n": len(panel),
                    "excluded_n": excluded_n,
                }
            )

        return pd.DataFrame(rows)

    def build_common_panel(
        self,
        geography: str,
        products: list[str] | None = None,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        metric: str = "demand",
        panel_mode: PanelMode = "totprods_anchor",
    ) -> tuple[set[str], int, int, str, int]:
        """Countries used consistently across a product-change summary.

        ``totprods_anchor`` (default): balanced panel for TOTPRODS at the ref month.
        ``intersection``: reporters in every product's balanced panel at that month.
        ``per_product``: not supported here — use ``build_product_change_summary`` instead.
        """
        if panel_mode == "per_product":
            raise ValueError(
                "per_product has no single common panel; use build_product_change_summary"
            )
        product_list = list(products or PRODUCT_CHANGE_DEMAND_CODES)
        codes_all, _ = self.resolve_geography(geography)

        panel, ry, rm, _peer = self.build_balanced_panel(
            geography,
            "TOTPRODS",
            reference_year=reference_year,
            reference_month=reference_month,
            lag_months=lag_months,
            metric=metric,
        )
        if reference_year is None:
            reference_year = ry
        if reference_month is None:
            reference_month = rm

        if panel_mode == "intersection":
            common = set(panel)
            for code in product_list:
                if code == "TOTPRODS":
                    continue
                if PRODUCT_TO_DATASET.get(code) != "secondary":
                    raise ValueError(f"{code!r} is not a secondary product")
                panel_p, _, _, _ = self.build_balanced_panel(
                    geography,
                    code,
                    reference_year=reference_year,
                    reference_month=reference_month,
                    lag_months=lag_months,
                    metric=metric,
                )
                common &= panel_p
            panel = common

        excluded_n = max(len(codes_all) - len(panel), 0) if len(codes_all) > 1 else 0
        month_label = f"{reference_year}-{reference_month:02d}"
        return panel, reference_year, reference_month, month_label, excluded_n

    def build_product_change_summary(
        self,
        geography: str,
        *,
        products: list[str] | None = None,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        metric: str = "demand",
        panel_mode: PanelMode = "totprods_anchor",
        history_years: int = SNAPSHOT_HISTORY_YEARS,
    ) -> pd.DataFrame:
        """YoY/MoM demand (or stocks) by product.

        ``totprods_anchor`` / ``intersection``: one shared country panel for all rows.
        ``per_product``: each product uses its own balanced panel (diesel panel for
        diesel, jet panel for jet, etc.) — reference month may vary by product.
        """
        product_list = list(products or PRODUCT_CHANGE_DEMAND_CODES)
        bundle = self._driver_bundle(geography, lag_months, metric=metric)
        codes_all, _ = self.resolve_geography(geography)

        shared_panel: set[str] | None = None
        shared_excluded_n = 0
        shared_ry: int | None = None
        shared_rm: int | None = None

        if panel_mode in ("totprods_anchor", "intersection"):
            shared_panel, shared_ry, shared_rm, _month_label, shared_excluded_n = (
                self.build_common_panel(
                    geography,
                    product_list,
                    reference_year=reference_year,
                    reference_month=reference_month,
                    lag_months=lag_months,
                    metric=metric,
                    panel_mode=panel_mode,
                )
            )

        rows: list[dict] = []

        for code in product_list:
            if PRODUCT_TO_DATASET.get(code) != "secondary":
                raise ValueError(f"{code!r} is not a secondary product")

            if panel_mode == "per_product":
                panel, ry, rm, _peer = self.build_balanced_panel(
                    geography,
                    code,
                    reference_year=reference_year,
                    reference_month=reference_month,
                    lag_months=lag_months,
                    metric=metric,
                )
                excluded_n = (
                    max(len(codes_all) - len(panel), 0)
                    if len(codes_all) > 1
                    else 0
                )
            else:
                panel = shared_panel or set()
                ry = shared_ry if shared_ry is not None else 0
                rm = shared_rm if shared_rm is not None else 0
                excluded_n = shared_excluded_n

            month_label = f"{ry}-{rm:02d}"
            mom_y, mom_m = _prior_calendar_month(ry, rm)
            hist_years_list = list(range(ry - history_years, ry))

            current = self._panel_sum_at_month(bundle, code, panel, ry, rm)
            prior_yoy = self._panel_sum_at_month(bundle, code, panel, ry - 1, rm)
            prior_mom = self._panel_sum_at_month(bundle, code, panel, mom_y, mom_m)

            yoy_abs = (
                current - prior_yoy
                if pd.notna(current) and pd.notna(prior_yoy)
                else np.nan
            )
            mom_abs = (
                current - prior_mom
                if pd.notna(current) and pd.notna(prior_mom)
                else np.nan
            )
            yoy_pct = (
                (yoy_abs / prior_yoy) * 100.0
                if pd.notna(yoy_abs) and pd.notna(prior_yoy) and prior_yoy != 0
                else np.nan
            )
            mom_pct = (
                (mom_abs / prior_mom) * 100.0
                if pd.notna(mom_abs) and pd.notna(prior_mom) and prior_mom != 0
                else np.nan
            )

            hist = [
                self._panel_sum_at_month(bundle, code, panel, y, rm)
                for y in hist_years_list
            ]
            hist_finite = [v for v in hist if pd.notna(v)]
            if hist_finite:
                hist_min, hist_max = min(hist_finite), max(hist_finite)
                hist_median = float(np.median(hist_finite))
            else:
                hist_min = hist_max = hist_median = np.nan

            if (
                pd.notna(current)
                and pd.notna(hist_min)
                and pd.notna(hist_max)
                and hist_max > hist_min
            ):
                pct_in_range = (current - hist_min) / (hist_max - hist_min) * 100.0
            elif pd.notna(current) and pd.notna(hist_max) and current > hist_max:
                pct_in_range = 100.0
            elif pd.notna(current) and pd.notna(hist_min) and current < hist_min:
                pct_in_range = 0.0
            else:
                pct_in_range = np.nan

            vs_5y = _vs_5y_range_label(current, hist_finite, pct_in_range)

            rows.append(
                {
                    "product": _product_label(code),
                    "product_code": code,
                    "metric": metric,
                    "month": month_label,
                    "panel_mode": panel_mode,
                    "level_kb_d": current,
                    "yoy_change": yoy_abs,
                    "yoy_pct": yoy_pct,
                    "mom_change": mom_abs,
                    "mom_pct": mom_pct,
                    "hist_5y_min": hist_min,
                    "hist_5y_max": hist_max,
                    "hist_5y_median": hist_median,
                    "vs_5y_range": vs_5y,
                    "panel_n": len(panel),
                    "excluded_n": excluded_n,
                }
            )

        return pd.DataFrame(rows)

    def build_country_contribution_table(
        self,
        geography: str,
        product: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        metric: str = "demand",
    ) -> pd.DataFrame:
        if PRODUCT_TO_DATASET[product] != "secondary":
            raise ValueError(f"{product!r} is not a secondary product")

        panel, ry, rm, _peer = self.build_balanced_panel(
            geography,
            product,
            reference_year=reference_year,
            reference_month=reference_month,
            lag_months=lag_months,
            metric=metric,
        )
        if not panel:
            return pd.DataFrame()

        bundle = self._driver_bundle(geography, lag_months, metric=metric)
        mom_y, mom_m = _prior_calendar_month(ry, rm)

        rows: list[dict] = []
        for code in panel:
            cur = self._lookup_monthly(bundle, product, code, ry, rm)
            pri_y = self._lookup_monthly(bundle, product, code, ry - 1, rm)
            pri_m = self._lookup_monthly(bundle, product, code, mom_y, mom_m)
            rows.append(
                {
                    "country": self.country_names.get(code, code),
                    "ref_area": code,
                    "sub_region": REGION_MAP.get(code, "—"),
                    "level_kb_d": cur,
                    "yoy_change": cur - pri_y,
                    "mom_change": cur - pri_m,
                }
            )

        out = pd.DataFrame(rows)
        panel_yoy = out["yoy_change"].sum()
        panel_mom = out["mom_change"].sum()
        out["yoy_share_pct"] = np.where(
            panel_yoy != 0, out["yoy_change"] / panel_yoy * 100.0, np.nan
        )
        out["mom_share_pct"] = np.where(
            panel_mom != 0, out["mom_change"] / panel_mom * 100.0, np.nan
        )
        return out.sort_values("yoy_change").reset_index(drop=True)

    def build_country_product_breakdown(
        self,
        geography: str,
        ref_area: str,
        *,
        reference_year: int | None = None,
        reference_month: int | None = None,
        lag_months: int = DRIVER_LAG_MONTHS,
        metric: str = "demand",
    ) -> pd.DataFrame:
        """One country, all secondary products — mirror of build_country_contribution_table."""
        ref_area = str(GEO_ALIASES.get(ref_area, ref_area))
        bundle = self._driver_bundle(geography, lag_months, metric=metric)
        rows: list[dict] = []

        for product in SECONDARY_DEMAND_PRODUCT_CODES:
            panel, ry, rm, _peer = self.build_balanced_panel(
                geography,
                product,
                reference_year=reference_year,
                reference_month=reference_month,
                lag_months=lag_months,
                metric=metric,
            )
            if ref_area not in {str(c) for c in panel}:
                continue
            mom_y, mom_m = _prior_calendar_month(ry, rm)
            cur = self._lookup_monthly(bundle, product, ref_area, ry, rm)
            pri_y = self._lookup_monthly(bundle, product, ref_area, ry - 1, rm)
            pri_m = self._lookup_monthly(bundle, product, ref_area, mom_y, mom_m)
            rows.append(
                {
                    "product": _product_label(product),
                    "product_code": product,
                    "month": f"{ry}-{rm:02d}",
                    "level_kb_d": cur,
                    "yoy_change": cur - pri_y,
                    "mom_change": cur - pri_m,
                }
            )

        if not rows:
            return pd.DataFrame()

        out = pd.DataFrame(rows)
        country_yoy = out["yoy_change"].sum()
        country_mom = out["mom_change"].sum()
        out["yoy_share_pct"] = np.where(
            country_yoy != 0, out["yoy_change"] / country_yoy * 100.0, np.nan
        )
        out["mom_share_pct"] = np.where(
            country_mom != 0, out["mom_change"] / country_mom * 100.0, np.nan
        )
        return out.sort_values("yoy_change").reset_index(drop=True)

    def style_regional_driver_summary(
        self, tbl: pd.DataFrame, *, value_decimals: int = 0
    ):
        if tbl.empty:
            return tbl.style
        fmt = {
            "level_kb_d": f"{{:,.{value_decimals}f}}",
            "yoy_change": f"{{:+,.{value_decimals}f}}",
            "yoy_pct": "{:+.1f}%",
            "mom_change": f"{{:+,.{value_decimals}f}}",
            "mom_pct": "{:+.1f}%",
            "hist_5y_min": f"{{:,.{value_decimals}f}}",
            "hist_5y_max": f"{{:,.{value_decimals}f}}",
            "hist_5y_median": f"{{:,.{value_decimals}f}}",
            "panel_n": "{:.0f}",
            "excluded_n": "{:.0f}",
        }
        num_cols = [
            "level_kb_d",
            "yoy_change",
            "yoy_pct",
            "mom_change",
            "mom_pct",
            "hist_5y_min",
            "hist_5y_max",
            "hist_5y_median",
            "panel_n",
            "excluded_n",
        ]
        return (
            tbl.style.format(fmt, na_rep="—")
            .set_properties(**{"text-align": "right"}, subset=num_cols)
            .set_properties(
                **{"text-align": "left"},
                subset=["product", "month", "vs_5y_range"],
            )
        )

    def style_country_contribution_table(
        self, tbl: pd.DataFrame, *, value_decimals: int = 0
    ):
        if tbl.empty:
            return tbl.style
        fmt = {
            "level_kb_d": f"{{:,.{value_decimals}f}}",
            "yoy_change": f"{{:+,.{value_decimals}f}}",
            "mom_change": f"{{:+,.{value_decimals}f}}",
            "yoy_share_pct": "{:+.0f}%",
            "mom_share_pct": "{:+.0f}%",
        }
        left_cols = [
            c for c in ["country", "ref_area", "sub_region"] if c in tbl.columns
        ]
        styler = (
            tbl.style.format(fmt, na_rep="—")
            .set_properties(
                **{"text-align": "right"},
                subset=[
                    "level_kb_d",
                    "yoy_change",
                    "mom_change",
                    "yoy_share_pct",
                    "mom_share_pct",
                ],
            )
        )
        if left_cols:
            styler = styler.set_properties(
                **{"text-align": "left"}, subset=left_cols
            )
        return styler

    def render_seasonality_by_year_all_products(
        self,
        geography: str,
        metric: str,
        *,
        years_back: int = SEASONALITY_YEARS_BACK,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> go.Figure:
        _, geo_label = self._geography_codes_for_series(
            geography,
            "TOTPRODS",
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        products_ordered = [_product_label(c) for c in ALL_DASHBOARD_PRODUCT_CODES]
        df = self.get_all_products_series(
            geography,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        units = metric_spec(ALL_DASHBOARD_PRODUCT_CODES[0], metric)["y_label"]
        title = f"{METRIC_LABELS[metric]} — seasonality by calendar year ({geo_label})"

        def _empty_figure(message: str = "No data for this selection") -> go.Figure:
            fig = go.Figure()
            fig.add_annotation(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="grey"),
            )
            fig.update_layout(
                title=title,
                height=420,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
            )
            return fig

        if df.empty or df["value"].dropna().empty:
            return _empty_figure()

        work = df.copy()
        work["date"] = pd.to_datetime(work["date"])
        max_year = int(work["date"].dt.year.max())
        cutoff_year = max_year - years_back
        work = work[work["date"].dt.year >= cutoff_year]

        products_with_data = [
            p for p in products_ordered if p in set(work["product_native"])
        ]
        if not products_with_data:
            return _empty_figure()

        return seasonality_by_year_chart(
            work,
            products=products_with_data,
            value_col="value",
            date_col="date",
            product_col="product_native",
            cols=2,
            title=f"{title} ({cutoff_year}–{max_year}, latest in red)",
            units_label=units,
        )

    def render_seasonal_chart(
        self,
        product: str,
        geography: str,
        metric: str,
        selected_years: list[int] | tuple[int, ...] = (),
        history_years: int = 5,
        *,
        exclude_lagging: bool = False,
        lag_months: int = 2,
    ) -> go.Figure:
        df = self.get_dashboard_series(
            product,
            geography,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )
        wide, band, current_year = build_seasonal_frame(df, history_years=history_years)
        spec = metric_spec(product, metric)
        _, geo_label = self._geography_codes_for_series(
            geography,
            product,
            metric,
            exclude_lagging=exclude_lagging,
            lag_months=lag_months,
        )

        title = (
            f"{_product_label(product)} - {METRIC_LABELS[metric]} "
            f"({geo_label}) - seasonal"
        )

        fig = go.Figure()
        if df.empty or df["value"].dropna().empty:
            fig.add_annotation(
                text="No data for this selection",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="grey"),
            )
            fig.update_layout(
                title=title,
                height=420,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
            )
            return fig

        x = list(range(1, 13))

        if band.notna().any().any():
            band_label = f"{current_year - history_years}-{current_year - 1}"

            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=band["min"].tolist(),
                    mode="lines",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                    name="min",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=band["max"].tolist(),
                    mode="lines",
                    line=dict(width=0),
                    fill="tonexty",
                    fillcolor="rgba(150,150,150,0.18)",
                    name=f"{band_label} range",
                    hovertemplate="%{x}<br>max %{y:,.1f}<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=band["p25"].tolist(),
                    mode="lines",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                    name="p25",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=band["p75"].tolist(),
                    mode="lines",
                    line=dict(width=0),
                    fill="tonexty",
                    fillcolor="rgba(110,110,110,0.32)",
                    name=f"{band_label} p25-p75",
                    hovertemplate="%{x}<br>p75 %{y:,.1f}<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=band["median"].tolist(),
                    mode="lines",
                    line=dict(
                        color="rgba(80,80,80,0.85)", dash="dash", width=1.5
                    ),
                    name=f"{band_label} median",
                    hovertemplate="%{x}<br>median %{y:,.2f}<extra></extra>",
                )
            )

        for year in sorted(set(selected_years)):
            if year not in wide.columns:
                continue
            y_values = wide[year].tolist()
            is_focus = year in (current_year, current_year - 1)
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y_values,
                    mode="lines",
                    line=dict(
                        color=_year_color(year, current_year),
                        width=2.5 if is_focus else 1.5,
                    ),
                    name=str(year),
                    connectgaps=False,
                    hovertemplate=f"{year} %{{x}}<br>%{{y:,.2f}}<extra></extra>",
                )
            )

        fig.update_layout(
            title=title,
            xaxis=dict(
                tickmode="array",
                tickvals=x,
                ticktext=_MONTH_NAMES,
                title="",
            ),
            yaxis=dict(title=spec["y_label"]),
            height=480,
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.18),
        )
        return fig


def build_seasonal_frame(
    df: pd.DataFrame,
    history_years: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Pivot (date, value) to month×year wide table and per-month band stats."""
    if df.empty:
        empty_wide = pd.DataFrame(index=range(1, 13))
        empty_band = pd.DataFrame(
            index=range(1, 13),
            columns=["min", "p25", "median", "p75", "max"],
            dtype=float,
        )
        return empty_wide, empty_band, 0

    dates = pd.to_datetime(df["date"])
    wide = (
        pd.DataFrame(
            {
                "year": dates.dt.year,
                "month": dates.dt.month,
                "value": df["value"].values,
            }
        )
        .pivot_table(index="month", columns="year", values="value", aggfunc="sum")
        .reindex(range(1, 13))
    )

    current_year = int(wide.columns.max()) if len(wide.columns) else 0
    band_cols = sorted(
        y for y in wide.columns if current_year - history_years <= y < current_year
    )

    if band_cols:
        sample = wide[band_cols]
        band_stats = pd.DataFrame(
            {
                "min": sample.min(axis=1),
                "p25": sample.quantile(0.25, axis=1),
                "median": sample.median(axis=1),
                "p75": sample.quantile(0.75, axis=1),
                "max": sample.max(axis=1),
            }
        )
    else:
        band_stats = pd.DataFrame(
            index=range(1, 13),
            columns=["min", "p25", "median", "p75", "max"],
            dtype=float,
        )

    return wide, band_stats, current_year


# --------------------------------------------------------------------------- #
# Module context
# --------------------------------------------------------------------------- #

_ctx: JodiDashboard | None = None


def configure(
    df_sec: pd.DataFrame,
    df_pri: pd.DataFrame,
    country_names: dict[str, str],
) -> None:
    """Bind loaded parquets; must run before any dashboard helper."""
    global _ctx
    _ctx = JodiDashboard(df_sec, df_pri, country_names)


def _require_ctx() -> JodiDashboard:
    if _ctx is None:
        raise RuntimeError(_NOT_CONFIGURED)
    return _ctx


def _delegate(name: str, *args: Any, **kwargs: Any):
    return getattr(_require_ctx(), name)(*args, **kwargs)


def resolve_geography(geography: str) -> tuple[set[str], str]:
    return _delegate("resolve_geography", geography)


def assess_reporter_freshness(
    geography: str,
    product: str,
    metric: str,
    *,
    lag_months: int = 2,
) -> pd.DataFrame:
    return _delegate(
        "assess_reporter_freshness",
        geography,
        product,
        metric,
        lag_months=lag_months,
    )


def get_dashboard_series(
    product: str,
    geography: str,
    metric: str,
    *,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> pd.DataFrame:
    return _delegate(
        "get_dashboard_series",
        product,
        geography,
        metric,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def render_chart(
    product: str,
    geography: str,
    metric: str,
    *,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> go.Figure:
    return _delegate(
        "render_chart",
        product,
        geography,
        metric,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def get_all_products_series(
    geography: str,
    metric: str,
    *,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> pd.DataFrame:
    return _delegate(
        "get_all_products_series",
        geography,
        metric,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def build_product_snapshot_table(
    geography: str,
    metric: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    history_years: int = SNAPSHOT_HISTORY_YEARS,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> pd.DataFrame:
    return _delegate(
        "build_product_snapshot_table",
        geography,
        metric,
        reference_year=reference_year,
        reference_month=reference_month,
        history_years=history_years,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def build_product_snapshot_tables(
    geography: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    history_years: int = SNAPSHOT_HISTORY_YEARS,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> dict[str, pd.DataFrame]:
    return _delegate(
        "build_product_snapshot_tables",
        geography,
        reference_year=reference_year,
        reference_month=reference_month,
        history_years=history_years,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def snapshot_month_options(
    geography: str,
) -> list[tuple[str, tuple[int, int]]]:
    return _delegate("snapshot_month_options", geography)


def default_reference_month(
    geography: str, metric: str = "demand"
) -> tuple[int, int]:
    return _delegate("default_reference_month", geography, metric)


def style_product_snapshot_table(tbl: pd.DataFrame, *, value_decimals: int = 1):
    return _delegate(
        "style_product_snapshot_table", tbl, value_decimals=value_decimals
    )


def build_balanced_panel(
    geography: str,
    product: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    metric: str = "demand",
) -> tuple[set[str], int, int, pd.Timestamp]:
    return _delegate(
        "build_balanced_panel",
        geography,
        product,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        metric=metric,
    )


def build_regional_driver_summary(
    geography: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    history_years: int = SNAPSHOT_HISTORY_YEARS,
    metric: str = "demand",
) -> pd.DataFrame:
    return _delegate(
        "build_regional_driver_summary",
        geography,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        history_years=history_years,
        metric=metric,
    )


def build_country_contribution_table(
    geography: str,
    product: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    metric: str = "demand",
) -> pd.DataFrame:
    return _delegate(
        "build_country_contribution_table",
        geography,
        product,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        metric=metric,
    )


def build_country_product_breakdown(
    geography: str,
    ref_area: str,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    metric: str = "demand",
) -> pd.DataFrame:
    return _delegate(
        "build_country_product_breakdown",
        geography,
        ref_area,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        metric=metric,
    )


def style_regional_driver_summary(tbl: pd.DataFrame, *, value_decimals: int = 0):
    return _delegate(
        "style_regional_driver_summary", tbl, value_decimals=value_decimals
    )


def style_country_contribution_table(tbl: pd.DataFrame, *, value_decimals: int = 0):
    return _delegate(
        "style_country_contribution_table", tbl, value_decimals=value_decimals
    )


def render_seasonality_by_year_all_products(
    geography: str,
    metric: str,
    *,
    years_back: int = SEASONALITY_YEARS_BACK,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> go.Figure:
    return _delegate(
        "render_seasonality_by_year_all_products",
        geography,
        metric,
        years_back=years_back,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def render_seasonal_chart(
    product: str,
    geography: str,
    metric: str,
    selected_years: list[int] | tuple[int, ...] = (),
    history_years: int = 5,
    *,
    exclude_lagging: bool = False,
    lag_months: int = 2,
) -> go.Figure:
    return _delegate(
        "render_seasonal_chart",
        product,
        geography,
        metric,
        selected_years,
        history_years,
        exclude_lagging=exclude_lagging,
        lag_months=lag_months,
    )


def build_common_panel(
    geography: str,
    products: list[str] | None = None,
    *,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    metric: str = "demand",
    panel_mode: PanelMode = "totprods_anchor",
) -> tuple[set[str], int, int, str, int]:
    return _delegate(
        "build_common_panel",
        geography,
        products,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        metric=metric,
        panel_mode=panel_mode,
    )


def build_product_change_summary(
    geography: str,
    *,
    products: list[str] | None = None,
    reference_year: int | None = None,
    reference_month: int | None = None,
    lag_months: int = DRIVER_LAG_MONTHS,
    metric: str = "demand",
    panel_mode: PanelMode = "totprods_anchor",
    history_years: int = SNAPSHOT_HISTORY_YEARS,
) -> pd.DataFrame:
    return _delegate(
        "build_product_change_summary",
        geography,
        products=products,
        reference_year=reference_year,
        reference_month=reference_month,
        lag_months=lag_months,
        metric=metric,
        panel_mode=panel_mode,
        history_years=history_years,
    )


def plot_product_change_bars(
    summary: pd.DataFrame,
    *,
    title: str,
    unit: str = "kb/d",
    yoy_col: str = "yoy_change",
    mom_col: str = "mom_change",
    product_col: str = "product",
    figsize: tuple[float, float] = (14, 5),
    pos_color: str = "#2ca02c",
    neg_color: str = "#d62728",
) -> plt.Figure:
    """Side-by-side horizontal bars: YoY change | MoM change (notebook 11 style)."""
    fig, axes = plt.subplots(1, 2, figsize=figsize, sharey=True)
    for ax, col, subtitle in zip(
        axes,
        [yoy_col, mom_col],
        [f"YoY change ({unit})", f"MoM change ({unit})"],
    ):
        plot_df = summary.sort_values(col)
        colors = [
            neg_color if v < 0 else pos_color
            for v in plot_df[col].fillna(0)
        ]
        ax.barh(plot_df[product_col], plot_df[col], color=colors)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_title(subtitle)
        ax.set_xlabel(unit)
    fig.suptitle(title, y=1.02)
    fig.tight_layout()
    return fig


__all__ = [
    "PRODUCTS_PRIMARY",
    "PRODUCTS_SECONDARY",
    "PRODUCT_TO_DATASET",
    "REGION_MAP",
    "CONSOLIDATED_ASIA_PACIFIC",
    "REGION_ORDER",
    "GLOBAL_KEY",
    "REGION_PREFIX",
    "METRIC_LABELS",
    "ALL_DASHBOARD_PRODUCT_CODES",
    "SEASONALITY_YEARS_BACK",
    "SNAPSHOT_HISTORY_YEARS",
    "DRIVER_LAG_MONTHS",
    "SECONDARY_DEMAND_PRODUCT_CODES",
    "PRODUCT_CHANGE_DEMAND_CODES",
    "PanelMode",
    "JodiDashboard",
    "configure",
    "metric_spec",
    "product_label",
    "resolve_geography",
    "assess_reporter_freshness",
    "get_dashboard_series",
    "render_chart",
    "get_all_products_series",
    "build_seasonal_frame",
    "render_seasonal_chart",
    "build_product_snapshot_table",
    "build_product_snapshot_tables",
    "snapshot_month_options",
    "default_reference_month",
    "style_product_snapshot_table",
    "build_balanced_panel",
    "build_regional_driver_summary",
    "build_common_panel",
    "build_product_change_summary",
    "plot_product_change_bars",
    "build_country_contribution_table",
    "build_country_product_breakdown",
    "style_regional_driver_summary",
    "style_country_contribution_table",
    "render_seasonality_by_year_all_products",
]
