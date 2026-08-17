"""
analytics.units
───────────────
Unit conversion for petroleum statistics.

Why this module exists
----------------------
Different national agencies report the same physical flows in different
units:

  - DCCEEW (Australia)  : ML       (megalitres,   volume)
  - PPAC (India)        : kt       (kilotonnes,   mass)
  - JODI                : kb / KL / kbd / kt  (any of the above)

A cross-country dashboard needs them in a common unit. The industry
standard for international oil-market analysis is **kbd** (thousand
barrels per day). This module is the single source of truth for the
conversion factors, so the notebooks don't each ship their own (slightly
different) hardcoded numbers.

Public API
----------
  convert(value, from_unit, to_unit, product_kind=None, date=None)
      Single-value conversion. Raises clearly for unsupported combinations.

  convert_series(s, from_unit, to_unit, product_kind=None, date=None)
      Vectorised pandas Series version.

  available_units()
      Returns the list of supported unit codes.

Notation
--------
  ML   = megalitre        = 1 000 m³        = 1 000 kL
  kL   = kilolitre        = 1 m³
  m3   = cubic metre
  kb   = thousand barrels = 1 000 bbl
  kbd  = thousand barrels per DAY  (rate; requires `date`)
  bbl/d = barrels per DAY (absolute rate; EPPO Table 2.3-4 native unit)
  kbpm = thousand barrels per calendar MONTH (KNOC product consumption;
         divide by days-in-month to get kbd)
  kt   = kilotonne (mass; requires `product_kind` for density)

Conversion factors
------------------
  Pure volume (exact):
      1 bbl = 0.158 987 m³
      => 1 m³  = 6.289 81 bbl
      => 1 ML  = 1 000 m³ = 6 289.81 bbl = 6.289 81 kb
      => 1 kL  = 1 m³     = 0.006 289 81 kb

  Mass → volume (per-product density, IEA-aligned):
      barrels per tonne, by product kind. See BBL_PER_TONNE below.

References
----------
  - IEA Energy Statistics Manual, ch. 4 (conversion factors)
  - JODI-Oil Manual, table of unit conversions
  - BP Statistical Review of World Energy, "Conversion factors"
"""
from __future__ import annotations

import calendar
from typing import Optional, Union

import pandas as pd

# --------------------------------------------------------------------------- #
#  Conversion factors
# --------------------------------------------------------------------------- #

# Pure-volume conversion: barrels per cubic metre. Source: 1 bbl = 158.987 L,
# so 1 m³ / 0.158987 = 6.28981 bbl. Five decimals is more than enough for any
# downstream rounding.
BBL_PER_M3: float = 6.28981

# Megalitres ↔ thousand barrels. 1 ML = 1000 m³ ⇒ 1 ML = 6289.81 bbl = 6.28981 kb.
KB_PER_ML: float = BBL_PER_M3  # numerically identical: 1 ML * 6.28981 = 6.28981 kb

# Kilolitres ↔ thousand barrels. 1 kL = 1 m³ ⇒ 0.00628981 kb.
KB_PER_KL: float = BBL_PER_M3 / 1000.0

# Mass → volume conversion factors. These are the IEA standard barrels-per-tonne
# values used throughout international oil statistics (BP Statistical Review,
# IEA Energy Statistics Manual, JODI). They are AVERAGE densities — any given
# barrel of crude from a specific field will differ by a few percent.
#
# Why these vary so much:
#   LPG floats — propane is ~0.50 t/m³ ⇒ many barrels per tonne (11.6).
#   Heavy fuel oil sinks toward water — ~0.97 t/m³ ⇒ few barrels per tonne (6.66).
#
# Adding a new product:
#   1. Find the IEA's "typical density" for that product (or a national stat
#      agency's published factor).
#   2. Convert to bbl/tonne: 6.28981 / density_in_t_per_m3.
#   3. Add it here and to ``reference/product_map.csv`` (Sub-category) and
#      ``analytics.products.SUBCATEGORY_TO_PRODUCT_KIND`` so the kind maps
#      from the CSV.
BBL_PER_TONNE: dict[str, float] = {
    "crude":      7.33,   # crude oil (world average)
    "condensate": 8.00,   # lighter than crude; lease condensate
    "gasoline":   8.50,   # motor gasoline (incl. aviation gasoline approx)
    "diesel":     7.46,   # diesel / gasoil
    "jet":        7.93,   # jet kerosene
    "kerosene":   7.93,   # other kerosene; similar density to jet
    "fuel_oil":   6.66,   # residual fuel oil
    "lpg":       11.60,   # LPG (mix of propane/butane)
    "naphtha":    8.90,   # naphtha
    "bitumen":    6.06,   # bitumen / asphalt
    "lubes":      7.13,   # lubricating oils & greases
    "ethanol":    7.94,   # ethanol (for ethanol-blended fuel approx)
    "other":      7.33,   # other oil products; IEA crude-oil-equivalent default
}

