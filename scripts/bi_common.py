"""Shared query + rendering helpers for the two BI outputs (Phase 6).

Both scripts/generate_executive_scorecard.py and
scripts/generate_operational_dashboard.py import mf_query() from here —
neither one is allowed to compute a metric any other way, which is the
actual point of this phase (see docs/semantic_layer_strategy.md). The
HTML/SVG helpers follow the dataviz skill's method: thin marks, rounded
line ends, a 2px gap between adjacent fills, the validated reference
categorical/status palette as CSS custom properties (light + dark, both
selected), and a native <title> hover on every mark — a deliberately
minimal but real hover layer (not a JS crosshair), appropriate for a
static, checked-in "thin" report rather than a live BI tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pandas as pd

DBT_DIR = Path(__file__).resolve().parent.parent / "dbt"

# The dataviz skill's validated reference palette (references/palette.md) —
# used unchanged, so no re-validation run is needed.
COLORS = {
    "series-1": ("#2a78d6", "#3987e5"),  # blue
    "series-2": ("#eb6834", "#d95926"),  # orange
    "series-3": ("#1baf7a", "#199e70"),  # aqua
    "series-4": ("#eda100", "#c98500"),  # yellow
    "surface": ("#fcfcfb", "#1a1a19"),
    "page": ("#f9f9f7", "#0d0d0d"),
    "text-primary": ("#0b0b0b", "#ffffff"),
    "text-secondary": ("#52514e", "#c3c2b7"),
    "text-muted": ("#898781", "#898781"),
    "gridline": ("#e1e0d9", "#2c2c2a"),
    "baseline": ("#c3c2b7", "#383835"),
    "border": ("rgba(11,11,11,0.10)", "rgba(255,255,255,0.10)"),
}


def mf_query(metrics: str, group_by: str | None = None, where: str | None = None) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
    try:
        cmd = ["uv", "run", "mf", "query", "--metrics", metrics, "--csv", str(csv_path), "--quiet"]
        if group_by:
            cmd += ["--group-by", group_by]
        if where:
            cmd += ["--where", where]
        result = subprocess.run(cmd, cwd=DBT_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"mf query failed for '{metrics}':\n{result.stderr}")
        return pd.read_csv(csv_path)
    finally:
        csv_path.unlink(missing_ok=True)


def page_shell(title: str, generated_at: str, body: str) -> str:
    """Wraps `body` (already-built HTML) in the shared page chrome: CSS custom
    properties for both themes, typography, and layout — see palette.md."""
    dark_vars = "\n".join(f"    --{name}: {dark};" for name, (_light, dark) in COLORS.items())
    light_vars = "\n".join(f"    --{name}: {light};" for name, (light, _dark) in COLORS.items())
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light;
{light_vars}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
{dark_vars}
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
{dark_vars}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 32px 24px 64px;
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 0.875rem; margin: 0 0 32px; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 24px;
  }}
  .card h2 {{ font-size: 1rem; margin: 0 0 16px; color: var(--text-primary); }}
  .stat-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat-tile {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    min-width: 160px;
    flex: 1;
  }}
  .stat-tile .label {{ font-size: 0.8125rem; color: var(--text-secondary); margin-bottom: 6px; }}
  .stat-tile .value {{ font-size: 1.75rem; font-weight: 600; color: var(--text-primary); }}
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; font-size: 0.8125rem; color: var(--text-secondary); }}
  .legend .swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }}
  .chart-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.8125rem; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--gridline); }}
  th {{ color: var(--text-secondary); font-weight: 500; }}
  td {{ color: var(--text-primary); }}
  details summary {{ cursor: pointer; color: var(--text-secondary); font-size: 0.8125rem; margin-top: 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="subtitle">Generated {generated_at} · every number below comes from <code>mf query</code> against the governed semantic layer — see docs/metric_definitions_semantic.md.</p>
{body}
</body>
</html>
"""


def stat_tile(label: str, value: str) -> str:
    return f'<div class="stat-tile"><div class="label">{label}</div><div class="value">{value}</div></div>'


def format_money(value: float) -> str:
    return f"${value:,.0f}"


def format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_count(value: float) -> str:
    return f"{value:,.0f}"


