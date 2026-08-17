"""Run country / JODI update scripts through one API.

Uses subprocess so each ``scripts/update_*.py`` keeps its own argparse and
logging. CLI flags are forwarded unchanged (e.g. ``--bootstrap``, ``--force``).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pipelines.registry import PROJECT_ROOT, get_pipeline, list_pipeline_ids, script_path

logger = logging.getLogger(__name__)


def run_update(
    pipeline_id: str,
    args: Sequence[str] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute ``scripts/update_{…}.py`` for ``pipeline_id``.

    Parameters
    ----------
    pipeline_id
        Registry key (e.g. ``"norway"``, ``"jodi"``).
    args
        Extra CLI arguments forwarded to the update script.
    check
        If True (default), raise ``CalledProcessError`` on non-zero exit.
    """
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
    """Run several pipelines; return map of id → returncode.

    Failed pipelines are logged. By default continues so one broken agency
    does not block the rest (Prefect tasks can still isolate failures).
    """
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
