"""
Processor for the JODI-Oil World Database (primary & secondary).

Mirrors the shape of ``processors.india_pt_consumption`` so the pipeline
patterns (build_from_historical → upsert → save → load) feel identical
across data sources.

Scale notes
-----------
JODI-Secondary across 2002-current is ~100M rows. We:
  * read year-by-year and concat once (peak memory is ~3-4 GB pandas-side)
  * convert string columns to ``category`` dtype after concat (huge size win)
  * write Parquet with snappy compression for Snowflake-friendly columnar
    storage, AND a SQLite mirror for ad-hoc SQL queries.

Country enrichment
------------------
``REF_AREA`` is JODI's ISO alpha-2 code. We left-join the workbook at
``reference/country_codes.xlsx`` to attach an English country name. Codes
that don't match (e.g. JODI aggregates like 'WORLD', 'OECD') simply get
NaN — that's a feature, not a bug.

Derived product: X_OTHKERO (non-jet kerosene)
---------------------------------------------
JODI's ``KEROSENE`` row is a parent aggregate that already includes
``JETKERO``. To get a non-overlapping kerosene/jet split for cross-source
comparison we emit a derived product ``X_OTHKERO = KEROSENE - JETKERO``
inside ``derive_x_othkero``. Derived rows carry ``value_status='derived'``
so downstream queries can include or exclude them by provenance. KEROSENE
and JETKERO themselves are kept untouched for source fidelity. The
pipeline calls the derivation automatically:
  * ``build_from_historical`` rebuilds X_OTHKERO from scratch.
  * ``upsert`` does an incremental refresh of only the (date, country,
    flow, unit) keys touched by the new file. Pass ``recompute_derived=True``
    to force a full rebuild.

Phase 4c additions (2026-05) — see reference/loaders.py:
    The output schema now carries three canonical columns derived from
    reference/product_map.csv and reference/metric_types.yaml:

        product_canonical : Sub-category (e.g. GASDIES -> "Diesel")
        category          : Category     (e.g. GASDIES -> "Distillates")
        metric_type       : Canonical metric code from metric_types.yaml
                            (== flow_breakdown for JODI; identity mapping)

    Asymmetry by design:
      * SECONDARY rows get all three canonical columns populated.
      * PRIMARY rows get only `metric_type` populated; `product_canonical`
        and `category` stay NaN because crude (CRUDEOIL/NGL/OTHERCRUDE/
        TOTCRUDE) is NOT mapped in product_map.csv — the project scope
        is petroleum *products*. Use
            df[df['product_canonical'].notna()]
        or
            df[df['dataset'] == 'secondary']
        to scope queries to the product side.

    The schema is the SAME 18 columns for both parquets (the two
    product columns just stay NaN in primary) so cross-dataset UNION ALL
    is trivial.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

# Reference loaders are imported at module level: they cache the CSV/YAML
# read on first call, so importing here is cheap and gives us one place
# to see all reference-data wiring.
from reference.loaders import (
    canonical_category,
    canonical_metric,
    canonical_subcategory,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Phase 4c reference-data wiring
# --------------------------------------------------------------------------- #

# Source key into product_map.csv (agency-level). Used only for SECONDARY
# rows; primary rows skip product canonicalisation by design.
_PRODUCT_MAP_SOURCE = "JODI"

# Dataset-level source keys into metric_types.yaml -> source_mappings.
# Each maps the JODI native flow_breakdown to a canonical metric_type
# (identity mapping in practice, but listed explicitly in the YAML so
# completeness can be validated by the loader).
_METRIC_SOURCE_BY_DATASET = {
    "primary":   "jodi_primary",
    "secondary": "jodi_secondary",
}

# Canonical column order. Date-first so multi-source joins stay natural.
# Phase 4c adds three columns; they slot next to the related native column
# so the schema reads in pairs: (native, canonical) × (product, metric).
COLUMN_ORDER = [
    "date",
    "year",
    "month",
    "ref_area",
    "country_name",
    "energy_product",          # native JODI code (e.g. "GASDIES")
    "product_canonical",       # Phase 4c: Sub-category from product_map.csv
                               #           (NaN for primary by design)
    "category",                # Phase 4c: Category from product_map.csv
                               #           (NaN for primary by design)
    "flow_breakdown",          # native JODI code (e.g. "TOTDEMO")
    "metric_type",             # Phase 4c: canonical metric code from
                               #           metric_types.yaml (identity)
    "unit_measure",
    "obs_value",
    "value_status",
    "assessment_code",
    "assessment_label",
    "dataset",
    "source_file",
    "updated_at",
]

# Natural key uniquely identifying one observation. We deliberately include
# unit_measure because JODI publishes the same observation in multiple units
# (e.g. KBBL, KBD, KTONS) and they're all valid distinct rows.
KEY_COLS = [
    "date", "ref_area", "energy_product", "flow_breakdown", "unit_measure",
]

# Subset of COLUMN_ORDER that benefits massively from the categorical dtype.
# Doing this after the cross-year concat is critical: each year's CSV uses
# a different subset of categories. Phase 4c-added columns are appended
# here so the new low-cardinality string columns also benefit from
# categorical compression at 15M+ rows.
_CATEGORICAL_COLS = [
    "ref_area", "country_name",
    "energy_product", "flow_breakdown", "unit_measure",
    "value_status", "assessment_label",
    "dataset", "source_file",
    # Phase 4c additions:
    "product_canonical", "category", "metric_type",
]


# --------------------------------------------------------------------------- #
#  Bootstrap: build the full historical DB from local CSVs
# --------------------------------------------------------------------------- #

def build_from_historical(
    raw_jodi_dir: Path,
    dataset_name: str,
    country_codes_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Walk every JODI annual CSV under ``raw_jodi_dir`` for the given dataset
    and return a single tidy DataFrame.

    Search strategy (deduplicates by year, latest mtime wins):
        - <raw_jodi_dir>/<dataset>/*.csv          (canonical, going forward)
        - <raw_jodi_dir>/<dataset>_jodi/*.csv     (legacy bootstrap layout)
        - <raw_jodi_dir>/<dataset>year*.csv       (root-level YTD files)

    Args:
        raw_jodi_dir:        e.g. ``data/raw/jodi``.
        dataset_name:        'secondary' or 'primary'.
        country_codes_path:  Optional path to country_codes.xlsx for the
                             country-name enrichment.

    Returns:
        A tidy DataFrame ready to be persisted by ``save()``.
    """
    raw_jodi_dir = Path(raw_jodi_dir)
    files_by_year = _discover_csv_files(raw_jodi_dir, dataset_name)
    if not files_by_year:
        raise FileNotFoundError(
            f"No JODI {dataset_name} CSVs found under {raw_jodi_dir}. "
            f"Expected files in <{dataset_name}/>, <{dataset_name}_jodi/>, "
            f"or named '{dataset_name}year*.csv' at the root."
        )
    logger.info(
        f"Bootstrap [{dataset_name}]: {len(files_by_year)} files "
        f"({min(files_by_year)}-{max(files_by_year)})"
    )
    df = _parse_and_concat(
        files_by_year.values(),
        dataset_name=dataset_name,
        country_codes_path=country_codes_path,
    )

    # On a fresh bootstrap of the secondary dataset, derive the X_OTHKERO
    # (non-jet kerosene) rows from scratch. KEROSENE/JETKERO only appear in
    # secondary, so primary doesn't need this step. See `derive_x_othkero`
    # for the rationale (avoiding double-counting jet across canonical
    # Sub-categories).
    if dataset_name == "secondary":
        df = derive_x_othkero(df, only_for_keys=None)
        df = _sort_and_clean(df)

    return df


