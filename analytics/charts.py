"""
analytics.charts
────────────────
Reusable plotly chart builders for country-oil dashboards.

Why this exists
---------------
The seasonality-by-calendar-year and cross-source comparison charts are
exactly the same shape regardless of country: small multiples, one panel
per product, with the variations being which years/sources to colour.
Putting them here means India, Australia, and any future country
dashboard share the same code path.

Public API
----------
  seasonality_by_year_chart(df, products, ...) -> plotly.graph_objects.Figure
      Small multiples of monthly values, one panel per product, one line
      per calendar year. Most recent year highlighted.

  cross_source_comparison_chart(df_a, df_b, products, ...) -> Figure
      Small multiples of one product per panel, with two lines (the two
      sources) overlaid. Unit alignment is the caller's responsibility.

Both functions:
  - Are PURE: no global state, no notebook references, no I/O.
  - Take long-form DataFrames (one row per date+product+...).
  - Return a plotly.graph_objects.Figure that the caller can .show(),
    .write_html(), or further customise.
"""
from __future__ import annotations

from typing import Literal, Mapping, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Default plotly colour cycle. Set once so both chart functions stay visually
# consistent across the dashboard.
_DEFAULT_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _grid_dims(n: int, cols: int) -> tuple[int, int]:
    """Compute (rows, cols) for a small-multiples grid of n panels.

    Why we wrap this in a helper: makes it trivial to switch the layout
    later (e.g. force 3 cols on wide displays) by editing one place.
    """
    rows = (n + cols - 1) // cols
    return rows, cols


# --------------------------------------------------------------------------- #
#  Seasonality by calendar year
# --------------------------------------------------------------------------- #

