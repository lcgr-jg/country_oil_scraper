"""Serve weekday poll deployments (local Prefect).

Prerequisites
-------------
1. Prefect API reachable (local server)::

       prefect server start
       # API: http://127.0.0.1:4200/api

2. From repo root, with the project venv active::

       python scripts/serve_weekday_polls.py

Leave this process running. Cron is Mon–Fri **04:00 Europe/London** (slow hours).
Each run hits the agency site; the flow result shows ``updated`` vs ``unchanged``.
If the PC is asleep at 04:00, the run waits until it wakes (serve must still be running).

Trigger once immediately from the UI (Deployments → Run) to verify without waiting.

Add another market
------------------
1. Confirm the id exists: ``python scripts/run_pipeline.py list``
2. Append ``(id, short_label)`` to ``POLL_COUNTRIES`` below
3. Restart this script (Ctrl+C, then run again)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prefect import serve  # noqa: E402
from prefect.schedules import Cron  # noqa: E402

from orchestration.flows import update_one  # noqa: E402
from pipelines.registry import get_pipeline  # noqa: E402

# Weekday early-morning poll — slow hours while the machine is often on but idle.
# Note: if Windows is asleep, the job waits until wake (serve must also be running).
SCHEDULE = Cron("0 4 * * 2-5", timezone="Europe/London")

# pipeline_id must match pipelines/registry.py (see: run_pipeline.py list)
POLL_COUNTRIES: list[tuple[str, str]] = [
    ("australia", "APSTAT petroleum statistics"),
    ("germany", "BAFA mineral oil data"),
    ("hungary", "MEKH demand + stocks"),
    ("india", "PPAC product consumption"),
    ("italy", "MASE consumption"),
    ("japan", "METI consumption"),
    ("jodi", "JODI World Database (primary + secondary)"),
    ("korea", "KNOC / Petronet"),
    ("norway", "SSB petroleum sales"),
    ("poland", "GUS petroleum sales"),
    ("portugal", "Portugal DGEG Sales"),
    ("spain", "MEE consumption"),
    ("taiwan", "MOEA consumption"),
    ("thailand", "EPPO sales"),
    ("uk", "DESNZ energy trends"),
    ("ukraine", "SSSU fuel")
]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    deployments = []
    for pipeline_id, label in POLL_COUNTRIES:
        # Fail fast if the id is typo'd / not registered.
        get_pipeline(pipeline_id)
        deployments.append(
            update_one.to_deployment(
                name=f"{pipeline_id}-weekday-poll",
                parameters={"pipeline_id": pipeline_id},
                schedules=[SCHEDULE],
                tags=["poll", pipeline_id, "weekday"],
                description=f"Poll {label}; unchanged is OK.",
            )
        )

    names = ", ".join(f"{c}-weekday-poll" for c, _ in POLL_COUNTRIES)
    logging.info("Serving %s (%s). Ctrl+C to stop.", names, SCHEDULE)
    serve(*deployments)


if __name__ == "__main__":
    main()