# --------------------------------------------------------------------------- #
#  Upsert: merge a freshly-parsed DataFrame into the existing DB
# --------------------------------------------------------------------------- #

def upsert(
    existing_df: Optional[pd.DataFrame],
    new_df: pd.DataFrame,
    *,
    recompute_derived: bool = False,
) -> pd.DataFrame:
    """
    Merge new observations into the existing database.

    For each natural-key tuple appearing in ``new_df``:
      - If it already exists in ``existing_df``, replace with the new value.
      - Otherwise, append it.

    Re-downloading the current year's file therefore overwrites provisional
    figures month-by-month while leaving older years untouched.

    Derived X_OTHKERO maintenance
    -----------------------------
    KEROSENE/JETKERO live in the secondary dataset and have a derived
    companion X_OTHKERO = KEROSENE - JETKERO (see ``derive_x_othkero`` for
    rationale). After the upsert, this function refreshes the derived rows:

      - ``recompute_derived=False`` (default) -> *incremental*: re-derive
        only for the (date, ref_area, flow, unit) keys present in
        ``new_df`` where energy_product is KEROSENE or JETKERO. Cheap and
        covers JODI's normal monthly-revision pattern (revised parents
        always show up in the new file).

      - ``recompute_derived=True`` -> *full rebuild*: drop every X_OTHKERO
        row in the combined dataframe and re-derive from current parents.
        Use after changing the derivation rule, fixing a bug, or when you
        suspect drift (e.g. JODI restated old years that you didn't
        re-download).

    Args:
        existing_df:      Current state. Pass ``None`` on first upsert.
        new_df:           Freshly-parsed rows to merge in.
        recompute_derived:
                          See above. Default is incremental.
    """
    if existing_df is None or existing_df.empty:
        combined = _sort_and_clean(new_df)
    else:
        # Multi-column anti-join: build a frozen-set membership index over
        # the new key tuples, then drop matching rows from existing in one
        # pass. Dramatically faster than .apply() row-wise for ~100M-row
        # tables.
        new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
        existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLS])
        keep_mask = ~existing_keys.isin(new_keys)

        combined = pd.concat(
            [existing_df.loc[keep_mask], new_df],
            ignore_index=True,
        )
        combined = _sort_and_clean(combined)

    # ------------------------------------------------------------------- #
    # X_OTHKERO maintenance. Only relevant when the combined frame contains
    # secondary rows; primary has no KEROSENE/JETKERO to derive from.
    # ------------------------------------------------------------------- #
    has_secondary = (
        "dataset" in combined.columns
        and (combined["dataset"].astype(str) == "secondary").any()
    )
    if has_secondary:
        # On the first-upsert path (no existing_df) we must always do a full
        # rebuild because there are no derived rows to incrementally update.
        full_rebuild = recompute_derived or existing_df is None or existing_df.empty

        if full_rebuild:
            combined = derive_x_othkero(combined, only_for_keys=None)
        else:
            kero_in_new = new_df[
                new_df["energy_product"].astype(str).isin(["KEROSENE", "JETKERO"])
            ]
            if not kero_in_new.empty:
                keys = (
                    kero_in_new[_OTHKERO_KEY_COLS]
                    .drop_duplicates()
                    .reset_index(drop=True)
                )
                combined = derive_x_othkero(combined, only_for_keys=keys)
            # else: no KEROSENE/JETKERO in new_df → derived rows untouched.

        combined = _sort_and_clean(combined)

    return combined


