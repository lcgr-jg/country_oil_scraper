"""Load Kayrros satellite demand into the warehouse long-form schema."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from typing import Optional

import pandas as pd

from warehouse.registry import KayrrosProductConfig, load_kayrros_config, kayrros_db_path

logger = logging.getLogger(__name__)


def load_kayrros_observations(
    country_code: str,
    country_name: str,
    products: tuple[KayrrosProductConfig, ...],
) -> pd.DataFrame:
    """Return Kayrros rows for one country registry entry."""
    if not products:
        return _empty_frame()

    db_path = kayrros_db_path()
    if not db_path.exists():
        logger.warning("Kayrros DB not found at %s — skipping satellite rows", db_path)
        return _empty_frame()

    kay_cfg = load_kayrros_config()
    db_meta = kay_cfg.get("db") or {}
    export_module = db_meta.get("export_module", "src.export")
    export_function = db_meta.get("export_function", "get_consumption")
    product_defs = kay_cfg.get("products") or {}

    kayros_root = db_path.parent.parent
    if str(kayros_root) not in sys.path:
        sys.path.insert(0, str(kayros_root))
    os.environ.setdefault("JET_FUEL_DB_PATH", str(db_path))

    mod = __import__(export_module, fromlist=[export_function])
    get_consumption = getattr(mod, export_function)

    ingested_at = datetime.now(tz=UTC)
    frames: list[pd.DataFrame] = []

    for prod in products:
        pdef = product_defs.get(prod.product_key) or {}
        try:
            raw = get_consumption(
                scope_type=prod.scope_type,
                scope=prod.scope,
                country_match=prod.country_match,
                freq=pdef.get("freq", "monthly"),
                metric=pdef.get("metric", "avg_kbd"),
                drop_incomplete=pdef.get("drop_incomplete", True),
            )
        except Exception as exc:
            logger.warning(
                "Kayrros load failed for %s %s: %s",
                country_code,
                prod.product_key,
                exc,
            )
            continue

        if raw is None or len(raw) == 0:
            continue

        df = raw.copy()
        date_col = "period_start" if "period_start" in df.columns else "date"
        value_col = "value" if "value" in df.columns else "kbd"
        df["date"] = pd.to_datetime(df[date_col])
        df["value_kbd"] = pd.to_numeric(df[value_col], errors="coerce")

        frames.append(
            pd.DataFrame(
                {
                    "country_code": country_code,
                    "country_name": country_name,
                    "scope_type": prod.scope_type,
                    "date": df["date"].dt.normalize(),
                    "source": "Kayrros",
                    "source_tier": "satellite",
                    "metric_type": "TOTDEMO",
                    "product_native": prod.product_key,
                    "product_canonical": prod.product_canonical,
                    "category": None,
                    "compare_panel": prod.product_canonical,
                    "value_native": df["value_kbd"],
                    "unit_native": "kbd",
                    "value_kbd": df["value_kbd"],
                    "is_provisional": False,
                    "ingested_at": ingested_at,
                }
            )
        )

    if not frames:
        return _empty_frame()
    out = pd.concat(frames, ignore_index=True)
    return out.dropna(subset=["date", "value_kbd"])


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "country_code",
            "country_name",
            "scope_type",
            "date",
            "source",
            "source_tier",
            "metric_type",
            "product_native",
            "product_canonical",
            "category",
            "compare_panel",
            "value_native",
            "unit_native",
            "value_kbd",
            "is_provisional",
            "ingested_at",
        ]
    )
