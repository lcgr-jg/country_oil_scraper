"""Export dashboard snapshot (current filters + visible charts) to self-contained HTML."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any, Literal, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go

PlotlyJsMode = Literal["inline", "cdn"]

# Match Plotly default qualitative palette (also used in analytics.charts).
_DEFAULT_PALETTE: tuple[str, ...] = (
    "#636efa",
    "#EF553B",
    "#00cc96",
    "#ab63fa",
    "#FFA15A",
    "#19d3f3",
    "#FF6692",
    "#B6E880",
    "#FF97FF",
    "#FECB52",
)


def prepare_figure_for_static_export(fig: go.Figure) -> go.Figure:
    """
    Bake explicit trace colors and plain array serialization for standalone HTML.

    Streamlit can mutate figures after ``st.plotly_chart`` (clearing line colors
    so they rely on runtime theming). Subplot traces without ``line.color`` also
    default to black outside the app. This makes export match in-app appearance.
    """
    export_fig = go.Figure(fig)

    colorway = _resolve_colorway(export_fig)
    export_fig.update_layout(template="plotly_white", colorway=list(colorway))

    for idx, trace in enumerate(export_fig.data):
        color = _trace_color(trace, idx, colorway)
        trace_type = getattr(trace, "type", "") or ""

        if trace_type in ("bar", "histogram", "funnel", "waterfall"):
            marker_obj = getattr(trace, "marker", None)
            marker_color = getattr(marker_obj, "color", None) if marker_obj else None
            if not _has_per_point_colors(marker_color):
                trace.update(marker=dict(color=color))
        else:
            line_obj = getattr(trace, "line", None)
            width = getattr(line_obj, "width", None) if line_obj is not None else None
            marker_obj = getattr(trace, "marker", None)
            marker_size = getattr(marker_obj, "size", None) if marker_obj else None
            trace.update(
                line=dict(color=color, width=width if width else 2),
                marker=dict(
                    color=color,
                    size=marker_size if marker_size else 6,
                    line=dict(width=0),
                ),
            )

        # Coerce coordinates to plain lists — avoids opaque binary blobs in HTML.
        for axis in ("x", "y", "z"):
            vals = getattr(trace, axis, None)
            if vals is not None:
                setattr(trace, axis, _tolist(vals))

    return export_fig


def _resolve_colorway(fig: go.Figure) -> tuple[str, ...]:
    layout_cw = fig.layout.colorway
    if layout_cw:
        colors = [str(c) for c in layout_cw if c and not _is_missing_color(str(c))]
        if colors:
            return tuple(colors)
    return _DEFAULT_PALETTE


def _trace_color(trace: Any, idx: int, colorway: tuple[str, ...]) -> str:
    candidates: list[Any] = []
    line_obj = getattr(trace, "line", None)
    if line_obj is not None and getattr(line_obj, "color", None) is not None:
        candidates.append(line_obj.color)
    marker_obj = getattr(trace, "marker", None)
    if marker_obj is not None and getattr(marker_obj, "color", None) is not None:
        mc = marker_obj.color
        if isinstance(mc, str):
            candidates.append(mc)
    for color in candidates:
        if isinstance(color, str) and not _is_missing_color(color):
            return color
    return colorway[idx % len(colorway)]


def _has_per_point_colors(marker_color: Any) -> bool:
    """True when marker colors are already set per bar/point (do not overwrite)."""
    if marker_color is None:
        return False
    if isinstance(marker_color, str):
        return False
    if isinstance(marker_color, (list, tuple)):
        return len(marker_color) > 0
    return hasattr(marker_color, "__len__") and not isinstance(marker_color, str)


def _is_missing_color(color: str) -> bool:
    c = color.strip().lower().replace(" ", "")
    return c in {
        "",
        "black",
        "#000",
        "#000000",
        "rgb(0,0,0)",
        "rgba(0,0,0,1)",
        "rgba(0,0,0,1.0)",
    }


def _tolist(values: Any) -> list[Any]:
    if isinstance(values, pd.Series):
        values = values.tolist()
    elif hasattr(values, "tolist"):
        values = values.tolist()
    else:
        values = list(values)
    out: list[Any] = []
    for v in values:
        if isinstance(v, pd.Timestamp):
            out.append(v.isoformat())
        else:
            out.append(v)
    return out


def snapshot_to_html(
    *,
    title: str,
    subtitle: str = "",
    figures: Sequence[go.Figure],
    tables: Optional[dict[str, pd.DataFrame]] = None,
    notes: Optional[Sequence[str]] = None,
    meta: Optional[dict[str, str]] = None,
    plotlyjs_mode: PlotlyJsMode = "inline",
) -> str:
    """
    Build a standalone HTML document from Plotly figures and optional tables.

    plotlyjs_mode
    ---------------
    ``inline`` (default): embed matching plotly.js from the installed package.
    ``cdn``: load plotly.js from CDN (smaller file; needs network access).
    """
    tables = tables or {}
    notes = list(notes or [])
    meta = meta or {}

    generated = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'/>",
        f"<title>{escape(title)}</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; margin: 24px; max-width: 1200px; }",
        "h1 { margin-bottom: 0.25rem; }",
        ".subtitle { color: #555; margin-bottom: 1.5rem; }",
        ".meta { font-size: 0.9rem; color: #666; margin-bottom: 1rem; }",
        ".section { margin: 2rem 0; }",
        "table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }",
        "th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: right; }",
        "th:first-child, td:first-child { text-align: left; }",
        "th { background: #f5f5f5; }",
        "ul.notes li { margin: 0.35rem 0; }",
        ".plotly-graph-div { min-height: 420px; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)}</h1>",
    ]

    if subtitle:
        parts.append(f"<p class='subtitle'>{escape(subtitle)}</p>")

    meta_lines = [f"Generated: {generated}"]
    for k, v in meta.items():
        meta_lines.append(f"{escape(k)}: {escape(str(v))}")
    parts.append(f"<p class='meta'>{' · '.join(meta_lines)}</p>")

    if notes:
        parts.append(
            "<div class='section'><h2>Trading notes &amp; divergence context</h2><ul class='notes'>"
        )
        for note in notes:
            parts.append(f"<li>{escape(note)}</li>")
        parts.append("</ul></div>")

    for idx, fig in enumerate(figures):
        if idx == 0:
            js_mode: bool | str = plotlyjs_mode
        else:
            js_mode = False
        export_fig = prepare_figure_for_static_export(fig)
        fig_html = export_fig.to_html(
            full_html=False,
            include_plotlyjs=js_mode,
            config={"displayModeBar": True, "responsive": True},
        )
        parts.append(f"<div class='section'>{fig_html}</div>")

    for name, df in tables.items():
        if df is None or df.empty:
            continue
        parts.append(f"<div class='section'><h2>{escape(name)}</h2>")
        parts.append(_dataframe_to_html(df))
        parts.append("</div>")

    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def _dataframe_to_html(df: pd.DataFrame) -> str:
    display = df.copy()
    for col in display.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        display[col] = display[col].dt.strftime("%Y-%m")
    numeric = display.select_dtypes(include="number").columns
    display[numeric] = display[numeric].round(1)
    return display.to_html(index=False, border=0, classes="")
