"""
Divergence notes — structural methodology gaps vs episodic shifts.

Persistent Kayrros/JODI level differences are often expected (coverage,
definitions). We flag only when a gap *changes* materially or when official
data revises — not when levels differ from a benchmark by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from analytics.core.comparisons import median_gap_pct
from warehouse.registry import load_divergence_baselines


@dataclass(frozen=True)
class DivergenceNote:
    country_code: str
    product_canonical: str
    official_source: str
    benchmark_source: str
    divergence_type: str  # structural | episodic_revision | episodic_gap_shift
    date: Optional[pd.Timestamp]
    gap_pct: Optional[float]
    gap_change_pp: Optional[float]
    message: str


def structural_notes(country_code: str) -> list[DivergenceNote]:
    """Known methodology gaps from config (informational only)."""
    notes: list[DivergenceNote] = []
    for row in load_divergence_baselines():
        if str(row.get("country_code")) != country_code:
            continue
        notes.append(
            DivergenceNote(
                country_code=country_code,
                product_canonical=str(row.get("product_canonical", "")),
                official_source=str(row.get("official_source", "official")),
                benchmark_source=str(row.get("benchmark_source", "benchmark")),
                divergence_type="structural",
                date=None,
                gap_pct=row.get("gap_pct"),
                gap_change_pp=None,
                message=str(
                    row.get(
                        "note",
                        "Known methodology difference between sources — not a data error.",
                    )
                ),
            )
        )
    return notes


def detect_episodic_divergences(
    country_code: str,
    official: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    product_canonical: str,
    official_source: str,
    benchmark_source: str,
    ref_date: pd.Timestamp,
    gap_shift_threshold_pp: float = 5.0,
    revision_threshold_pct: float = 5.0,
    baseline_months: int = 12,
) -> list[DivergenceNote]:
    """
    Flag when a cross-source gap widens vs its recent median, or official revises.

    Does not treat a stable level gap as an error.
    """
    notes: list[DivergenceNote] = []

    off = official.sort_values("date")
    bench = benchmark.sort_values("date")

    hist_median = median_gap_pct(off, bench, months=baseline_months)
    if hist_median is not None:
        at_ref_off = off[off["date"] == ref_date]
        at_ref_bench = bench[bench["date"] == ref_date]
        if not at_ref_off.empty and not at_ref_bench.empty:
            o = float(at_ref_off["value_kbd"].iloc[-1])
            b = float(at_ref_bench["value_kbd"].iloc[-1])
            if b != 0:
                current_gap = (o - b) / b * 100
                shift = current_gap - hist_median
                if abs(shift) >= gap_shift_threshold_pp:
                    notes.append(
                        DivergenceNote(
                            country_code=country_code,
                            product_canonical=product_canonical,
                            official_source=official_source,
                            benchmark_source=benchmark_source,
                            divergence_type="episodic_gap_shift",
                            date=ref_date,
                            gap_pct=current_gap,
                            gap_change_pp=shift,
                            message=(
                                f"{benchmark_source} vs {official_source} gap moved "
                                f"{shift:+.1f} pp vs {baseline_months}m median "
                                f"(current {current_gap:+.1f}%, median {hist_median:+.1f}%) — "
                                "worth a closer look; may still reflect methodology."
                            ),
                        )
                    )

    # Official revision vs prior published month (same source).
    at = off[off["date"] == ref_date]
    if not at.empty:
        level = float(at["value_kbd"].iloc[-1])
        # If warehouse had prior snapshot we'd compare; use MoM vs stored prior as proxy.
        prior = off[off["date"] == ref_date - pd.DateOffset(months=1)]
        if not prior.empty:
            prev = float(prior["value_kbd"].iloc[-1])
            if prev != 0:
                rev_pct = (level / prev - 1) * 100
                # Large MoM alone isn't revision — skip unless we detect duplicate dates.
                # For monthly demand, flag large YoY-style restatements via 12m compare.
                prior_y = off[off["date"] == ref_date - pd.DateOffset(months=12)]
                if not prior_y.empty:
                    py = float(prior_y["value_kbd"].iloc[-1])
                    if py != 0:
                        yoy = (level / py - 1) * 100
                        if abs(yoy) >= revision_threshold_pct * 2:
                            notes.append(
                                DivergenceNote(
                                    country_code=country_code,
                                    product_canonical=product_canonical,
                                    official_source=official_source,
                                    benchmark_source=benchmark_source,
                                    divergence_type="episodic_revision",
                                    date=ref_date,
                                    gap_pct=yoy,
                                    gap_change_pp=None,
                                    message=(
                                        f"{official_source} {product_canonical} YoY "
                                        f"{yoy:+.1f}% at {ref_date:%Y-%m} — check for "
                                        "revisions or one-off demand events."
                                    ),
                                )
                            )

    return notes


def format_divergence_notes(notes: list[DivergenceNote]) -> pd.DataFrame:
    if not notes:
        return pd.DataFrame(
            columns=[
                "type",
                "product",
                "sources",
                "date",
                "gap_pct",
                "message",
            ]
        )
    return pd.DataFrame(
        [
            {
                "type": n.divergence_type,
                "product": n.product_canonical,
                "sources": f"{n.official_source} vs {n.benchmark_source}",
                "date": n.date.strftime("%Y-%m") if n.date is not None else "—",
                "gap_pct": n.gap_pct,
                "message": n.message,
            }
            for n in notes
        ]
    )
