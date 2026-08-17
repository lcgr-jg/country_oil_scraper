"""Region presets for multi-country dashboard views."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from warehouse.registry import _CONFIG_DIR, list_countries


@dataclass(frozen=True)
class RegionConfig:
    region_id: str
    display_name: str
    country_ids: tuple[str, ...]


def load_regions_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "regions.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def list_regions(*, enabled_countries_only: bool = True) -> list[RegionConfig]:
    """Return region presets with country_ids filtered to enabled countries."""
    enabled = {c.country_id for c in list_countries(enabled_only=enabled_countries_only)}
    raw = load_regions_config().get("regions") or {}
    out: list[RegionConfig] = []
    for region_id, cfg in raw.items():
        ids = tuple(c for c in (cfg.get("country_ids") or []) if c in enabled)
        if not ids:
            continue
        out.append(
            RegionConfig(
                region_id=region_id,
                display_name=str(cfg.get("display_name", region_id)),
                country_ids=ids,
            )
        )
    return sorted(out, key=lambda r: r.display_name.lower())


def get_region(region_id: str) -> RegionConfig:
    for region in list_regions(enabled_countries_only=False):
        if region.region_id == region_id:
            return region
    raise KeyError(f"Unknown region_id: {region_id!r}")
