# Country Oil Data Scraper

Modular framework for scraping petroleum data from national statistical agencies,
starting with India's PPAC (Petroleum Planning & Analysis Cell). Designed for
eventual comparison against JODI (Joint Organisations Data Initiative).

## Setup

From the repo root (Python 3.10+):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,orchestration]"
```

Or: `pip install -r requirements.txt` (includes Prefect). Editable install is preferred
so `scrapers` / `pipelines` / `orchestration` import cleanly.

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the scraper / processor / update-script
split, per-country reference, and rules for adding new sources.

```
country_oil_scraper/
├── config/sources.yaml        # Registry of all data sources per country
├── scrapers/                  # download() + parse() — source-native tidy data
├── processors/                # load / upsert / save + canonical mapping
├── pipelines/                 # Shared registry + run_update() API
├── orchestration/             # Prefect flows (local; Cloud-ready later)
├── scripts/update_*.py        # Per-country CLIs (still supported)
├── scripts/run_pipeline.py    # Unified CLI over the registry
├── scripts/scratch/           # One-off probes (not scheduled)
├── reference/                 # product_map.csv, metric_types.yaml
├── data/raw/{country}/        # Downloaded files as-is (gitignored)
├── data/processed/{country}/  # Parquet databases (gitignored)
├── data/warehouse/backups/    # Dated DuckDB snapshots (tracked)
├── docs/                      # User guides (HTML)
└── notebooks/                 # Exploration and prototyping
```

**Quick rule:** parsing lives in scrapers; database persistence and canonical
columns live in processors. Scheduling goes through `pipelines` / Prefect, not
notebooks or `scripts/scratch/`.

## Central warehouse & dashboard

Countries are wired into a local **DuckDB warehouse** and a **Streamlit**
dashboard (`config/countries.yaml`). Country ETL runs via update scripts (or the
unified pipeline CLI); consolidation reads those parquets into one file for
charts, JODI cross-checks, Kayrros jet, and CSV/HTML export.

Dated warehouse backups live under `data/warehouse/backups/` (committed on
purpose). The live `oil_demand.duckdb` is gitignored — rebuild anytime with
consolidate.

### 1. Refresh country parquets (as needed)

Per-country scripts still work:

```powershell
python scripts/update_norway.py
python scripts/update_india_pt_consumption.py
python scripts/update_jodi.py
```

Or use the registry (same underlying scripts):

```powershell
python scripts/run_pipeline.py list
python scripts/run_pipeline.py norway
python scripts/run_pipeline.py norway -- --force
python scripts/run_pipeline.py all --consolidate
```

### 2. Build the warehouse

From the project root:

```powershell
python scripts/consolidate_warehouse.py
```

Output: `data/warehouse/oil_demand.duckdb` (gitignored). Options:

- `--countries norway,india` — subset rebuild
- `--no-jodi` / `--no-kayrros` — skip benchmark or satellite tiers
- `-v` — verbose logging

### 3. Run the dashboard

```powershell
streamlit run apps/demand_dashboard.py
```

Use the sidebar to pick **single country** or **multi-country aggregate** (region
presets in `config/regions.yaml` pre-fill the country list; you can edit it).
Choose reference month, native vs canonical view (single-country only), and
optional JODI / Kayrros / seasonality panels. At the bottom of the page:

- **Download data (CSV)** — per-dataset CSVs or a ZIP bundle
- **Download HTML snapshot** — static export of the current charts and tables

### 4. Optional: Prefect (local)

After `pip install -e ".[orchestration]"` (or install into your Coding `.venv`):

```powershell
# Terminal A — UI
prefect server start
# open http://127.0.0.1:4200

# Ad hoc one-country run (shows updated/unchanged in the flow result)
python -c "from orchestration.flows import update_one; print(update_one('norway'))"