# Units this module knows about. Anything else raises a clear error.
_VOLUME_UNITS = {"ML", "kL", "m3", "kb", "kbpm"}
_RATE_UNITS = {"kbd", "bbl/d"}
_MASS_UNITS = {"kt", "ktoe"}
_ALL_UNITS = _VOLUME_UNITS | _RATE_UNITS | _MASS_UNITS


def available_units() -> list[str]:
    """Return the list of supported unit codes."""
    return sorted(_ALL_UNITS)


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _to_kb(
    value: Union[float, pd.Series],
    from_unit: str,
    product_kind: Optional[str],
    date: Optional[Union[pd.Timestamp, pd.Series]],
) -> Union[float, pd.Series]:
    """Step 1 of any conversion: normalise the input to kb (thousand barrels).

    kb is chosen as the pivot because every other unit has a clean
    deterministic conversion to it (volume × density factor or
    × m³ factor), and from kb we can go to any target.
    """
    if from_unit in ("kb", "kbpm"):
        # kbpm: monthly total already expressed in thousand barrels (KNOC).
        return value
    if from_unit == "ML":
        return value * KB_PER_ML
    if from_unit == "kL":
        return value * KB_PER_KL
    if from_unit == "m3":
        # 1 m³ = 1 kL, so same factor.
        return value * KB_PER_KL
    if from_unit in ("kt", "ktoe"):
        if product_kind is None:
            raise ValueError(
                "Mass→volume conversion from 'kt' requires a product_kind "
                "(e.g. 'diesel', 'gasoline'). Got product_kind=None."
            )
        factor = _bbl_per_tonne(product_kind)
        # 1 kt = 1000 tonnes; each tonne has `factor` barrels; result is in
        # bbl × 1000 = kb directly. (1 kt × factor bbl/t = 1000*factor bbl = factor kb.)
        return value * factor
    if from_unit == "kbd":
        # kbd → kb requires multiplying by days_in_month, which only makes
        # sense if we know the month. (One day's kbd ≠ one month's kb.)
        if date is None:
            raise ValueError(
                "Rate→stock conversion from 'kbd' requires a `date` so we "
                "know how many days the rate spans. Got date=None."
            )
        return value * _days_in_month(date)
    if from_unit == "bbl/d":
        # EPPO publishes absolute barrels/day; 1 kbd = 1 000 bbl/d.
        if date is None:
            raise ValueError(
                "Rate→stock conversion from 'bbl/d' requires a `date` so we "
                "know how many days the rate spans. Got date=None."
            )
        return value * _days_in_month(date) / 1000.0
    raise ValueError(
        f"Unsupported from_unit={from_unit!r}. "
        f"Supported: {sorted(_ALL_UNITS)}"
    )


def _from_kb(
    kb_value: Union[float, pd.Series],
    to_unit: str,
    product_kind: Optional[str],
    date: Optional[Union[pd.Timestamp, pd.Series]],
) -> Union[float, pd.Series]:
    """Step 2 of any conversion: go from the kb pivot to the target unit."""
    if to_unit == "kb":
        return kb_value
    if to_unit == "ML":
        return kb_value / KB_PER_ML
    if to_unit == "kL":
        return kb_value / KB_PER_KL
    if to_unit == "m3":
        return kb_value / KB_PER_KL
    if to_unit in ("kt", "ktoe"):
        if product_kind is None:
            raise ValueError(
                "Volume→mass conversion to 'kt' requires a product_kind. "
                "Got product_kind=None."
            )
        factor = _bbl_per_tonne(product_kind)
        return kb_value / factor
    if to_unit == "kbd":
        if date is None:
            raise ValueError(
                "Stock→rate conversion to 'kbd' requires a `date` so we "
                "know how many days to divide by. Got date=None."
            )
        return kb_value / _days_in_month(date)
    if to_unit == "bbl/d":
        if date is None:
            raise ValueError(
                "Stock→rate conversion to 'bbl/d' requires a `date` so we "
                "know how many days to multiply by. Got date=None."
            )
        return kb_value / _days_in_month(date) * 1000.0
    raise ValueError(
        f"Unsupported to_unit={to_unit!r}. "
        f"Supported: {sorted(_ALL_UNITS)}"
    )


def _bbl_per_tonne(product_kind: str) -> float:
    """Look up bbl/tonne for a product kind, with a clear error if missing."""
    if product_kind not in BBL_PER_TONNE:
        raise ValueError(
            f"No bbl/tonne factor for product_kind={product_kind!r}. "
            f"Known kinds: {sorted(BBL_PER_TONNE)}. "
            f"To add support, edit analytics/units.py::BBL_PER_TONNE."
        )
    return BBL_PER_TONNE[product_kind]


