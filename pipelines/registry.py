"""Pipeline registry: maps stable IDs to country/JODI update scripts.

Prefect flows and ``scripts/run_pipeline.py`` both use this so adding a market
means registering one row here (plus scraper/processor/update script as today).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@dataclass(frozen=True)
class Pipeline:
    """One schedulable ETL entrypoint."""

    id: str
    script: str  # filename under scripts/
    description: str
    # When True, include in the default "update all countries" Prefect flow.
    # JODI is separate (benchmark source, not a national agency).
    default_batch: bool = True
    # Relative to data/processed/ — used to detect updated vs unchanged after a poll.
    # None → status "unknown" on success (e.g. multi-file JODI).
    parquet_rel_path: str | None = None
    date_column: str = "date"


# Keys are what you pass to run_update("norway") / Prefect.
# parquet_rel_path mirrors config/countries.yaml where applicable.
PIPELINES: dict[str, Pipeline] = {
    p.id: p
    for p in [
        Pipeline(
            "australia",
            "update_australia.py",
            "Australia APSTAT petroleum statistics",
            parquet_rel_path="australia/australia_petroleum_statistics.parquet",
        ),
        Pipeline(
            "germany",
            "update_germany.py",
            "Germany BAFA mineral oil data",
            parquet_rel_path="germany/germany_bafa_demand.parquet",
        ),
        Pipeline(
            "hungary",
            "update_hungary.py",
            "Hungary MEKH demand + stocks",
            parquet_rel_path="hungary/hungary_mekh_demand.parquet",
        ),
        Pipeline(
            "india",
            "update_india_pt_consumption.py",
            "India PPAC product consumption",
            parquet_rel_path="india/india_pt_consumption.parquet",
        ),
        Pipeline(
            "italy",
            "update_italy.py",
            "Italy MASE consumption",
            parquet_rel_path="italy/italy_mase_consumption.parquet",
        ),
        Pipeline(
            "japan",
            "update_japan.py",
            "Japan METI consumption",
            parquet_rel_path="japan/japan_meti_consumption.parquet",
        ),
        Pipeline(
            "jodi",
            "update_jodi.py",
            "JODI World Database (primary + secondary)",
            default_batch=False,
            parquet_rel_path=None,
        ),
        Pipeline(
            "korea",
            "update_korea.py",
            "Korea KNOC / Petronet",
            parquet_rel_path="korea/korea_knoc.parquet",
        ),
        Pipeline(
            "norway",
            "update_norway.py",
            "Norway SSB petroleum sales",
            parquet_rel_path="norway/norway_ssb_sales.parquet",
        ),
        Pipeline(
            "poland",
            "update_poland.py",
            "Poland ARE liquid fuels",
            parquet_rel_path="poland/poland_are_liquid_fuels.parquet",
        ),
        Pipeline(
            "portugal",
            "update_portugal.py",
            "Portugal DGEG sales",
            parquet_rel_path="portugal/portugal_dgeg_sales.parquet",
        ),
        Pipeline(
            "spain",
            "update_spain.py",
            "Spain CORES consumption",
            parquet_rel_path="spain/spain_cores_consumption.parquet",
        ),
        Pipeline(
            "taiwan",
            "update_taiwan.py",
            "Taiwan MOEA consumption",
            parquet_rel_path="taiwan/taiwan_moea_consumption.parquet",
        ),
        Pipeline(
            "thailand",
            "update_thailand.py",
            "Thailand EPPO sales",
            parquet_rel_path="thailand/thailand_eppo_sales.parquet",
        ),
        Pipeline(
            "uk",
            "update_uk.py",
            "UK DESNZ energy trends",
            parquet_rel_path="uk/uk_energy_trends.parquet",
        ),
        Pipeline(
            "ukraine",
            "update_ukraine.py",
            "Ukraine SSSU fuel",
            parquet_rel_path="ukraine/ukraine_sssu_fuel.parquet",
        ),
    ]
}


def list_pipeline_ids(*, default_batch_only: bool = False) -> list[str]:
    ids = [
        pid
        for pid, p in PIPELINES.items()
        if (not default_batch_only) or p.default_batch
    ]
    return sorted(ids)


def get_pipeline(pipeline_id: str) -> Pipeline:
    key = pipeline_id.strip().lower()
    if key not in PIPELINES:
        known = ", ".join(list_pipeline_ids())
        raise KeyError(f"Unknown pipeline {pipeline_id!r}. Known: {known}")
    return PIPELINES[key]


def script_path(pipeline_id: str) -> Path:
    pipe = get_pipeline(pipeline_id)
    path = SCRIPTS_DIR / pipe.script
    if not path.is_file():
        raise FileNotFoundError(f"Update script missing for {pipeline_id}: {path}")
    return path
