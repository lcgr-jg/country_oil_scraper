"""Central DuckDB warehouse for country oil demand data."""

from warehouse.consolidate import (
    consolidate,
    default_warehouse_path,
    ensure_warehouse,
    warehouse_needs_rebuild,
)

__all__ = [
    "consolidate",
    "default_warehouse_path",
    "ensure_warehouse",
    "warehouse_needs_rebuild",
]
