"""Console script entry (``oil-pipeline``) — same behavior as scripts/run_pipeline.py."""

from __future__ import annotations

import argparse
import logging
import sys

from pipelines.registry import PIPELINES, list_pipeline_ids
from pipelines.runner import run_consolidate, run_many, run_update


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run a registered country/JODI update pipeline",
    )
    parser.add_argument(
        "pipeline",
        help='Pipeline id (e.g. norway), "list", or "all" for default country batch',
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="After updates, run consolidate_warehouse.py",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="With 'all', stop at the first failing pipeline",
    )
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded to the update script; use -- then flags",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    forwarded = list(args.script_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]

    target = args.pipeline.strip().lower()

    if target == "list":
        for pid in list_pipeline_ids():
            p = PIPELINES[pid]
            batch = "batch" if p.default_batch else "manual"
            print(f"  {pid:12}  [{batch}]  {p.description}")
        return

    if target == "all":
        results = run_many(extra_args=forwarded, stop_on_error=args.stop_on_error)
        failed = [k for k, rc in results.items() if rc != 0]
        if args.consolidate and not (failed and args.stop_on_error):
            run_consolidate()
        if failed:
            sys.exit(1)
        return

    run_update(target, forwarded)
    if args.consolidate:
        run_consolidate()


if __name__ == "__main__":
    main()