# Or CLI with JSON status
python scripts/run_pipeline.py norway --with-status
```

**Weekday polling** — Prefect does not know agency calendars;
it runs a check Mon–Fri **04:00 Europe/London** (slow hours). Unchanged polls are success, not failure.
If the PC is asleep at that time, the run waits until wake (keep `serve_weekday_polls.py` running):

```powershell
# Terminal B — keep this process alive (schedules + runs the deployments)
python scripts/serve_weekday_polls.py
```

Edit `POLL_COUNTRIES` in that script to add markets (ids from `python scripts/run_pipeline.py list`).
Restart the serve process after editing.

In the UI: **Deployments** should list `norway-weekday-poll` and `germany-weekday-poll`.
Use **Run** once to verify without waiting for cron. Flow result includes
`status: updated | unchanged | error`.

`update_and_consolidate` skips warehouse rebuild when every country is unchanged
(unless you pass `consolidate_only_if_updated=False`).

Flows call the same `pipelines.run_update_with_status` entrypoints. Prefect Cloud
is optional later (same flows + a worker).

### 5. Optional: schedule consolidation (Windows)

To refresh the warehouse nightly after update scripts finish, use Task Scheduler
or a Prefect deployment to run (adjust paths to your clone):

```powershell
cd "C:\path\to\country_oil_scraper"
python scripts\consolidate_warehouse.py
```

Run consolidate **after** any scheduled country/JODI updates so the dashboard
always reads fresh parquets.

### Warehouse layout

```
config/countries.yaml      # Enabled countries, parquet paths, Kayrros scopes
config/regions.yaml        # Multi-country presets (Europe, Asia Pacific, …)
warehouse/                 # consolidate.py, schema, country hooks, regions.py
analytics/core/            # Loaders, metrics, multi_country aggregation
apps/demand_dashboard.py   # Streamlit UI
scripts/consolidate_warehouse.py
```

## Data Sources — India (PPAC)

| Dataset | URL | Access Method | Format |
|---------|-----|---------------|--------|
| Products-wise consumption | ppac.gov.in/consumption/products-wise | AJAX (needs reverse-engineering) + direct Excel downloads | Monthly by product, '000 MT |
| State-wise consumption | ppac.gov.in/consumption/state-wise | Direct Excel download | Annual by state & product |
| PMUY connections | ppac.gov.in/consumption/state-wise-pmuy-data | Direct Excel download | State-wise LPG connections under PMUY |

### What is PMUY?

**Pradhan Mantri Ujjwala Yojana** (Prime Minister's Lightening Scheme) — launched May 2016
to provide free LPG connections to women in Below Poverty Line households. The goal was to
replace dirty cooking fuels (firewood, coal, cow dung) with clean LPG. Over 100 million
connections distributed as of early 2025. The PPAC PMUY dataset tracks state-wise connection
counts by oil marketing company (IOCL, BPCL, HPCL).

**Why it matters for oil demand:** PMUY is a major structural driver of Indian LPG demand growth.
Each new connection = a new recurring LPG consumer. Tracking PMUY penetration by state helps
explain regional LPG consumption trends and forecast future demand.

## Data Sources — Japan (METI)

| Dataset | Source | Access | Format |
|---------|--------|--------|--------|
| Domestic sales (国内向販売) | [石油統計 速報 + 確報](https://www.meti.go.jp/statistics/tyo/sekiyuka/index.html) | `curl_cffi` scraper | Monthly xlsx |

**Update (routine):** `python scripts/update_japan.py` — latest 速報 + last 6 確報 months  
**Bootstrap:** `python scripts/update_japan.py --bootstrap` (all `data/raw/japan/yearbook/h2dhhpe*.xlsx` + 確報 + 速報; history from 2013 with 年報 stitch)  
**Dashboard:** `notebooks/14_japan_demand_dashboard.ipynb`  
**Full guide:** [docs/japan_meti_guide.html](docs/japan_meti_guide.html) — 速報/確報/年報, command cookbook, product_map & JODI panels, troubleshooting.

Headline totals include **naphtha** (overall industrial + transport demand).

## Data Sources — Korea (KNOC / Petronet)

| Dataset | Source | Access | Format |
|---------|--------|--------|--------|
| 제품별소비 (product consumption) | [Petronet](https://www.petronet.co.kr/v4/sub.jsp) | Automated scrape (`scrapers/korea_knoc.py`) | Monthly CSV bundles, kbpm |

**Update (routine):** `python scripts/update_korea.py --force`  
**Dashboard:** `notebooks/13_korea_demand_dashboard.ipynb`  
**Full guide:** [docs/korea_knoc_guide.html](docs/korea_knoc_guide.html) — pipeline overview, command cookbook, notebook sections, troubleshooting.

## Data Sources — Taiwan (MOEA)

| Dataset | Source | Access | Format |
|---------|--------|--------|--------|
| 5-04 Petroleum Products Consumption (按油品別) | [E-STATE-STAT](https://ea01.moeaea.gov.tw/a0303/02/en/newest/monthly/?tab=Oil) | `curl_cffi` auto-download (`scrapers/taiwan_moea.py`) | Monthly xlsx, ktoe |

**Update (routine):** `python scripts/update_taiwan.py`  
**Bootstrap:** `python scripts/update_taiwan.py --bootstrap`  
**Dashboard:** `notebooks/16_taiwan_demand_dashboard.ipynb`

Annual rows (2007–2024) are expanded to flat monthly imputations until true monthly history is available. Headline totals include **naphtha** and other petchem lines.

## Data Sources — Hungary (MEKH)

| Dataset | Source | Access | Format |
|---------|--------|--------|--------|
| Oil balance (demand) | [HaviOlajMerleg](https://stattab.mekh.hu/#/generated-report/HaviOlajMerleg) | OData v4 API | Monthly kt, `GDINCTRO` → TOTDEMO |
| Closing stocks | [HaviOlajKeszlet](https://stattab.mekh.hu/#/generated-report/HaviOlajKeszlet) | OData v4 API | Monthly kt, `CSNATTER` → CLOSTLV |

**Update (routine):** `python scripts/update_hungary.py`  
**Bootstrap:** `python scripts/update_hungary.py --bootstrap`  
**Dashboard:** `notebooks/22_hungary_demand_dashboard.ipynb`  
**Full guide:** [docs/hungary_mekh_guide.html](docs/hungary_mekh_guide.html) — OData flows, product mapping, command cookbook, JODI/Kayrros panels, troubleshooting.

Demand uses **Gross inland deliveries (Observed)** only. LPG and Natural gas liquids are separate native products. The MEKH TAB portal is backed by a public OData API (not Power BI).

## JODI Comparison (Future)

JODI publishes monthly oil data by country in a standardised format. The idea is to:
1. Scrape granular national-source data (this project)
2. Pull the same country's JODI submission
3. Compare for discrepancies, timeliness gaps, or detail not in JODI

## Scalability Design

Adding a new country — see [ARCHITECTURE.md](ARCHITECTURE.md) for the full pattern:

1. Add source metadata to `config/sources.yaml`
2. Create `scrapers/{country}.py` — implement `download()` and `parse()`
3. Create `processors/{country}.py` — implement `load()`, `upsert()`, `save()`
4. Create `scripts/update_{country}.py` — CLI wiring
5. Add product mappings to `reference/product_map.csv`
6. (Optional) Add a prototyping notebook