def seasonality_by_year_chart(
    df: pd.DataFrame,
    products: Sequence[str],
    *,
    value_col: str = "value",
    date_col: str = "date",
    product_col: str = "product_native",
    cols: int = 2,
    title: Optional[str] = None,
    highlight_year: Optional[int] = None,
    highlight_color: str = "#d62728",  # red
    default_visible_prior_years: Optional[int] = None,
    product_labels: Optional[Mapping[str, str]] = None,
    other_palette: Sequence[str] = ("#90c2e7", "#b3a2c7", "#a8dba8", "#f4b183", "#bdbdbd"),
    panel_height: int = 280,
    units_label: str = "",
) -> go.Figure:
    """Build a small-multiples seasonality chart, one panel per product.

    For each product, draws one line per calendar year present in the data,
    plotted against the calendar month (Jan…Dec). The most recent year (or
    a year you pass in ``highlight_year``) is drawn thicker and in a
    contrasting colour so the eye is drawn to "what's happening THIS year
    vs the historical pattern".

    Parameters
    ----------
    df : long-form DataFrame
        Must contain ``date_col``, ``product_col``, ``value_col``.
        Dates should be at monthly granularity (the function aggregates by
        year+month internally, so daily input also works).
    products : sequence of product labels
        Which products to show, in the panel order desired. One subplot
        per product, top-to-bottom then left-to-right.
    value_col, date_col, product_col : str
        Column names in ``df``. Defaults match the canonical schema.
    cols : int
        Number of columns in the small-multiples grid.
    title : str, optional
        Figure title.
    highlight_year : int, optional
        Which calendar year to bold-and-colour. Defaults to the most
        recent year in the data.
    default_visible_prior_years : int, optional
        When set, only the most recent *N* calendar years before
        ``highlight_year``, plus ``highlight_year`` itself, are shown by
        default. Older years remain in the legend and can be toggled on
        (Plotly ``visible='legendonly'``).
    product_labels : mapping, optional
        Display names for subplot titles and hovers, keyed by the values
        in ``products`` / ``product_col`` (e.g. canonical product names).
    highlight_color : str
        Colour for the highlighted year. Defaults to red so it pops.
    other_palette : sequence of colours
        Colour cycle for all other years. Cycles per panel if you have
        more years than colours.
    panel_height : int
        Height in pixels per row of the grid.
    units_label : str
        Y-axis label (e.g. "ML", "kt"). The chart is unit-agnostic; this
        is just a string for the axis.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    if not products:
        raise ValueError("Need at least one product to plot.")
    if any(c not in df.columns for c in (value_col, date_col, product_col)):
        missing = [c for c in (value_col, date_col, product_col) if c not in df.columns]
        raise KeyError(f"Missing required columns: {missing}")

    # Work on a copy so we can attach year/month without mutating the caller's df.
    work = df[df[product_col].isin(products)].copy()
    work[date_col] = pd.to_datetime(work[date_col])
    work["__year"] = work[date_col].dt.year
    work["__month"] = work[date_col].dt.month

    # Aggregate to (product, year, month). If the input is already monthly
    # this is a no-op; if it's daily this gives us the monthly total.
    work = (
        work.groupby([product_col, "__year", "__month"])[value_col]
        .sum(min_count=1)  # min_count=1 so an all-NaN group stays NaN, not 0
        .reset_index()
    )

    if highlight_year is None:
        highlight_year = int(work["__year"].max())

    if default_visible_prior_years is not None:
        if default_visible_prior_years < 0:
            raise ValueError("default_visible_prior_years must be >= 0")
        default_visible = set(
            range(highlight_year - default_visible_prior_years, highlight_year + 1)
        )
    else:
        default_visible = None

    years_sorted = sorted(work["__year"].unique())
    rows, cols = _grid_dims(len(products), cols)

    panel_titles = [
        (product_labels.get(product, product) if product_labels else product)
        for product in products
    ]

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=panel_titles,
        shared_xaxes=False,
        vertical_spacing=0.10,
        horizontal_spacing=0.08,
    )

    # We want each year to appear in the legend ONCE, not once per panel.
    # plotly's legendgroup + showlegend-only-on-first-panel pattern handles
    # this. Track which legendgroups we've already shown.
    seen_legend: set[int] = set()

    for idx, product in enumerate(products):
        r = idx // cols + 1
        c = idx % cols + 1
        sub = work[work[product_col] == product]
        panel_label = panel_titles[idx]

        for year_idx, year in enumerate(years_sorted):
            ydata = sub[sub["__year"] == year].sort_values("__month")
            if ydata.empty:
                continue

            is_highlight = year == highlight_year
            if is_highlight:
                line = dict(color=highlight_color, width=3)
            else:
                colour = other_palette[year_idx % len(other_palette)]
                line = dict(color=colour, width=1.4)

            show_legend = year not in seen_legend
            if show_legend:
                seen_legend.add(year)

            if default_visible is None:
                trace_visible: bool | str = True
            else:
                trace_visible = True if year in default_visible else "legendonly"

            fig.add_trace(
                go.Scatter(
                    x=ydata["__month"],
                    y=ydata[value_col],
                    mode="lines+markers",
                    name=str(year),
                    legendgroup=str(year),
                    showlegend=show_legend,
                    visible=trace_visible,
                    line=line,
                    marker=dict(size=5),
                    hovertemplate=(
                        f"<b>{panel_label}</b><br>"
                        f"Year: {year}<br>"
                        "Month: %{x}<br>"
                        f"{value_col}: %{{y:,.1f}} {units_label}<extra></extra>"
                    ),
                ),
                row=r, col=c,
            )

    # Force calendar-month tick labels on every panel, not just the first.
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(1, 13)),
        ticktext=month_labels,
    )
    if units_label:
        fig.update_yaxes(title_text=units_label)

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=panel_height * rows,
        hovermode="closest",
        legend=dict(orientation="h", y=-0.06, yanchor="top", x=0.5, xanchor="center",
                    title_text="Calendar year"),
        margin=dict(t=70, l=60, r=20, b=60),
    )
    return fig


# --------------------------------------------------------------------------- #
#  Cross-source comparison
# --------------------------------------------------------------------------- #

def cross_source_comparison_chart(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    products: Sequence[str],
    *,
    label_a: str = "Source A",
    label_b: str = "Source B",
    value_col_a: str = "value",
    value_col_b: str = "value",
    date_col_a: str = "date",
    date_col_b: str = "date",
    product_col_a: str = "product_native",
    product_col_b: str = "product_native",
    color_a: str = "#1f77b4",  # blue
    color_b: str = "#ff7f0e",  # orange
    cols: int = 2,
    title: Optional[str] = None,
    panel_height: int = 280,
    units_label: str = "",
) -> go.Figure:
    """Build a small-multiples cross-source comparison chart.

    For each product, draws two lines: one for source A, one for source B.
    Use this to spot discrepancies between agencies that supposedly report
    the same flow (e.g. national stat office vs JODI).

    The caller is responsible for:
      - Filtering each frame to the same metric (e.g. both TOTDEMO).
      - Aligning units (e.g. both already in kL).
      - Using the SAME product labels in both frames, or providing
        ``product_col_a`` / ``product_col_b`` that resolve to matching
        values per panel.

    Parameters
    ----------
    df_a, df_b : long-form DataFrames
        Source A and source B data. Each must have its own value/date/
        product columns (defaults assume the canonical schema in both).
    products : sequence of str
        Product labels that exist in BOTH frames (matching on
        ``product_col_a`` / ``product_col_b`` respectively). One panel per.
    label_a, label_b : str
        Display names for the two sources in the legend.
    value_col_a, value_col_b : str
        Numeric column name in each frame.
    date_col_a, date_col_b : str
        Date column name in each frame.
    product_col_a, product_col_b : str
        Product label column in each frame. If A and B label the same
        product differently, the caller should add a join column with
        matching values upstream (see notebook section 9 for an example).
    color_a, color_b : str
        Plotly colour codes for the two lines.
    cols : int
        Columns in the small-multiples grid.
    title : str, optional
    panel_height : int
        Height per row of the grid.
    units_label : str
        Y-axis label.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    if not products:
        raise ValueError("Need at least one product to plot.")

    rows, cols = _grid_dims(len(products), cols)
    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=list(products),
        shared_xaxes=False,
        vertical_spacing=0.10,
        horizontal_spacing=0.08,
    )

    first = True
    for idx, product in enumerate(products):
        r = idx // cols + 1
        c = idx % cols + 1

        sub_a = df_a[df_a[product_col_a] == product].sort_values(date_col_a)
        sub_b = df_b[df_b[product_col_b] == product].sort_values(date_col_b)

        fig.add_trace(
            go.Scatter(
                x=sub_a[date_col_a], y=sub_a[value_col_a],
                mode="lines", name=label_a,
                legendgroup=label_a,
                showlegend=first,
                line=dict(color=color_a, width=1.6),
                hovertemplate=(
                    f"<b>{product} — {label_a}</b><br>"
                    "%{x|%Y-%m}: %{y:,.1f}"
                    + (f" {units_label}" if units_label else "")
                    + "<extra></extra>"
                ),
            ),
            row=r, col=c,
        )
        fig.add_trace(
            go.Scatter(
                x=sub_b[date_col_b], y=sub_b[value_col_b],
                mode="lines", name=label_b,
                legendgroup=label_b,
                showlegend=first,
                line=dict(color=color_b, width=1.6),
                hovertemplate=(
                    f"<b>{product} — {label_b}</b><br>"
                    "%{x|%Y-%m}: %{y:,.1f}"
                    + (f" {units_label}" if units_label else "")
                    + "<extra></extra>"
                ),
            ),
            row=r, col=c,
        )
        first = False

    if units_label:
        fig.update_yaxes(title_text=units_label)

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=panel_height * rows,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.06, yanchor="top", x=0.5, xanchor="center"),
        margin=dict(t=70, l=60, r=20, b=60),
    )
    return fig


