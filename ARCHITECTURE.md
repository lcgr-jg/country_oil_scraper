# Architecture: Scrapers, Processors, and Update Scripts

This document describes how country pipelines are structured and where new code
should live. It reflects the **intended** pattern; a few existing countries
deviate in minor ways (called out below).

## Pipeline overview

```
sources.yaml          metadata (URLs, formats, notes)
      │
      ▼
scrapers/{country}.py download() + parse()     raw file → tidy DataFrame
      │
      ▼
processors/{country}.py load / upsert / save   local DB + canonical columns
      │
      ▼
scripts/update_{country}.py                    CLI orchestration
      │
      ▼
data/raw/{country}/       downloaded files as-is
data/processed/{country}/ parquet (+ optional sqlite)
```

Production update scripts (`update_thailand.py`, `update_australia.py`, etc.)
**always go through a processor**. They do not call `BaseScraper.run()` directly.

## Layer responsibilities

### Scraper (`scrapers/{country}.py`)

Inherits from `BaseScraper`. Owns everything that talks to the **source format**.

| Method | Responsibility |
|--------|----------------|
| `download()` | Fetch raw files from the web (or API) into `data/raw/{country}/` |
| `parse(raw_path)` | Parse **one raw file** into a tidy, **source-native** DataFrame |

The scraper output schema should use columns like `product_native`, `value`, `unit`,
`source_file`, `is_provisional` — whatever the agency publishes. Do **not** add
cross-source canonical columns here.

**Re-parse without re-download:** because `download()` and `parse()` are separate,
you can iterate on parsing logic against cached raw files (`--no-download` flags
on update scripts).

### Processor (`processors/{country}.py`)

Owns everything that touches the **local database**.

| Function | Responsibility |
|----------|----------------|
| `build_from_historical()` | First-ever build from raw files (may loop multiple files) |
| `load()` | Read existing parquet from `data/processed/{country}/` |
| `upsert()` | Merge new observations into the existing DataFrame |
| `save()` | Write parquet (+ optional sqlite) |

Processors also own **canonical enrichment** — mapping native labels to shared
categories via `reference/product_map.csv` and `reference/metric_types.yaml`:

- `product_canonical` (e.g. HSD → "Diesel")
- `category` (e.g. HSD → "Distillates")

Keeping canonical mapping in the processor means you can refresh mappings by
re-running `load → save` without re-scraping or re-parsing raw files.

### Update script (`scripts/update_{country}.py`)

Thin CLI that wires scraper + processor:

1. Parse args (`--bootstrap`, `--force`, `--no-download`, …)
2. Download raw files (unless skipped)
3. Parse via scraper (directly or through processor `build_from_historical`)
4. Upsert + save via processor
5. Log summary (rows, date range, output paths)

### Config (`config/sources.yaml`)

Documents agency metadata, dataset names, URLs, access methods, and run notes.
The `country` key passed to `BaseScraper(country=...)` must match the yaml key
exactly (e.g. `"italy"` → `data/raw/italy/`).

## Rules for new countries

1. **Parsing lives in the scraper.** Processors call `scraper.parse()`, never
   duplicate Excel/CSV layout logic.
2. **Canonical mapping lives in the processor.** Scrapers stay 1:1 with the
   source file format.
3. **Multi-file bootstrap orchestration lives in the processor.** Loop over raw
   files, call `scraper.parse()` on each, concat/merge, then `save()`.
   (See JODI and India for this pattern.)
4. **One update script per country** that delegates to the processor for anything
   beyond a simple download-only phase.
5. **Register the pipeline** in `pipelines/registry.py` so
   `scripts/run_pipeline.py` and Prefect (`orchestration/flows.py`) can schedule
   it. Do not put probes in `scripts/` — use `scripts/scratch/` or notebooks.

## Scheduling entrypoints

| Layer | Role |
|-------|------|
| `scripts/update_{country}.py` | Per-source CLI (argparse, country-specific flags) |
| `pipelines/registry.py` + `runner.py` | Stable IDs → scripts; `run_update_with_status` |
| `orchestration/flows.py` | Prefect flows wrapping the runner (local first) |
| `scripts/serve_weekday_polls.py` | Serves Norway/Germany weekday poll deployments |

Poll outcomes are `updated` / `unchanged` / `error` / `unknown` (parquet fingerprint
before vs after). Production schedules should call the registry/Prefect layer, not
notebooks.

## Per-country reference

| Country | Scraper | Processor | Multi-file bootstrap |
|---------|---------|-----------|----------------------|
| India | `india_ppac.py` | `india_pt_consumption.py` | Processor loops; scraper parses one file |
| JODI | `jodi.py` | `jodi.py` | Processor `_parse_and_concat` → `scraper.parse()` per CSV |
| Australia | `australia_apstat.py` | `australia_petroleum_statistics.py` | Single xlsx has full history |
| Thailand | `thailand_eppo.py` | `thailand_eppo_sales.py` | Scraper `build_monthly_series()` stitches two workbooks *(legacy)* |
| Italy | `italy_mase.py` | `italy_mase_consumption.py` | Processor loops definitive + preliminary |
| Japan | `japan_meti.py` | `japan_meti_consumption.py` | Bootstrap 確報 index + 速報; processor loops `kakuhou/` + `sokuhou/` |
| Spain | `spain_cores.py` | `spain_cores_consumption.py` | Single xlsx has full history (1996+) |
| Hungary | `hungary_mekh.py` | `hungary_mekh_demand.py` | OData JSON snapshots (demand + stocks) |
| Ukraine | `ukraine_sssu.py` | `ukraine_sssu_fuel.py` | SDMX CSV + Data Bank wide exports |
| Norway | `norway_ssb.py` | `norway_ssb_sales.py` | StatBank API stitch 03687 + 11174 + 13585 |

### Known deviations

- **Thailand** puts multi-file stitching (`build_monthly_series`, `stitch_monthly`)
  in the scraper rather than the processor. New countries should prefer the
  processor-side loop (JODI/India style).
- **`BaseScraper.run()`** combines download → parse → save processed parquet
  without a processor. This is a convenience path for prototyping; production
  pipelines use processors instead.

## Italy Phase 2 plan (when parsing starts)

```
scrapers/italy_mase.py
  parse(raw_path)              one workbook → source-native long form

processors/italy_mase_consumption.py   (new)
  build_from_historical()      loop 24 definitive files (+ latest preliminary?)
  upsert()                     merge new preliminary month
  save() / load()              parquet persistence
  _derive_canonical_columns()  reference/product_map.csv lookup

scripts/update_italy.py
  extend beyond download-only to call processor
```

## File layout

```
country_oil_scraper/
├── config/sources.yaml
├── scrapers/
│   ├── base.py
│   ├── india_ppac.py
│   ├── jodi.py
│   ├── australia_apstat.py
│   ├── thailand_eppo.py
│   ├── italy_mase.py
│   ├── spain_cores.py
│   └── hungary_mekh.py
├── processors/
│   ├── india_pt_consumption.py
│   ├── jodi.py
│   ├── australia_petroleum_statistics.py
│   ├── thailand_eppo_sales.py
│   ├── (italy — Phase 2)
│   ├── spain_cores_consumption.py
│   └── hungary_mekh_demand.py
├── scripts/
│   ├── update_india_pt_consumption.py
│   ├── update_jodi.py
│   ├── update_australia.py
│   ├── update_thailand.py
│   ├── update_italy.py
│   ├── update_spain.py
│   └── update_hungary.py
├── reference/                 product_map.csv, metric_types.yaml, loaders
└── data/
    ├── raw/{country}/
    └── processed/{country}/
```
