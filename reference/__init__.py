"""
reference
─────────
Project reference data + cached loaders for the canonical vocabularies.

Files in this package
---------------------
  product_map.csv      Canonical product taxonomy (Country/Source/Product_name
                       -> Category/Sub-category, with Parent_product hierarchy
                       and controlled-vocab tags in Product_details).
  metric_types.yaml    Canonical metric vocabulary (INDPROD, TOTDEMO, etc.)
                       with per-source mappings from native labels.
  loaders.py           Cached read-only Python API over the above.

Quick start
-----------
    from reference.loaders import (
        canonical_subcategory, canonical_category, canonical_metric,
        is_primary, is_aggregate, parent_product,
    )

    canonical_subcategory("HSD", source="PPAC")           # -> "Diesel"
    canonical_metric("Sales of products",
                     source="dceew_petroleum_statistics") # -> "TOTDEMO"
"""