# --------------------------------------------------------------------------- #
#  Persistence
# --------------------------------------------------------------------------- #

def save(
    df: pd.DataFrame,
    output_dir: Path,
    dataset_name: str,
    write_sqlite: bool = False,
) -> dict[str, Path]:
    """
    Persist the database for one dataset.

    Default output is parquet only. The SQLite mirror is opt-in via
    ``write_sqlite=True`` — we stopped writing it by default because the
    project's notebooks load via ``pd.read_parquet`` and nobody was
    querying the .db file. Re-enable when you need ad-hoc SQL access.

      1. Parquet — ``jodi_<dataset>.parquet`` (always written)
         Snappy-compressed, Snowflake ``COPY INTO``-ready.
      2. SQLite  — ``jodi_<dataset>.db`` (only if ``write_sqlite=True``)
         Table ``jodi_<dataset>``, indexed on (date, ref_area),
         (energy_product), and (flow_breakdown).

    Args:
        df:            Tidy DataFrame to save.
        output_dir:    Destination directory (created if missing).
        dataset_name:  'secondary' or 'primary'.
        write_sqlite:  Opt in to writing the SQLite mirror. Default False.

    Returns:
        Dict with key 'parquet' (always) and 'sqlite' (only when enabled).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / f"jodi_{dataset_name}.parquet"
    sqlite_path = output_dir / f"jodi_{dataset_name}.db"

    # -- Parquet ---------------------------------------------------- #
    df_pq = df.copy()
    df_pq["date"] = pd.to_datetime(df_pq["date"])
    df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    size_mb = parquet_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved parquet: {parquet_path} ({size_mb:,.1f} MB)")

    paths = {"parquet": parquet_path}

    # -- SQLite ----------------------------------------------------- #
    if write_sqlite:
        df_sql = df.copy()
        # SQLite has no native DATE/TIMESTAMP — store as ISO strings
        df_sql["date"] = pd.to_datetime(df_sql["date"]).dt.strftime("%Y-%m-%d")
        df_sql["updated_at"] = pd.to_datetime(df_sql["updated_at"]).astype(str)
        # Categories must be cast back to strings for sqlite3.
        for col in _CATEGORICAL_COLS:
            if col in df_sql.columns:
                df_sql[col] = df_sql[col].astype(str)

        table_name = f"jodi_{dataset_name}"
        with sqlite3.connect(sqlite_path) as conn:
            # method=None (default) uses executemany under the hood, which
            # avoids SQLite's 32,766-bound-parameter cap that 'multi' hits
            # on 15-column tables with chunksize > ~2000. Throughput on
            # 15M rows is still ~1-2 minutes.
            df_sql.to_sql(
                table_name, conn,
                if_exists="replace",
                index=False,
                chunksize=50_000,
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date_ref "
                f"ON {table_name} (date, ref_area)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_product "
                f"ON {table_name} (energy_product)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_flow "
                f"ON {table_name} (flow_breakdown)"
            )
        size_mb = sqlite_path.stat().st_size / (1024 * 1024)
        logger.info(f"Saved SQLite: {sqlite_path} ({size_mb:,.1f} MB)")
        paths["sqlite"] = sqlite_path

    return paths


def load(output_dir: Path, dataset_name: str) -> Optional[pd.DataFrame]:
    """Load the existing parquet for one dataset, or None if it doesn't exist."""
    parquet_path = Path(output_dir) / f"jodi_{dataset_name}.parquet"
    if not parquet_path.exists():
        logger.info(
            f"No existing JODI {dataset_name} DB found at {parquet_path} "
            f"— will build from scratch."
        )
        return None
    df = pd.read_parquet(parquet_path)
    logger.info(
        f"Loaded JODI {dataset_name} DB: {len(df):,} rows "
        f"({df['date'].min()} → {df['date'].max()})"
    )
    return df


