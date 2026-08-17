"""Rule-based trading implications from computed demand metrics."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def build_trading_notes(
    change_table: pd.DataFrame,
    *,
    country_name: str,
    ref_month: pd.Timestamp,
    yoy_accel_threshold: float = 2.0,
    yoy_decel_threshold: float = -2.0,
    diesel_products: Iterable[str] = ("Diesel", "Auto diesel (dutiable)", "Auto diesel (free)"),
    gasoline_products: Iterable[str] = ("Gasoline", "Motor gasoline"),
) -> list[str]:
    """
    Translate MoM/YoY table into short market-relevant bullets.

    Deliberately conservative — flags direction, not price calls.
    """
    if change_table.empty:
        return [f"{country_name}: insufficient data for {ref_month:%Y-%m}."]

    notes: list[str] = []
    total_row = change_table[change_table["product"].str.contains("Total", case=False, na=False)]
    if not total_row.empty:
        yoy = float(total_row["yoy_pct"].iloc[0])
        if pd.notna(yoy):
            if yoy >= yoy_accel_threshold:
                notes.append(
                    f"Total demand YoY +{yoy:.1f}% — growth running above flat/slow baseline."
                )
            elif yoy <= yoy_decel_threshold:
                notes.append(
                    f"Total demand YoY {yoy:.1f}% — deceleration vs prior year."
                )

    diesel_set = set(diesel_products)
    gas_set = set(gasoline_products)

    for _, row in change_table.iterrows():
        product = str(row["product"])
        yoy = row.get("yoy_pct")
        mom = row.get("mom_pct")
        if product.startswith("Total") or pd.isna(yoy):
            continue

        if product in diesel_set or "diesel" in product.lower():
            if yoy <= yoy_decel_threshold:
                notes.append(
                    f"Diesel ({product}) YoY {yoy:.1f}% — watch industrial/ freight indicators."
                )
            elif yoy >= yoy_accel_threshold:
                notes.append(
                    f"Diesel ({product}) YoY +{yoy:.1f}% — firm distillate demand signal."
                )
        if product in gas_set or "gasoline" in product.lower():
            if pd.notna(mom) and abs(mom) >= 5:
                notes.append(
                    f"Gasoline ({product}) MoM {mom:+.1f}% — check seasonal vs structural."
                )

    if not notes:
        notes.append(
            f"{country_name} ({ref_month:%Y-%m}): no strong trend signals in headline products."
        )
    return notes
