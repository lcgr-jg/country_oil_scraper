-- DuckDB warehouse schema for country_oil_scraper central analysis.
-- Rebuilt by warehouse/consolidate.py from country parquets + JODI + Kayrros.

CREATE TABLE IF NOT EXISTS fact_observations (
    country_code       VARCHAR NOT NULL,
    country_name       VARCHAR,
    scope_type         VARCHAR NOT NULL DEFAULT 'country',
    date               DATE NOT NULL,
    source             VARCHAR NOT NULL,
    source_tier        VARCHAR NOT NULL,
    metric_type        VARCHAR NOT NULL,
    product_native     VARCHAR NOT NULL DEFAULT '',
    product_canonical  VARCHAR,
    category           VARCHAR,
    compare_panel      VARCHAR,
    value_native       DOUBLE,
    unit_native        VARCHAR,
    value_kbd          DOUBLE,
    is_provisional     BOOLEAN,
    ingested_at        TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS fact_revisions (
    country_code       VARCHAR NOT NULL,
    source             VARCHAR NOT NULL,
    metric_type        VARCHAR NOT NULL,
    product_native     VARCHAR NOT NULL DEFAULT '',
    product_canonical  VARCHAR,
    date               DATE NOT NULL,
    prior_value_kbd    DOUBLE,
    new_value_kbd      DOUBLE,
    revision_pct       DOUBLE,
    detected_at        TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS fact_divergences (
    country_code       VARCHAR NOT NULL,
    product_canonical  VARCHAR NOT NULL,
    official_source    VARCHAR NOT NULL,
    benchmark_source   VARCHAR NOT NULL,
    date               DATE NOT NULL,
    divergence_type    VARCHAR NOT NULL,
    gap_pct            DOUBLE,
    gap_change_pp      DOUBLE,
    message            VARCHAR,
    detected_at        TIMESTAMP DEFAULT current_timestamp
);

-- Convenience views for the dashboard (recreated on each consolidate).
CREATE OR REPLACE VIEW v_official_demand AS
SELECT *
FROM fact_observations
WHERE source_tier = 'official'
  AND metric_type = 'TOTDEMO';

CREATE OR REPLACE VIEW v_benchmark_demand AS
SELECT *
FROM fact_observations
WHERE source_tier IN ('benchmark', 'satellite')
  AND metric_type = 'TOTDEMO';
