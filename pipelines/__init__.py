"""Shared ETL entrypoints for CLIs and Prefect."""

from pipelines.registry import PIPELINES, get_pipeline, list_pipeline_ids
from pipelines.runner import run_consolidate, run_many, run_update

__all__ = [
    "PIPELINES",
    "get_pipeline",
    "list_pipeline_ids",
    "run_consolidate",
    "run_many",
    "run_update",
]
