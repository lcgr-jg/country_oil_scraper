"""Run country / JODI update scripts through one API.

Uses subprocess so each ``scripts/update_*.py`` keeps its own argparse and
logging. CLI flags are forwarded unchanged (e.g. ``--bootstrap``, ``--force``).

``run_update_with_status`` fingerprints the processed parquet before/after so
scheduled polls can distinguish ``updated`` vs ``unchanged``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pipelines.fingerprint import fingerprint_parquet
from pipelines.registry import PROJECT_ROOT, get_pipeline, list_pipeline_ids, script_path
from pipelines.results import PipelineRunResult

logger = logging.getLogger(__name__)


def run_update(
    pipeline_id: str,
    args: Sequence[str] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute ``scripts/update_{…}.py`` for ``pipeline_id``."""
    pipe = get_pipeline(pipeline_id)
    path = script_path(pipeline_id)
    cmd = [sys.executable, str(path), *(args or ())]
    logger.info("Running pipeline %s (%s): %s", pipe.id, pipe.description, " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        check=check,
        text=True,
    )


def run_update_with_status(
    pipeline_id: str,
    args: Sequence[str] | None = None,
) -> PipelineRunResult:
    """Run an update and classify the outcome for polling schedules.

    Compares processed parquet row count + max(date) when
    ``Pipeline.parquet_rel_path`` is set.
    """
    pipe = get_pipeline(pipeline_id)
    before = None
    if pipe.parquet_rel_path:
        before = fingerprint_parquet(
            pipe.parquet_rel_path, date_column=pipe.date_column
        )

    try:
        cp = run_update(pipeline_id, args, check=False)
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Pipeline %s failed to start", pipeline_id)
        return PipelineRunResult(
            pipeline_id=pipe.id,
            status="error",
            returncode=-1,
            rows_before=before.rows if before else None,
            max_date_before=before.max_date if before else None,
            message=str(exc),
        )

    if cp.returncode != 0:
        return PipelineRunResult(
            pipeline_id=pipe.id,
            status="error",
            returncode=cp.returncode,
            rows_before=before.rows if before else None,
            max_date_before=before.max_date if before else None,
            message=f"update script exited {cp.returncode}",
        )

    if not pipe.parquet_rel_path:
        return PipelineRunResult(
            pipeline_id=pipe.id,
            status="unknown",
            returncode=0,
            message="no parquet fingerprint configured (treat success as checked)",
        )

    after = fingerprint_parquet(pipe.parquet_rel_path, date_column=pipe.date_column)

    if not after.exists:
        return PipelineRunResult(
            pipeline_id=pipe.id,
            status="unknown",
            returncode=0,
            rows_before=before.rows if before and before.exists else None,
            max_date_before=before.max_date if before and before.exists else None,
            message="script ok but processed parquet missing",
        )

    # First successful materialization counts as an update.
    if before is None or not before.exists:
        status = "updated"
        message = "parquet created"
    elif after.unchanged_from(before):
        status = "unchanged"
        message = "no change in rows or max(date)"
    else:
        status = "updated"
        message = "rows and/or max(date) changed"

    result = PipelineRunResult(
        pipeline_id=pipe.id,
        status=status,
        returncode=0,
        rows_before=before.rows if before and before.exists else None,
        rows_after=after.rows,
        max_date_before=before.max_date if before and before.exists else None,
        max_date_after=after.max_date,
        message=message,
    )
    logger.info(
        "Pipeline %s → %s (max_date %s → %s, rows %s → %s)",
        result.pipeline_id,
        result.status,
        result.max_date_before,
        result.max_date_after,
        result.rows_before,
        result.rows_after,
    )
    return result


def run_consolidate(
    args: Sequence[str] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute ``scripts/consolidate_warehouse.py``."""
    path = PROJECT_ROOT / "scripts" / "consolidate_warehouse.py"
    if not path.is_file():
        raise FileNotFoundError(path)
    cmd = [sys.executable, str(path), *(args or ())]
    logger.info("Consolidating warehouse: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        check=check,
        text=True,
    )


def run_many(
    pipeline_ids: Sequence[str] | None = None,
    *,
    extra_args: Sequence[str] | None = None,
    stop_on_error: bool = False,
) -> dict[str, int]:
    """Run several pipelines; return map of id → returncode."""
    ids = list(pipeline_ids) if pipeline_ids is not None else list_pipeline_ids(default_batch_only=True)
    results: dict[str, int] = {}
    for pid in ids:
        try:
            cp = run_update(pid, extra_args, check=False)
            results[pid] = cp.returncode
            if cp.returncode != 0:
                logger.error("Pipeline %s exited %s", pid, cp.returncode)
                if stop_on_error:
                    break
        except Exception:
            logger.exception("Pipeline %s failed before exit", pid)
            results[pid] = -1
            if stop_on_error:
                break
    return results


def run_many_with_status(
    pipeline_ids: Sequence[str] | None = None,
    *,
    extra_args: Sequence[str] | None = None,
    stop_on_error: bool = False,
) -> dict[str, PipelineRunResult]:
    """Like ``run_many`` but returns structured poll outcomes."""
    ids = list(pipeline_ids) if pipeline_ids is not None else list_pipeline_ids(default_batch_only=True)
    out: dict[str, PipelineRunResult] = {}
    for pid in ids:
        result = run_update_with_status(pid, extra_args)
        out[pid] = result
        if result.status == "error" and stop_on_error:
            break
    return out
