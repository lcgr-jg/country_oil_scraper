"""Australia CLOSTLV stock-sheet labels must map in product_map.csv."""

from __future__ import annotations

from reference.loaders import canonical_category, canonical_subcategory

STOCK_SHEET_LABELS: dict[str, tuple[str | None, str | None]] = {
    "Diesel oil": ("Distillates", "Diesel"),
    "Automotive gasoline": ("Gasoline", "Gasoline"),
    "Aviation turbine fuel": ("Kerosene", "Jet Fuel"),
    "LPG": ("LPG", "LPG"),
    "Lubricating oils, greases & basestocks": ("Heavy byproducts", "Lubricants / Grease"),
}


def test_australia_clostlv_stock_labels_map_to_canonical() -> None:
    source = "DCCEEW"
    for label, (cat, sub) in STOCK_SHEET_LABELS.items():
        assert canonical_subcategory(label, source=source) == sub
        assert canonical_category(label, source=source) == cat


def test_australia_clostlv_out_of_scope_aggregates_unmapped() -> None:
    source = "DCCEEW"
    for label in (
        "Crude oil and refinery feedstocks",
        "Total stocks COE",
    ):
        assert canonical_subcategory(label, source=source) is None
        assert canonical_category(label, source=source) is None