# --------------------------------------------------------------------------- #
#  Cross-source levels + gap (two-panel, single product)
# --------------------------------------------------------------------------- #

def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Expand `#rrggbb` to an `rgba(r,g,b,a)` string for plotly fill colours.

    Plotly accepts hex codes for `line.color` but not for a partial-opacity
    `fillcolor`, so we expand on demand. Non-hex inputs (named colours, rgba
    strings) are returned unchanged so the caller can still override.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def cross_source_gap_chart(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    *,
    label_a: str,
    label_b: str,
    value_col_a: str = "value",
    value_col_b: str = "value",
    date_col_a: str = "date",
    date_col_b: str = "date",
    gap_direction: Literal["a_minus_b", "b_minus_a"] = "a_minus_b",
    color_a: str = "#1f77b4",  # blue
    color_b: str = "#ff7f0e",  # orange
    gap_color: str = "#2ca02c",  # green
    gap_fill_alpha: float = 0.15,
    title: Optional[str] = None,
    units_label: str = "",
    height: int = 600,
    width: Optional[int] = None,
    levels_panel_fraction: float = 0.6,
    gap_default: Literal["abs", "pct"] = "abs",
) -> go.Figure:
    """Two-panel comparison: levels (both sources) on top, gap on bottom.

    Use this when you want to QUANTIFY the difference between two sources,
    not just visualise that they "roughly track". The gap panel exposes
    persistence, sign, and magnitude in one view. An interactive
    `[Absolute] [Percent]` toggle in the top-left of the chart lets the
    viewer flip the gap panel between the inputs' native unit and a
    percentage-of-benchmark view live — useful when the absolute level
    shifts by 5–10x over the time range (a flat absolute gap can hide a
    steady percentage gap, and vice versa).

    Unit alignment is the CALLER's responsibility (same policy as
    `cross_source_comparison_chart`): pre-convert both frames to the same
    unit before calling.

    Parameters
    ----------
    df_a, df_b : long-form DataFrames
        Source A and source B time series. Each must contain its own date
        and value columns. The function inner-joins on date for the gap
        computation but plots each source over its OWN full range on the
        top panel, so the viewer can see where each begins / ends.
    label_a, label_b : str
        Display names used in the legend, hover text, panel titles, and
        toggle buttons.
    value_col_a, value_col_b : str
        Numeric column name in each frame (defaults to ``"value"``).
    date_col_a, date_col_b : str
        Date column name in each frame (defaults to ``"date"``).
    gap_direction : 'a_minus_b' | 'b_minus_a'
        Sign convention for the gap series. The denominator for the
        percentage view is always the *second* (subtrahend) source — the
        "benchmark" you are diffing against:
          - ``'a_minus_b'`` → gap = A − B, pct = (A − B) / B × 100
          - ``'b_minus_a'`` → gap = B − A, pct = (B − A) / A × 100
    color_a, color_b, gap_color : str
        Hex colour codes. ``gap_color`` is also used (with reduced alpha)
        for the filled area under the gap series.
    gap_fill_alpha : float
        Alpha for the gap area fill (0–1). 0.15 is light enough not to
        overwhelm the line.
    title : str, optional
        Figure title.
    units_label : str
        Y-axis label for the levels panel and the absolute-mode gap panel
        (e.g. ``"kbd"``, ``"kt"``, ``"ML"``). The chart is otherwise unit-
        agnostic.
    height : int
        Total figure height in pixels.
    width : int, optional
        Figure width. ``None`` lets plotly use the container width
        (responsive).
    levels_panel_fraction : float
        Vertical fraction allocated to the levels panel; 0.6 puts the gap
        panel at 40% of the height, matching the reference style.
    gap_default : 'abs' | 'pct'
        Which view the gap panel shows on first render. The toggle buttons
        let the viewer change it without re-rendering.

    Returns
    -------
    plotly.graph_objects.Figure
        Two-row subplot with `[Absolute] [Percent]` toggle buttons.
        Caller is responsible for ``.show()`` / ``.write_html()``.

    Examples
    --------
    >>> fig = cross_source_gap_chart(
    ...     dcceew_jet, nowcaster,
    ...     label_a="DCCEEW (official)", label_b="Kayrros nowcaster",
    ...     value_col_a="kbd", value_col_b="kbd",
    ...     gap_direction="b_minus_a",   # nowcaster − official
    ...     units_label="kbd",
    ...     title="Australia jet fuel: DCCEEW vs Kayrros nowcaster",
    ... )
    >>> fig.show()
    """
    # Normalise inputs into a common (date, a) / (date, b) shape, then
    # inner-join for the gap. Each frame keeps its full date range for the
    # top panel — the viewer sees where each source begins / ends.
    a = (
        df_a[[date_col_a, value_col_a]]
        .rename(columns={date_col_a: "date", value_col_a: "a"})
        .copy()
    )
    b = (
        df_b[[date_col_b, value_col_b]]
        .rename(columns={date_col_b: "date", value_col_b: "b"})
        .copy()
    )
    a["date"] = pd.to_datetime(a["date"])
    b["date"] = pd.to_datetime(b["date"])
    overlap = (
        a.merge(b, on="date", how="inner")
        .sort_values("date").reset_index(drop=True)
    )

    if gap_direction == "a_minus_b":
        gap_abs = overlap["a"] - overlap["b"]
        denom = overlap["b"]
        gap_text = f"{label_a} − {label_b}"
        denom_label = label_b
    elif gap_direction == "b_minus_a":
        gap_abs = overlap["b"] - overlap["a"]
        denom = overlap["a"]
        gap_text = f"{label_b} − {label_a}"
        denom_label = label_a
    else:
        raise ValueError(
            f"gap_direction must be 'a_minus_b' or 'b_minus_a', "
            f"got {gap_direction!r}"
        )

    # Percent of the benchmark. Explicit zero-mask avoids divide-by-zero
    # warnings and just yields NaN on those rows (the chart skips them).
    gap_pct = (gap_abs / denom.where(denom != 0)) * 100.0

    # Subplot titles. We swap the gap one via updatemenus when the mode
    # toggles, so build both versions up front.
    unit_suffix = f" — {units_label}" if units_label else ""
    levels_title = f"{label_a} vs {label_b}{unit_suffix}"
    gap_title_abs = f"Gap ({gap_text}){unit_suffix}"
    gap_title_pct = f"Gap ({gap_text}) — % of {denom_label}"

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=(
            levels_title,
            gap_title_abs if gap_default == "abs" else gap_title_pct,
        ),
        row_heights=[levels_panel_fraction, 1.0 - levels_panel_fraction],
    )

    # ── Top panel: full ranges of each source ──────────────────────────
    fig.add_trace(
        go.Scatter(
            x=a["date"], y=a["a"], mode="lines", name=label_a,
            line=dict(color=color_a, width=1.6),
            hovertemplate=(
                f"<b>{label_a}</b><br>%{{x|%Y-%m}}: %{{y:,.2f}}"
                + (f" {units_label}" if units_label else "")
                + "<extra></extra>"
            ),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=b["date"], y=b["b"], mode="lines", name=label_b,
            line=dict(color=color_b, width=1.6),
            hovertemplate=(
                f"<b>{label_b}</b><br>%{{x|%Y-%m}}: %{{y:,.2f}}"
                + (f" {units_label}" if units_label else "")
                + "<extra></extra>"
            ),
        ),
        row=1, col=1,
    )

    # ── Bottom panel: gap series with filled area + zero baseline. ──────
    # customdata carries BOTH abs and pct so hover always shows both
    # regardless of which view is currently active — the toggle only
    # changes the primary visual; the secondary number is one hover away.
    custom = list(zip(gap_abs.tolist(), gap_pct.tolist()))
    abs_unit_tag = f" {units_label}" if units_label else ""
    gap_hover = (
        f"<b>{gap_text}</b><br>%{{x|%Y-%m}}<br>"
        f"  abs : %{{customdata[0]:+,.2f}}{abs_unit_tag}<br>"
        f"  pct : %{{customdata[1]:+,.2f}}%<extra></extra>"
    )

    gap_trace_idx = len(fig.data)  # index of the gap trace we add next
    fig.add_trace(
        go.Scatter(
            x=overlap["date"],
            y=gap_abs if gap_default == "abs" else gap_pct,
            mode="lines", name=gap_text,
            line=dict(color=gap_color, width=1.4),
            fill="tozeroy",
            fillcolor=_hex_to_rgba(gap_color, gap_fill_alpha),
            showlegend=False,
            customdata=custom,
            hovertemplate=gap_hover,
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0, line_color="black", line_width=1, row=2, col=1)

    if units_label:
        fig.update_yaxes(title_text=units_label, row=1, col=1)
    fig.update_yaxes(
        title_text=(units_label if gap_default == "abs" else "%"),
        row=2, col=1,
    )

    # ── Interactive toggle: [Absolute] [Percent] ───────────────────────
    # method='update' lets us swap both trace y/hovertemplate AND layout
    # pieces (yaxis2 title, the gap subplot title) in a single click.
    # make_subplots stores subplot titles as layout annotations in order,
    # so the gap subplot title is annotations[1].
    abs_btn = dict(
        label=f"Absolute{' (' + units_label + ')' if units_label else ''}",
        method="update",
        args=[
            {"y": [gap_abs.tolist()]},
            {
                "yaxis2.title.text": units_label,
                "annotations[1].text": gap_title_abs,
            },
            [gap_trace_idx],
        ],
    )
    pct_btn = dict(
        label="Percent",
        method="update",
        args=[
            {"y": [gap_pct.tolist()]},
            {
                "yaxis2.title.text": "%",
                "annotations[1].text": gap_title_pct,
            },
            [gap_trace_idx],
        ],
    )

    fig.update_layout(
        # Title is centred so it doesn't collide with the top-left toggle
        # buttons or the top-right legend. Three distinct horizontal anchors
        # (left/centre/right) give each element its own band.
        title=dict(text=title, x=0.5, xanchor="center", y=0.98, yanchor="top"),
        template="plotly_white",
        height=height,
        width=width,
        hovermode="x unified",
        legend=dict(
            orientation="h", y=1.02, yanchor="bottom", x=1.0, xanchor="right",
        ),
        margin=dict(t=100, l=60, r=20, b=60),  # +10px so the centred title has breathing room
        updatemenus=[
            dict(
                type="buttons",
                direction="right",
                buttons=[abs_btn, pct_btn],
                active=0 if gap_default == "abs" else 1,
                x=0.0, xanchor="left",
                y=1.10, yanchor="bottom",
                showactive=True,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#cccccc",
                font=dict(size=11),
            ),
        ],
    )
    return fig
