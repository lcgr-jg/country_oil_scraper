"""Local Prefect flows for country updates + warehouse consolidate.

Run ad hoc (no Cloud required)::

    pip install -e ".[orchestration]"
    python -c "from orchestration.flows import update_and_consolidate; update_and_consolidate(['norway'])"

Or serve / deploy later; the same flows work with Prefect Cloud when you add a worker.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from prefect import flow, task

from pipelines.registry import list_pipeline_ids
from pipelines.runner import run_consolidate, run_update

logger = logging.getLogger(__name__)


@task(name="update-pipeline", retries=1, retry_delay_seconds=60)
def update_pipeline_task(pipeline_id: str, extra_args: list[str] | None = None) -> str:
    """Run one country/JODI update script; return the pipeline id on success."""
    run_update(pipeline_id, extra_args or [])
    return pipeline_id


@task(name="consolidate-warehouse")
def consolidate_task(extra_args: list[str] | None = None) -> str:
    run_consolidate(extra_args or [])
    return "warehouse"


@flow(name="update-one")
def update_one(pipeline_id: str, extra_args: list[str] | None = None) -> str:
    """Refresh a single pipeline (e.g. norway)."""
    return update_pipeline_task(pipeline_id, extra_args)


@flow(name="update-and-consolidate")
def update_and_consolidate(
    pipeline_ids: Sequence[str] | None = None,
    *,
    include_jodi: bool = False,
    skip_consolidate: bool = False,
    extra_args: list[str] | None = None,
    consolidate_args: list[str] | None = None,
) -> dict[str, str]:
    """Update many countries (parallel tasks), then rebuild DuckDB.

    Failures are isolated per country via Prefect tasks. Consolidate runs only
    after the update map completes (successful or not — adjust if you prefer
    stricter gating).
    """
    ids = list(pipeline_ids) if pipeline_ids is not None else list_pipeline_ids(default_batch_only=True)
    if include_jodi and "jodi" not in ids:
        ids = [*ids, "jodi"]

    # Submit independently so one agency outage does not cancel siblings.
    futures = {
        pid: update_pipeline_task.submit(pid, extra_args) for pid in ids
    }
    outcomes: dict[str, str] = {}
    for pid, fut in futures.items():
        try:
            outcomes[pid] = fut.result()
        except Exception as exc:  # noqa: BLE001 — surface per-country in flow result
            logger.exception("Pipeline %s failed", pid)
            outcomes[pid] = f"error: {exc}"

    if not skip_consolidate:
        try:
            outcomes["consolidate"] = consolidate_task(consolidate_args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Consolidate failed")
            outcomes["consolidate"] = f"error: {exc}"

    return outcomes


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Smoke path: list default batch only (does not hit the network).
    print("default batch:", ", ".join(list_pipeline_ids(default_batch_only=True)))
