"""Generate notebooks/29_demand_nowcast_poc.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "29_demand_nowcast_poc.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "id": None,
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
        "id": None,
    }


cells = [
    md(
        """# Demand nowcast POC — national scrapers vs JODI

Phase 3 proof of concept (**no IEA** — paywall / irregular access).

| Layer | Role |
|-------|------|
| National scrapers (DE BAFA, JP METI, KR KNOC, AU DCCEEW) | Early demand print |
| JODI `TOTDEMO` | Monthly settle / global backbone |

**Buckets:** `gasoline`, `gasoil_diesel` (same recipes as Phase 2 compare buckets).

Re-export: `python scripts/export_demand_nowcast.py`
"""
    ),
    code(
        r'''from pathlib import Path
import sys

import pandas as pd
from IPython.display import display, Markdown

pd.set_option("display.max_rows", 100)
pd.set_option("display.max_colwidth", 80)


def _resolve_project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "analytics" / "demand_nowcast.py").exists():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "analytics" / "demand_nowcast.py").exists():
            return nested
    raise RuntimeError(f"Could not locate project root from cwd: {here}")


ROOT = _resolve_project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.demand_nowcast import (
    build_lead_summary,
    build_nowcast_long,
    build_nowcast_tracker,
    build_nowcast_wide,
    export_nowcast_csvs,
    list_poc_series,
    make_nowcast_explorer,
)

print("ROOT:", ROOT)
display(pd.DataFrame([s.__dict__ for s in list_poc_series()]))
'''
    ),
    md("## 1. Build panels + lead summary"),
    code(
        r'''paths = export_nowcast_csvs(ROOT)
long = build_nowcast_long(ROOT)
wide = build_nowcast_tracker(build_nowcast_wide(long))
lead = build_lead_summary(wide)

display(Markdown("### Export paths"))
for k, p in paths.items():
    print(f"  {k}: {p.relative_to(ROOT)}")

display(Markdown("### Lead vs JODI (months official is ahead)"))
display(lead)

display(Markdown(
    f"Long rows: **{len(long):,}** · wide: **{len(wide):,}** · "
    f"nowcast-only months: **{int(wide['is_nowcast_month'].sum()):,}**"
))
'''
    ),
    md(
        """## 2. Interactive explorer

- **Levels** — official early print vs JODI settle
- **Tracker** — combined series (`official` when present, else JODI)
- **% diff** — overlap quality where both exist
"""
    ),
    code(
        r'''make_nowcast_explorer(long, wide)
'''
    ),
    md(
        """## 3. How to read this

1. Positive `lead_months` → national agency is the nowcast source for the latest month(s).
2. `is_nowcast_month` in the wide CSV flags months with official data but no JODI yet.
3. When JODI arrives, compare `pct_diff` — large persistent bias means the bucket map or unit conversion needs review (Japan gasoil includes Fuel Oil A by design).
4. Inventories are **out of scope** for this POC; extend later with national CLOSTLV → JODI only (still no IEA).
"""
    ),
]


for i, c in enumerate(cells):
    c["id"] = f"c{i:02d}"

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "pygments_lexer": "ipython3"},
    },
    "cells": cells,
}

OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