def line_chart_svg(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    *,
    color_slot: str = "series-1",
    y_format=format_money,
    width: int = 720,
    height: int = 260,
) -> str:
    """One-series line chart: thin 2px line, rounded data-end, dots with a
    native <title> hover on every point (the minimal real hover layer for a
    static report — see this module's docstring)."""
    pad_left, pad_right, pad_top, pad_bottom = 56, 16, 16, 32
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    values = df[y_col].tolist()
    labels = df[x_col].tolist()
    n = len(values)
    if n == 0:
        return "<p>No data.</p>"
    max_v = max(values) or 1
    min_v = min(0, min(values))
    span = (max_v - min_v) or 1

    def x_at(i: int) -> float:
        return pad_left + (i / max(n - 1, 1)) * plot_w

    def y_at(v: float) -> float:
        return pad_top + plot_h - ((v - min_v) / span) * plot_h

    points = [(x_at(i), y_at(v)) for i, v in enumerate(values)]
    path_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)

    gridlines = ""
    for frac in (0, 0.5, 1):
        gy = pad_top + plot_h - frac * plot_h
        gv = min_v + frac * span
        gridlines += (
            f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" '
            f'stroke="var(--gridline)" stroke-width="1"/>'
            f'<text x="{pad_left - 8}" y="{gy + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="var(--text-muted)">{y_format(gv)}</text>'
        )

    dots = ""
    for i, (x, y) in enumerate(points):
        dots += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--{color_slot})">'
            f"<title>{labels[i]}: {y_format(values[i])}</title></circle>"
        )

    label_step = max(1, n // 6)
    x_labels = ""
    for i in range(0, n, label_step):
        x_labels += (
            f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-size="11" fill="var(--text-muted)">{labels[i]}</text>'
        )

    return f"""<div class="chart-wrap">
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{y_col} over time">
  {gridlines}
  <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="var(--baseline)" stroke-width="1"/>
  <path d="{path_d}" fill="none" stroke="var(--{color_slot})" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  {dots}
  {x_labels}
</svg>
</div>"""


def bar_chart_svg(
    labels: list[str],
    values: list[float],
    *,
    color_slot: str = "series-1",
    y_format=format_money,
    width: int = 720,
    height: int = 280,
    horizontal: bool = False,
) -> str:
    """Single-series bar chart, thin rounded bar ends, gap between bars, a
    native <title> hover per bar."""
    if not values:
        return "<p>No data.</p>"
    max_v = max(values) or 1

    if horizontal:
        pad_left, pad_right, pad_top, pad_bottom = 140, 48, 12, 12
        plot_w = width - pad_left - pad_right
        n = len(values)
        bar_h = min(28, (height - pad_top - pad_bottom) / n - 6)
        bars = ""
        for i, (label, v) in enumerate(zip(labels, values, strict=True)):
            y = pad_top + i * ((height - pad_top - pad_bottom) / n)
            bar_w = (v / max_v) * plot_w
            bars += (
                f'<text x="{pad_left - 10}" y="{y + bar_h / 2 + 4:.1f}" text-anchor="end" '
                f'font-size="12" fill="var(--text-secondary)">{label}</text>'
                f'<rect x="{pad_left}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                f'rx="4" fill="var(--{color_slot})"><title>{label}: {y_format(v)}</title></rect>'
                f'<text x="{pad_left + bar_w + 8:.1f}" y="{y + bar_h / 2 + 4:.1f}" '
                f'font-size="11" fill="var(--text-muted)">{y_format(v)}</text>'
            )
        return f"""<div class="chart-wrap">
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="bar chart">
  {bars}
</svg>
</div>"""

    pad_left, pad_right, pad_top, pad_bottom = 56, 16, 16, 32
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    n = len(values)
    slot_w = plot_w / n
    bar_w = max(8, slot_w - 8)

    bars = ""
    for i, (label, v) in enumerate(zip(labels, values, strict=True)):
        bar_h = (v / max_v) * plot_h
        x = pad_left + i * slot_w + (slot_w - bar_w) / 2
        y = pad_top + plot_h - bar_h
        bars += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'rx="4" fill="var(--{color_slot})"><title>{label}: {y_format(v)}</title></rect>'
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-size="11" fill="var(--text-muted)">{label}</text>'
        )

    return f"""<div class="chart-wrap">
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="bar chart">
  <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="var(--baseline)" stroke-width="1"/>
  {bars}
</svg>
</div>"""
