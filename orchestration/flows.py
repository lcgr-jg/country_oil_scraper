"""Local Prefect flows for country updates + warehouse consolidate.

Run ad hoc (no Cloud required)::

    python -c "from orchestration.flows import update_one; print(update_one('norway'))"

Weekday polling deployments (Norway + Germany)::

    python scripts/serve_weekday_polls.py

Keep that process running (and ``prefect server start``) so scheduled checks fire.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from prefect import flow, task
from prefect.logging import get_run_logger

from pipelines.registry import list_pipeline_ids
from pipelines.runner import run_consolidate, run_update_with_status

logger = logging.getLogger(__name__)


@task(name="update-pipeline", retries=1, retry_delay_seconds=60, persist_result=True)
def update_pipeline_task(
    pipeline_id: str, extra_args: list[str] | None = None
) -> dict[str, Any]:
    """Run one country/JODI update; return structured status dict for the UI."""
    run_logger = get_run_logger()
    result = run_update_with_status(pipeline_id, extra_args or [])
    payload = result.to_dict()
    if result.status == "error":
        raise RuntimeError(
            f"{pipeline_id} failed: {result.message} (exit {result.returncode})"
        )
    # get_run_logger → visible in Prefect UI Logs; payload → Results tab.
    run_logger.info(
        "POLL RESULT %s status=%s max_date %s → %s rows %s → %s (%s)",
        pipeline_id,
        result.status,
        result.max_date_before,
        result.max_date_after,
        result.rows_before,
        result.rows_after,
        result.message,
    )
    return payload


@task(name="consolidate-warehouse", persist_result=True)
def consolidate_task(extra_args: list[str] | None = None) -> str:
    run_consolidate(extra_args or [])
    return "warehouse"


@flow(name="update-one", persist_result=True, log_prints=True)
def update_one(
    pipeline_id: str, extra_args: list[str] | None = None
) -> dict[str, Any]:
    """Refresh a single pipeline (e.g. norway). Returns status payload."""
    payload = update_pipeline_task(pipeline_id, extra_args)
    print(  # also lands in UI when log_prints=True
        f"POLL RESULT {payload.get('pipeline_id')} "
        f"status={payload.get('status')} "
        f"max_date={payload.get('max_date_before')}→{payload.get('max_date_after')}"
    )
    return payload


@flow(name="update-and-consolidate", persist_result=True, log_prints=True)
def update_and_consolidate(
    pipeline_ids: Sequence[str] | None = None,
    *,
    include_jodi: bool = False,
    skip_consolidate: bool = False,
    consolidate_only_if_updated: bool = True,
    extra_args: list[str] | None = None,
    consolidate_args: list[str] | None = None,
) -> dict[str, Any]:
    """Update many countries (parallel tasks), then optionally rebuild DuckDB.

    When ``consolidate_only_if_updated`` is True (default), skip consolidate if
    every country poll was ``unchanged`` / ``unknown`` with no ``updated``.
    """
    ids = list(pipeline_ids) if pipeline_ids is not None else list_pipeline_ids(default_batch_only=True)
    if include_jodi and "jodi" not in ids:
        ids = [*ids, "jodi"]

    futures = {
        pid: update_pipeline_task.submit(pid, extra_args) for pid in ids
    }
    outcomes: dict[str, Any] = {}
    any_updated = False
    for pid, fut in futures.items():
        try:
            payload = fut.result()
            outcomes[pid] = payload
            if isinstance(payload, dict) and payload.get("status") == "updated":
                any_updated = True
        except Exception as exc:  # noqa: BLE001 — surface per-country in flow result
            logger.exception("Pipeline %s failed", pid)
            outcomes[pid] = {"pipeline_id": pid, "status": "error", "message": str(exc)}

    if not skip_consolidate:
        should_consolidate = any_updated or not consolidate_only_if_updated
        if should_consolidate:
            try:
                outcomes["consolidate"] = consolidate_task(consolidate_args)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Consolidate failed")
                outcomes["consolidate"] = f"error: {exc}"
        else:
            outcomes["consolidate"] = "skipped (no country updated)"

    return outcomes


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("default batch:", ", ".join(list_pipeline_ids(default_batch_only=True)))