# --------------------------------------------------------------------------- #
#  Derived products
# --------------------------------------------------------------------------- #

# Keys at which X_OTHKERO is derivable: one obs per (date, country, flow, unit).
# energy_product is *not* part of the key because the whole point of the
# pivot is to put KEROSENE and JETKERO side-by-side as columns.
_OTHKERO_KEY_COLS = ["date", "ref_area", "flow_breakdown", "unit_measure"]


def derive_x_othkero(
    df: pd.DataFrame,
    only_for_keys: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Derive ``X_OTHKERO = KEROSENE - JETKERO`` and return the dataframe with
    the derived rows inserted or refreshed.

    Why this exists
    ---------------
    In JODI's hierarchy, ``KEROSENE`` is a *parent* aggregate that already
    includes ``JETKERO`` (jet kerosene). Treating KEROSENE and JETKERO as
    two independent rows for cross-source comparison double-counts jet
    when one sums by canonical Sub-category. ``X_OTHKERO`` ("other
    kerosene", i.e. non-jet) is the project-derived complement so the
    canonical Sub-category split becomes non-overlapping:

        Sub-category 'Kerosene' = X_OTHKERO   (non-jet, derived)
        Sub-category 'Jet Fuel' = JETKERO     (JODI-native)
        KEROSENE itself        = aggregate kept for source fidelity but
                                  excluded from cross-source sums
                                  (see reference/product_map.csv).

    Provenance markers on derived rows
    ----------------------------------
    Derived rows are tagged so downstream queries can filter them in or out:
        value_status      = 'derived'
        assessment_label  = 'derived'
        assessment_code   = NA       (no JODI assessment applies)
        source_file       = '<derived>'

    Edge cases
    ----------
        - Only one parent present for a key  -> X_OTHKERO not emitted.
        - KEROSENE < JETKERO (negative diff) -> clamp to 0, log warning.
          Almost always a JODI revision / rounding artefact.
        - KEROSENE == JETKERO                -> emit X_OTHKERO = 0 (valid:
          country reports only jet kerosene).

    Args:
        df:
            Tidy JODI dataframe. May already contain X_OTHKERO rows.
        only_for_keys:
            ``None`` -> *full rebuild*. Drop all existing X_OTHKERO rows
                        and re-derive from every key where both parents
                        are present. Use on bootstrap, after a derivation
                        rule change, or when you want to force a refresh.
            ``DataFrame`` with at least the columns ``date``, ``ref_area``,
                        ``flow_breakdown``, ``unit_measure`` -> *incremental*.
                        Drop and re-derive X_OTHKERO only for the listed
                        keys. Other existing X_OTHKERO rows stay intact.
                        Use during routine upserts.

    Returns:
        A *new* dataframe with X_OTHKERO rows inserted/refreshed. The input
        is not mutated. Categorical dtypes on the standard columns are
        preserved (the function temporarily casts them to object internally
        so concat doesn't choke on the new 'X_OTHKERO' / 'derived' values).

    Notes:
        The function does NOT sort the output. Callers that need a sorted,
        fully-typed result should pass the return value through
        ``_sort_and_clean()``. The pipeline functions
        (``build_from_historical``, ``upsert``) already do this.
    """
    if df.empty:
        return df.copy()

    # Bail early on an empty incremental scope: nothing to drop, nothing to add.
    if only_for_keys is not None and only_for_keys.empty:
        return df.copy()

    # Categorical dtypes can't accept previously-unseen labels through concat,
    # so we cast back to object for the duration of this function and restore
    # category dtype on the way out.
    work = df.copy()
    was_categorical = {}
    for col in _CATEGORICAL_COLS:
        if col in work.columns and isinstance(work[col].dtype, pd.CategoricalDtype):
            was_categorical[col] = True
            work[col] = work[col].astype(object)

    # ------------------------------------------------------------------- #
    # 1. Scope the parents we'll derive from, and decide which existing
    #    X_OTHKERO rows we'll drop (so re-deriving them is a clean replace).
    # ------------------------------------------------------------------- #
    parents = work[work["energy_product"].isin(["KEROSENE", "JETKERO"])]

    if only_for_keys is not None:
        # Incremental path: limit to the specified keys.
        scope_idx = pd.MultiIndex.from_frame(only_for_keys[_OTHKERO_KEY_COLS])
        if not parents.empty:
            parent_idx = pd.MultiIndex.from_frame(parents[_OTHKERO_KEY_COLS])
            parents = parents.loc[parent_idx.isin(scope_idx)]
        # Drop only the X_OTHKERO rows whose keys are in scope.
        existing_x = work[work["energy_product"] == "X_OTHKERO"]
        if not existing_x.empty:
            existing_idx = pd.MultiIndex.from_frame(existing_x[_OTHKERO_KEY_COLS])
            drop_idx = existing_x.index[existing_idx.isin(scope_idx)]
            work = work.drop(drop_idx)
    else:
        # Full rebuild: drop every X_OTHKERO row currently present.
        work = work[work["energy_product"] != "X_OTHKERO"]

    if parents.empty:
        logger.info("derive_x_othkero: no KEROSENE/JETKERO in scope; nothing to derive.")
        return _to_categorical(work, was_categorical)

    # ------------------------------------------------------------------- #
    # 2. Pivot the two parent products into columns so the subtraction is
    #    a single vectorised operation across (date, area, flow, unit).
    # ------------------------------------------------------------------- #
    wide = parents.pivot_table(
        index=_OTHKERO_KEY_COLS,
        columns="energy_product",
        values="obs_value",
        aggfunc="first",
    ).reset_index()

    if "KEROSENE" not in wide.columns or "JETKERO" not in wide.columns:
        logger.info(
            "derive_x_othkero: scope missing one of (KEROSENE, JETKERO); "
            "nothing to derive."
        )
        return _to_categorical(work, was_categorical)

    both = wide["KEROSENE"].notna() & wide["JETKERO"].notna()
    n_missing_parent = int((~both).sum())
    derived = wide.loc[both, _OTHKERO_KEY_COLS + ["KEROSENE", "JETKERO"]].copy()

    if derived.empty:
        logger.info(
            f"derive_x_othkero: no key had both parents present "
            f"({n_missing_parent} key(s) skipped). No X_OTHKERO rows emitted."
        )
        return _to_categorical(work, was_categorical)

    # ------------------------------------------------------------------- #
    # 3. Compute KEROSENE - JETKERO. Clamp negatives to 0 (almost always
    #    a rounding/revision artefact) and log the count so audits are easy.
    # ------------------------------------------------------------------- #
    diff = derived["KEROSENE"] - derived["JETKERO"]
    n_negative = int((diff < 0).sum())
    if n_negative:
        logger.warning(
            f"derive_x_othkero: {n_negative} key(s) had KEROSENE < JETKERO. "
            f"Clamping X_OTHKERO to 0 (likely JODI revision/rounding artefact)."
        )
    derived["obs_value"] = diff.clip(lower=0)

    # ------------------------------------------------------------------- #
    # 4. Fill in the rest of the row metadata. country_name is the only
    #    field that needs to be looked up from the parents (it's a function
    #    of ref_area, not of date/flow/unit).
    # ------------------------------------------------------------------- #
    cn_map = (
        parents[["ref_area", "country_name"]]
        .drop_duplicates("ref_area")
        .set_index("ref_area")["country_name"]
        .to_dict()
    )
    derived["country_name"] = derived["ref_area"].map(cn_map)

    dt = pd.to_datetime(derived["date"])
    derived["year"] = dt.dt.year.astype("Int16")
    derived["month"] = dt.dt.month.astype("Int8")
    derived["energy_product"] = "X_OTHKERO"
    derived["value_status"] = "derived"
    # Build assessment_code as a typed all-NA Int8 Series rather than a bare
    # pd.NA scalar. The scalar form would create an object-dtype column, which
    # triggers a pandas FutureWarning at concat time about all-NA columns
    # changing dtype-inference behaviour. Typed-NA avoids that entirely.
    derived["assessment_code"] = pd.array([pd.NA] * len(derived), dtype="Int8")
    derived["assessment_label"] = "derived"
    # KEROSENE/JETKERO only live in the secondary dataset, so derived rows
    # always belong there too.
    derived["dataset"] = "secondary"
    derived["source_file"] = "<derived>"
    # Use naive local-time timestamp to match scrapers/jodi.py:217. Earlier
    # iterations used pd.Timestamp.utcnow() which returns a tz-aware value;
    # mixing aware+naive timestamps in a single column trips up the
    # pd.to_datetime() call in save() when writing the SQLite mirror.
    derived["updated_at"] = pd.Timestamp.now()

    # ------------------------------------------------------------------- #
    # 5. Append in canonical column order and restore categorical dtypes.
    # ------------------------------------------------------------------- #
    # Phase 4c columns (product_canonical, category, metric_type) aren't
    # populated here — upsert's trailing _sort_and_clean() fills them via
    # _derive_canonical_columns. Pad with NA so COLUMN_ORDER selection works.
    for col in COLUMN_ORDER:
        if col not in derived.columns:
            derived[col] = pd.NA
    derived_out = derived[COLUMN_ORDER]
    out = pd.concat([work, derived_out], ignore_index=True)

    logger.info(
        f"derive_x_othkero: emitted {len(derived_out):,} X_OTHKERO row(s) "
        f"({n_missing_parent} skipped for missing parent; "
        f"{n_negative} clamped to 0)."
    )

    return _to_categorical(out, was_categorical)


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _discover_csv_files(raw_jodi_dir: Path, dataset_name: str) -> dict[int, Path]:
    """
    Locate one CSV per calendar year for the given dataset.

    Returns a {year: path} dict. When the same year is found in multiple
    locations (e.g. legacy ``secondary_jodi/2025.csv`` AND a fresh
    ``secondary/2025.csv``), the one with the most recent mtime wins.
    """
    candidates: list[Path] = []
    candidates += list((raw_jodi_dir / dataset_name).glob("*.csv"))
    candidates += list((raw_jodi_dir / f"{dataset_name}_jodi").glob("*.csv"))
    # Root-level YTD files like 'secondaryyear2026.csv'
    candidates += list(raw_jodi_dir.glob(f"{dataset_name}year*.csv"))

    by_year: dict[int, Path] = {}
    for path in candidates:
        year = _year_from_filename(path.name)
        if year is None:
            logger.warning(f"  Skipping unparseable filename: {path}")
            continue
        if year not in by_year or path.stat().st_mtime > by_year[year].stat().st_mtime:
            by_year[year] = path
    return dict(sorted(by_year.items()))


def _year_from_filename(name: str) -> Optional[int]:
    """
    Extract a 4-digit year from JODI filenames such as
    '2024.csv' or 'secondaryyear2026.csv'. Returns None if no plausible
    year (1990-2099) can be located.
    """
    import re
    m = re.search(r"(19\d{2}|20\d{2})", name)
    return int(m.group(1)) if m else None


def _parse_and_concat(
    paths: Iterable[Path],
    dataset_name: str,
    country_codes_path: Optional[Path],
) -> pd.DataFrame:
    """Parse every CSV via the JodiScraper, concat, enrich, sort, type."""
    # Late import: scrapers/ may not be on sys.path at module load time.
    import importlib, sys
    if "scrapers.jodi" in sys.modules:
        JodiScraper = sys.modules["scrapers.jodi"].JodiScraper
    else:
        JodiScraper = importlib.import_module("scrapers.jodi").JodiScraper

    paths = list(paths)
    # data_dir = raw_jodi_dir.parents[1]  → e.g. ".../data"
    # We pass it so the scraper's BaseScraper directory checks succeed.
    data_dir = paths[0].resolve().parents[3]
    scraper = JodiScraper(data_dir=str(data_dir))

    frames: list[pd.DataFrame] = []
    for p in paths:
        frames.append(scraper.parse(dataset_name, p))

    logger.info(f"  Concatenating {len(frames)} year-frames…")
    df = pd.concat(frames, ignore_index=True)
    logger.info(f"  Concatenated: {len(df):,} rows")

    df = _enrich_country(df, country_codes_path)
    df = _sort_and_clean(df)
    return df


def _enrich_country(df: pd.DataFrame, country_codes_path: Optional[Path]) -> pd.DataFrame:
    """Left-join English country names from the reference workbook onto REF_AREA."""
    if country_codes_path is None or not Path(country_codes_path).exists():
        logger.warning(
            "  Skipping country enrichment — country_codes.xlsx not found"
        )
        df["country_name"] = pd.NA
        return df

    codes = pd.read_excel(country_codes_path)
    # Normalise to the columns we need; the ISO workbook uses these names.
    code_col = "Alpha-2 code"
    name_col = "English short name"
    if code_col not in codes.columns or name_col not in codes.columns:
        raise ValueError(
            f"country_codes.xlsx missing expected columns "
            f"({code_col}, {name_col}). Got: {list(codes.columns)}"
        )
    mapping = codes.set_index(code_col)[name_col].to_dict()
    df["country_name"] = df["ref_area"].map(mapping)

    unmatched = df.loc[df["country_name"].isna(), "ref_area"].dropna().unique()
    if len(unmatched):
        logger.info(
            f"  {len(unmatched)} ref_area codes had no country_name match "
            f"(likely JODI aggregates): {sorted(unmatched)[:10]}…"
        )
    return df


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce column order, types, categoricals, and sort by date+ref_area.

    The Phase 4c canonical-column step runs BEFORE the categorical
    conversion so the new columns benefit from the same compression as
    the existing ones. The step is idempotent: re-running on a frame
    that already has product_canonical / category / metric_type just
    overwrites them with freshly looked-up values - useful for picking
    up edits to product_map.csv / metric_types.yaml without re-scraping.
    """
    df = _derive_canonical_columns(df)

    for col in COLUMN_ORDER:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[COLUMN_ORDER].copy()

    # Numeric coercions (idempotent — re-running won't break anything)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int16")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int8")
    df["assessment_code"] = pd.to_numeric(df["assessment_code"], errors="coerce").astype("Int8")
    df["obs_value"] = pd.to_numeric(df["obs_value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Categorical conversion happens last so categories reflect the union
    # across all parsed years.
    for col in _CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = df[col].astype("category")

    # Stable sort: date → ref_area → product → flow → unit. Mirrors how a
    # human would scroll through the data.
    df = df.sort_values(
        ["date", "ref_area", "energy_product", "flow_breakdown", "unit_measure"],
        ignore_index=True,
    )
    return df


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add the 3 Phase-4c canonical columns by looking up native JODI codes
    against reference/product_map.csv and reference/metric_types.yaml.

    Asymmetric by design:
      * `metric_type` is populated for BOTH primary and secondary rows.
        The mapping is identity (JODI's vocabulary IS the canonical
        vocabulary), but we look up via the loader rather than copying
        flow_breakdown verbatim so that:
          (a) the loader validates every native code is declared in
              metric_types.yaml, raising loudly on unknowns;
          (b) the column has a single source of truth (the YAML)
              instead of being implicitly tied to flow_breakdown.
      * `product_canonical` and `category` are populated ONLY for
        secondary rows. Primary's crude products (CRUDEOIL/NGL/
        OTHERCRUDE/TOTCRUDE) are intentionally NOT in product_map.csv
        because the project scope is petroleum *products*. Primary rows
        get NaN here, which downstream queries treat as "out of product
        scope" via `df['product_canonical'].notna()`.

    Performance: JODI has ~10 unique products and ~10 unique flow codes
    per dataset; we cache lookups per-unique-value so each 15M-row frame
    needs only ~20 reference-data calls before .map() runs across the
    column.
    """
    if df.empty:
        for col in ("product_canonical", "category", "metric_type"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    df = df.copy()

    # ------------------------------------------------------------------- #
    # 1. metric_type — applies to BOTH primary and secondary rows.
    #    Branch the source key by per-row `dataset` value.
    # ------------------------------------------------------------------- #
    # Build a (dataset, flow_breakdown) -> canonical-code lookup, batched
    # per dataset so each unique flow-code combo costs one loader call.
    metric_map: dict[tuple[str, str], str] = {}
    unknown_metrics: list[tuple[str, str]] = []
    dataset_values = df["dataset"].astype(str).dropna().unique()
    for ds in dataset_values:
        yaml_source = _METRIC_SOURCE_BY_DATASET.get(ds)
        if yaml_source is None:
            # Defensive: any non-primary/non-secondary dataset value would
            # come from a code change. Surface it rather than silently
            # writing NaN.
            raise ValueError(
                f"Unknown JODI dataset value {ds!r}; expected "
                f"one of {list(_METRIC_SOURCE_BY_DATASET)}."
            )
        ds_flows = (
            df.loc[df["dataset"].astype(str) == ds, "flow_breakdown"]
              .dropna()
              .astype(str)
              .unique()
        )
        for flow in ds_flows:
            try:
                metric_map[(ds, flow)] = canonical_metric(flow, source=yaml_source)
            except KeyError:
                unknown_metrics.append((ds, flow))

    if unknown_metrics:
        raise KeyError(
            f"JODI flow_breakdown codes missing from reference/metric_types.yaml: "
            f"{unknown_metrics!r}. Add them under the relevant source_mappings "
            f"block (jodi_primary / jodi_secondary) and re-run."
        )

    # Vectorised lookup: build a (dataset, flow_breakdown) tuple Series
    # and map through the dict in one pass.
    ds_str = df["dataset"].astype(str)
    flow_str = df["flow_breakdown"].astype(str)
    df["metric_type"] = list(map(metric_map.get, zip(ds_str, flow_str)))

    # ------------------------------------------------------------------- #
    # 2. product_canonical / category — SECONDARY rows only.
    # ------------------------------------------------------------------- #
    is_secondary = df["dataset"].astype(str) == "secondary"

    # Initialise both columns as all-NaN so primary rows get the intended
    # "out of product scope" value without any further work.
    df["product_canonical"] = pd.NA
    df["category"] = pd.NA

    if is_secondary.any():
        sec_products = (
            df.loc[is_secondary, "energy_product"]
              .dropna()
              .astype(str)
              .unique()
        )
        canon_map: dict[str, Optional[str]] = {}
        cat_map: dict[str, Optional[str]] = {}
        unknown_products: list[str] = []
        for name in sec_products:
            try:
                canon_map[name] = canonical_subcategory(name, source=_PRODUCT_MAP_SOURCE)
                cat_map[name] = canonical_category(name, source=_PRODUCT_MAP_SOURCE)
            except KeyError:
                unknown_products.append(name)

        if unknown_products:
            raise KeyError(
                f"JODI secondary energy_product codes missing from "
                f"reference/product_map.csv: {unknown_products!r}. "
                f"Add them (use Category='-', Sub-category='-' for aggregates) "
                f"and re-run."
            )

        # Only assign on the secondary subset; primary stays NaN.
        df.loc[is_secondary, "product_canonical"] = (
            df.loc[is_secondary, "energy_product"].astype(str).map(canon_map)
        )
        df.loc[is_secondary, "category"] = (
            df.loc[is_secondary, "energy_product"].astype(str).map(cat_map)
        )

    return df


def _to_categorical(df: pd.DataFrame, was_categorical: dict[str, bool]) -> pd.DataFrame:
    """
    Restore categorical dtype on columns that were categorical before
    `derive_x_othkero` cast them to object. Idempotent.
    """
    df = df.copy()
    for col, flag in was_categorical.items():
        if flag and col in df.columns and not isinstance(df[col].dtype, pd.CategoricalDtype):
            df[col] = df[col].astype("category")
    return df
