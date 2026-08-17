"""Structured pipeline run outcomes for polling / Prefect UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

PipelineStatus = Literal["updated", "unchanged", "error", "unknown"]


@dataclass(frozen=True)
class PipelineRunResult:
    """Result of one agency poll/update.

    ``updated`` / ``unchanged`` require a registered parquet fingerprint path.
    ``unknown`` means the script succeeded but we could not compare state
    (e.g. JODI multi-file, or first run with no prior parquet).
    """

    pipeline_id: str
    status: PipelineStatus
    returncode: int
    rows_before: int | None = None
    rows_after: int | None = None
    max_date_before: str | None = None
    max_date_after: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
