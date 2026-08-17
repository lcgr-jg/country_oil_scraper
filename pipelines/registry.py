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


# Keys are what you pass to run_update("norway") / Prefect.
PIPELINES: dict[str, Pipeline] = {
    p.id: p
    for p in [
        Pipeline("australia", "update_australia.py", "Australia APSTAT petroleum statistics"),
        Pipeline("germany", "update_germany.py", "Germany BAFA mineral oil data"),
        Pipeline("hungary", "update_hungary.py", "Hungary MEKH demand + stocks"),
        Pipeline(
            "india",
            "update_india_pt_consumption.py",
            "India PPAC product consumption",
        ),
        Pipeline("italy", "update_italy.py", "Italy MASE consumption"),
        Pipeline("japan", "update_japan.py", "Japan METI consumption"),
        Pipeline(
            "jodi",
            "update_jodi.py",
            "JODI World Database (primary + secondary)",
            default_batch=False,
        ),
        Pipeline("korea", "update_korea.py", "Korea KNOC / Petronet"),
        Pipeline("norway", "update_norway.py", "Norway SSB petroleum sales"),
        Pipeline("poland", "update_poland.py", "Poland ARE liquid fuels"),
        Pipeline("portugal", "update_portugal.py", "Portugal DGEG sales"),
        Pipeline("spain", "update_spain.py", "Spain CORES consumption"),
        Pipeline("taiwan", "update_taiwan.py", "Taiwan MOEA consumption"),
        Pipeline("thailand", "update_thailand.py", "Thailand EPPO sales"),
        Pipeline("uk", "update_uk.py", "UK DESNZ energy trends"),
        Pipeline("ukraine", "update_ukraine.py", "Ukraine SSSU fuel"),
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
