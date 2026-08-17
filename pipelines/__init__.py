"""Shared ETL entrypoints for CLIs and Prefect."""

from pipelines.registry import PIPELINES, get_pipeline, list_pipeline_ids
from pipelines.results import PipelineRunResult
from pipelines.runner import (
    run_consolidate,
    run_many,
    run_many_with_status,
    run_update,
    run_update_with_status,
)

__all__ = [
    "PIPELINES",
    "PipelineRunResult",
    "get_pipeline",
    "list_pipeline_ids",
    "run_consolidate",
    "run_many",
    "run_many_with_status",
    "run_update",
    "run_update_with_status",
]
