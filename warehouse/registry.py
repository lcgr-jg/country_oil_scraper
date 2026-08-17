"""Load country and Kayrros configuration from YAML."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _PROJECT_ROOT / "config"


@dataclass(frozen=True)
class KayrrosProductConfig:
    product_key: str
    product_canonical: str
    scope_type: str
    scope: str
    country_match: str = "code"


@dataclass(frozen=True)
class CountryConfig:
    country_id: str
    display_name: str
    country_code: str
    enabled: bool
    official_source_label: str
    parquet_path: Path
    reference_module: str
    jodi_ref_area: str
    demand_metric_type: str
    kayrros_enabled: bool
    kayrros_products: tuple[KayrrosProductConfig, ...] = field(default_factory=tuple)
    unit_native: Optional[str] = None
    unit_native_attr: Optional[str] = None
    jet_product_native: Optional[str] = None
    product_column: Optional[str] = None
    value_column: Optional[str] = None


def project_root() -> Path:
    return _PROJECT_ROOT


def coding_root() -> Path:
    return _PROJECT_ROOT.parent


def load_countries_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "countries.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_kayrros_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "kayrros.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_divergence_baselines() -> list[dict[str, Any]]:
    path = _CONFIG_DIR / "divergence_baselines.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("baselines") or [])


def list_countries(*, enabled_only: bool = True) -> list[CountryConfig]:
    raw = load_countries_config().get("countries") or {}
    out: list[CountryConfig] = []
    processed = _PROJECT_ROOT / "data" / "processed"
    for country_id, cfg in raw.items():
        if enabled_only and not cfg.get("enabled", True):
            continue
        rel = (cfg.get("parquet") or {}).get("rel_path", "")
        kayrros_cfg = cfg.get("kayrros") or {}
        kay_products = tuple(
            KayrrosProductConfig(
                product_key=p["product_key"],
                product_canonical=p.get("product_canonical", p["product_key"]),
                scope_type=p["scope_type"],
                scope=str(p["scope"]),
                country_match=p.get("country_match", "code"),
            )
            for p in (kayrros_cfg.get("products") or [])
        )
        out.append(
            CountryConfig(
                country_id=country_id,
                display_name=cfg["display_name"],
                country_code=cfg["country_code"],
                enabled=bool(cfg.get("enabled", True)),
                official_source_label=cfg.get("official_source_label", country_id),
                parquet_path=processed / rel,
                reference_module=str(cfg.get("reference_module") or ""),
                jodi_ref_area=cfg.get("jodi_ref_area", cfg["country_code"]),
                demand_metric_type=cfg.get("demand_metric_type", "TOTDEMO"),
                kayrros_enabled=bool(kayrros_cfg.get("enabled", False)),
                kayrros_products=kay_products,
                unit_native=cfg.get("unit_native"),
                unit_native_attr=cfg.get("unit_native_attr"),
                jet_product_native=cfg.get("jet_product_native"),
                product_column=cfg.get("product_column"),
                value_column=cfg.get("value_column"),
            )
        )
    return out


def get_country(country_id: str) -> CountryConfig:
    for cfg in list_countries(enabled_only=False):
        if cfg.country_id == country_id:
            return cfg
    raise KeyError(f"Unknown country_id: {country_id!r}")


def import_reference_module(reference_module: str) -> Any:
    if not reference_module:
        raise ValueError("reference_module is not configured")
    return importlib.import_module(reference_module)


def kayrros_db_path() -> Path:
    rel = (load_kayrros_config().get("db") or {}).get(
        "rel_path", "kayros/jet_fuel/data/jet_fuel.duckdb"
    )
    return coding_root() / rel