def _days_in_month(date: Union[pd.Timestamp, pd.Series, str]) -> Union[int, pd.Series]:
    """Days-in-month for a Timestamp or a Series of Timestamps.

    Scalar fast path lets `convert()` skip pandas overhead when the caller
    is converting a single value. The Series path lets `convert_series()`
    handle a column of dates without pulling the loop into Python.
    """
    if isinstance(date, pd.Series):
        dt = pd.to_datetime(date)
        return dt.dt.days_in_month
    ts = pd.Timestamp(date)
    return calendar.monthrange(ts.year, ts.month)[1]


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

def convert(
    value: float,
    from_unit: str,
    to_unit: str,
    product_kind: Optional[str] = None,
    date: Optional[Union[pd.Timestamp, str]] = None,
) -> float:
    """Convert a single scalar value between units.

    Parameters
    ----------
    value : float
        The numeric value to convert.
    from_unit, to_unit : str
        Source and target units. See ``available_units()``.
    product_kind : str, optional
        Required when EITHER side is a mass unit ('kt'). Example values:
        'diesel', 'gasoline', 'jet', 'kerosene', 'fuel_oil', 'lpg',
        'naphtha', 'crude', 'condensate', 'bitumen', 'lubes', 'ethanol'.
    date : pandas.Timestamp or ISO date string, optional
        Required when EITHER side is a rate unit ('kbd'). Used to look up
        days-in-month for the rate↔stock conversion.

    Returns
    -------
    float
        The converted value.

    Raises
    ------
    ValueError
        On unsupported units, or when product_kind/date are required but
        missing. Error messages tell you exactly which argument to add.

    Examples
    --------
    >>> convert(1000, "ML", "kL")
    1000000.0
    >>> round(convert(1000, "ML", "kb"), 2)
    6289.81
    >>> round(convert(1000, "ML", "kbd", date="2026-02-01"), 2)
    224.64  # 6289.81 kb / 28 days
    >>> round(convert(100, "kt", "kb", product_kind="diesel"), 2)
    746.0   # 100 kt × 7.46 bbl/t = 746 kb
    """
    if from_unit not in _ALL_UNITS:
        raise ValueError(f"Unknown from_unit={from_unit!r}")
    if to_unit not in _ALL_UNITS:
        raise ValueError(f"Unknown to_unit={to_unit!r}")
    kb = _to_kb(value, from_unit, product_kind, date)
    return _from_kb(kb, to_unit, product_kind, date)


def convert_series(
    s: pd.Series,
    from_unit: str,
    to_unit: str,
    product_kind: Optional[Union[str, pd.Series]] = None,
    date: Optional[Union[pd.Timestamp, str, pd.Series]] = None,
) -> pd.Series:
    """Vectorised version of ``convert`` for a pandas Series.

    Parameters
    ----------
    s : pandas.Series
        Numeric Series to convert.
    from_unit, to_unit : str
        Same as ``convert``.
    product_kind : str or pandas.Series, optional
        Either a single kind applied to every row, or a Series (parallel to
        ``s``) with a per-row kind. The Series form is the common case for
        a long-form DataFrame where different rows are different products.
    date : Timestamp/str or pandas.Series, optional
        Same scalar-or-Series rules as product_kind.

    Returns
    -------
    pandas.Series
        Same index as ``s``, with values converted.
    """
    # If product_kind is a per-row Series, dispatch each kind separately.
    # This is faster than .apply for typical petroleum data (5-15 distinct
    # kinds across thousands of rows) — we do one vectorised multiply per
    # kind rather than a Python call per row.
    if isinstance(product_kind, pd.Series):
        out = pd.Series(index=s.index, dtype="float64")
        # dropna=False: NaN kinds become one group (scalar None path below).
        for kind, mask in product_kind.groupby(product_kind, dropna=False):
            sub_s = s.loc[mask.index]
            sub_date = (
                date.loc[mask.index] if isinstance(date, pd.Series) else date
            )
            kind_scalar = None if pd.isna(kind) else kind
            needs_kind = (
                from_unit in _MASS_UNITS or to_unit in _MASS_UNITS
            )
            if kind_scalar is None and needs_kind:
                out.loc[mask.index] = float("nan")
                continue
            out.loc[mask.index] = convert_series(
                sub_s, from_unit, to_unit, product_kind=kind_scalar, date=sub_date,
            )
        return out

    # product_kind is now a scalar (or None). Same for date — handle the
    # per-row date case for kbd conversions where every row has its own month.
    if from_unit not in _ALL_UNITS:
        raise ValueError(f"Unknown from_unit={from_unit!r}")
    if to_unit not in _ALL_UNITS:
        raise ValueError(f"Unknown to_unit={to_unit!r}")

    kb = _to_kb(s, from_unit, product_kind, date)
    return _from_kb(kb, to_unit, product_kind, date)
