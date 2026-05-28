from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from licor.reports.zone_curve_report import INTENSITY_COLORS


@dataclass(frozen=True)
class ExperimentalZoneDynamicsDriverReviewReportConfig:
    baseline_intensity: str = "none"
    title: str = "Spa LMP2 experimental driver review (dynamics v1)"
    include_plotlyjs: str | bool = "cdn"


def render_experimental_zone_dynamics_driver_review_html(
    zone_dynamics: pl.DataFrame,
    driver_review: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsDriverReviewReportConfig | None = None,
) -> str:
    report_config = config or ExperimentalZoneDynamicsDriverReviewReportConfig()
    filtered = zone_dynamics.filter(
        pl.col("lico_intensity").fill_null(report_config.baseline_intensity)
        != report_config.baseline_intensity
    )

    sections: list[str] = []
    include_plotlyjs = report_config.include_plotlyjs
    for review_row in driver_review.sort("zone_id").iter_rows(named=True):
        zone_id = str(review_row["zone_id"])
        zone_points = filtered.filter(pl.col("zone_id") == zone_id)
        figure = _create_zone_figure(zone_points, review_row)
        figure_html = figure.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config={"displayModeBar": False, "responsive": True},
        )
        include_plotlyjs = False
        sections.append(_render_zone_section(review_row, figure_html))

    return _wrap_html_document(
        title=report_config.title,
        body="".join(sections),
    )


def write_experimental_zone_dynamics_driver_review_report_html(
    zone_dynamics: pl.DataFrame,
    driver_review: pl.DataFrame,
    path: str | Path,
    *,
    config: ExperimentalZoneDynamicsDriverReviewReportConfig | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_experimental_zone_dynamics_driver_review_html(
            zone_dynamics,
            driver_review,
            config=config,
        ),
        encoding="utf-8",
    )
    return output_path


def _create_zone_figure(
    zone_points: pl.DataFrame,
    review_row: dict[str, object],
) -> go.Figure:
    label = str(review_row["display_label"])
    figure = make_subplots(
        rows=1,
        cols=4,
        subplot_titles=(
            "Entry relief",
            "Apex / exit",
            "Time cost",
            "Fuel saved",
        ),
        horizontal_spacing=0.08,
    )

    for intensity in _sorted_intensities(zone_points):
        intensity_points = (
            zone_points.filter(pl.col("lico_intensity") == intensity)
            .sort("lico_distance_before_brake_m")
        )
        if intensity_points.is_empty():
            continue
        color = INTENSITY_COLORS.get(intensity, "#2563eb")
        distances = intensity_points["lico_distance_before_brake_m"].to_list()
        hover = _hover_text(intensity_points)

        figure.add_trace(
            go.Scatter(
                x=distances,
                y=intensity_points["brake_start_delta_vs_baseline_m"].to_list(),
                mode="markers",
                name=intensity,
                legendgroup=intensity,
                marker={"color": color, "size": 10, "line": {"color": "#111827", "width": 0.6}},
                text=hover,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=distances,
                y=intensity_points["apex_speed_delta_vs_baseline_kph"].to_list(),
                mode="markers",
                name=f"{intensity} apex",
                legendgroup=intensity,
                showlegend=False,
                marker={"color": color, "size": 10, "symbol": "circle"},
                text=hover,
                hovertemplate="%{text}<br>series=apex<extra></extra>",
            ),
            row=1,
            col=2,
        )
        figure.add_trace(
            go.Scatter(
                x=distances,
                y=intensity_points["exit_speed_delta_vs_baseline_kph"].to_list(),
                mode="markers",
                name=f"{intensity} exit",
                legendgroup=intensity,
                showlegend=False,
                marker={"color": color, "size": 10, "symbol": "diamond"},
                text=hover,
                hovertemplate="%{text}<br>series=exit<extra></extra>",
            ),
            row=1,
            col=2,
        )
        figure.add_trace(
            go.Scatter(
                x=distances,
                y=intensity_points["time_lost_vs_baseline_s"].to_list(),
                mode="markers",
                name=f"{intensity} time",
                legendgroup=intensity,
                showlegend=False,
                marker={"color": color, "size": 10},
                text=hover,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=3,
        )
        figure.add_trace(
            go.Scatter(
                x=distances,
                y=intensity_points["fuel_saved_vs_baseline_l"].to_list(),
                mode="markers",
                name=f"{intensity} fuel",
                legendgroup=intensity,
                showlegend=False,
                marker={"color": color, "size": 10},
                text=hover,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=4,
        )

    _add_trendline(
        figure,
        zone_points,
        x_column="lico_distance_before_brake_m",
        y_column="brake_start_delta_vs_baseline_m",
        row=1,
        col=1,
        name="entry trend",
    )
    _add_trendline(
        figure,
        zone_points,
        x_column="lico_distance_before_brake_m",
        y_column="apex_speed_delta_vs_baseline_kph",
        row=1,
        col=2,
        name="apex trend",
        color="#111827",
    )
    _add_trendline(
        figure,
        zone_points,
        x_column="lico_distance_before_brake_m",
        y_column="exit_speed_delta_vs_baseline_kph",
        row=1,
        col=2,
        name="exit trend",
        color="#6b7280",
    )
    _add_trendline(
        figure,
        zone_points,
        x_column="lico_distance_before_brake_m",
        y_column="time_lost_vs_baseline_s",
        row=1,
        col=3,
        name="time trend",
    )
    _add_trendline(
        figure,
        zone_points,
        x_column="lico_distance_before_brake_m",
        y_column="fuel_saved_vs_baseline_l",
        row=1,
        col=4,
        name="fuel trend",
    )

    for col in range(1, 5):
        figure.add_hline(y=0.0, line_color="#d1d5db", line_width=1, row=1, col=col)

    figure.update_layout(
        title=f"{label} simplified driver review",
        template="plotly_white",
        height=360,
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
        legend_title_text="LICO intensity",
    )
    for col in range(1, 5):
        figure.update_xaxes(
            title_text="LICO distance before brake (m)",
            row=1,
            col=col,
            showgrid=True,
            gridcolor="#f3f4f6",
        )
    figure.update_yaxes(title_text="brake start delta (m)", row=1, col=1)
    figure.update_yaxes(title_text="speed delta (km/h)", row=1, col=2)
    figure.update_yaxes(title_text="time lost (s)", row=1, col=3)
    figure.update_yaxes(title_text="fuel saved (L)", row=1, col=4)
    return figure


def _render_zone_section(review_row: dict[str, object], figure_html: str) -> str:
    zone_label = _escape(review_row["display_label"])
    primary = _badge(str(review_row["primary_review_label"]), tone="primary")
    secondary = _badge(str(review_row["secondary_review_label"]), tone="secondary")
    status = _escape(review_row.get("current_model_status") or "n/a")
    summary = _escape(review_row.get("driver_summary") or "")
    takeaway = _escape(review_row.get("pilot_takeaway") or "")

    metrics = [
        ("Current status", status),
        ("Passes", _format_number(review_row.get("pass_count"), ".0f")),
        (
            "LICO distance range",
            _distance_range(
                review_row.get("min_lico_distance_before_brake_m"),
                review_row.get("max_lico_distance_before_brake_m"),
            ),
        ),
        (
            "Mean fuel saved",
            _format_number(review_row.get("mean_fuel_saved_vs_baseline_l"), ".3f", " L"),
        ),
        (
            "Mean time lost",
            _format_number(review_row.get("mean_time_lost_vs_baseline_s"), ".3f", " s"),
        ),
        (
            "Mean brake delta",
            _format_number(
                review_row.get("mean_brake_start_delta_vs_baseline_m"),
                ".2f",
                " m",
            ),
        ),
        (
            "Mean apex delta",
            _format_number(
                review_row.get("mean_apex_speed_delta_vs_baseline_kph"),
                ".2f",
                " km/h",
            ),
        ),
        (
            "Mean exit delta",
            _format_number(
                review_row.get("mean_exit_speed_delta_vs_baseline_kph"),
                ".2f",
                " km/h",
            ),
        ),
        (
            "Dynamics R2 gain",
            _format_number(review_row.get("r2_improvement"), ".3f"),
        ),
        (
            "Tyre delta",
            _format_number(
                review_row.get("mean_carcass_temp_zone_start_delta_vs_baseline_c"),
                ".2f",
                " C",
            ),
        ),
    ]
    metrics_html = "".join(
        f"<div class='metric'><span class='metric-label'>{_escape(label)}</span>"
        f"<span class='metric-value'>{_escape(value)}</span></div>"
        for label, value in metrics
    )

    quality_flags = _escape(review_row.get("current_quality_flags") or "")
    quality_html = (
        f"<p class='flags'><strong>Quality flags:</strong> {quality_flags}</p>"
        if quality_flags
        else ""
    )

    return f"""
    <section class="zone-section">
      <div class="zone-header">
        <h2>{zone_label}</h2>
        <div class="badges">{primary}{secondary}</div>
      </div>
      <p class="summary">{summary}</p>
      <p class="takeaway"><strong>Pilot takeaway:</strong> {takeaway}</p>
      {quality_html}
      <div class="metric-grid">{metrics_html}</div>
      <div class="figure-wrap">{figure_html}</div>
    </section>
    """


def _wrap_html_document(*, title: str, body: str) -> str:
    escaped_title = _escape(title)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escaped_title}</title>
    <style>
      body {{
        font-family: Inter, Arial, sans-serif;
        margin: 0;
        background: #f8fafc;
        color: #0f172a;
      }}
      .page {{
        max-width: 1480px;
        margin: 0 auto;
        padding: 32px 24px 64px;
      }}
      .intro {{
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px 24px;
        margin-bottom: 24px;
      }}
      .intro h1 {{
        margin: 0 0 12px;
        font-size: 28px;
      }}
      .intro p {{
        margin: 0 0 10px;
        line-height: 1.55;
      }}
      .zone-section {{
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px 24px;
        margin-bottom: 24px;
      }}
      .zone-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
      }}
      .zone-header h2 {{
        margin: 0;
        font-size: 24px;
      }}
      .badges {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .badge {{
        display: inline-block;
        border-radius: 999px;
        padding: 6px 10px;
        font-size: 13px;
        font-weight: 600;
      }}
      .badge.primary {{
        background: #dbeafe;
        color: #1d4ed8;
      }}
      .badge.secondary {{
        background: #dcfce7;
        color: #166534;
      }}
      .summary, .takeaway, .flags {{
        margin: 12px 0 0;
        line-height: 1.55;
      }}
      .metric-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 12px;
        margin-top: 18px;
        margin-bottom: 18px;
      }}
      .metric {{
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 12px;
        background: #f8fafc;
      }}
      .metric-label {{
        display: block;
        color: #475569;
        font-size: 12px;
        margin-bottom: 4px;
      }}
      .metric-value {{
        display: block;
        font-size: 18px;
        font-weight: 600;
      }}
      .figure-wrap {{
        margin-top: 16px;
      }}
      .figure-wrap .plotly-graph-div {{
        width: 100%;
      }}
      ul {{
        margin: 10px 0 0 22px;
      }}
    </style>
  </head>
  <body>
    <div class="page">
      <section class="intro">
        <h1>{escaped_title}</h1>
        <p>This report is the simple companion to the full dynamics audit. Each zone should be read as a causal chain, not four isolated charts.</p>
        <ul>
          <li><strong>Entry relief:</strong> more LICO should arrive slower and usually move braking later.</li>
          <li><strong>Apex / exit:</strong> if those stay near zero or better, the zone converts LICO into a usable corner state.</li>
          <li><strong>Time cost:</strong> this is the local cost after the entry and corner adaptation happened.</li>
          <li><strong>Fuel saved:</strong> this stays as the cleanest signal and helps separate mechanical gain from human adaptation noise.</li>
        </ul>
      </section>
      {body}
    </div>
  </body>
</html>
"""


def _sorted_intensities(zone_points: pl.DataFrame) -> list[str]:
    ordered = []
    for label in ("low", "medium", "high", "controlled_random"):
        if label in zone_points["lico_intensity"].to_list():
            ordered.append(label)
    remaining = sorted(
        value for value in zone_points["lico_intensity"].drop_nulls().unique().to_list() if value not in ordered
    )
    return ordered + [str(value) for value in remaining]


def _hover_text(zone_points: pl.DataFrame) -> list[str]:
    texts = []
    for row in zone_points.iter_rows(named=True):
        details = [
            f"run={row.get('run_id', '')}",
            f"lap={row.get('lap_number', '')}",
            f"distance={_format_number(row.get('lico_distance_before_brake_m'), '.1f', ' m')}",
            f"brake={_format_number(row.get('brake_start_delta_vs_baseline_m'), '.2f', ' m')}",
            f"apex={_format_number(row.get('apex_speed_delta_vs_baseline_kph'), '.2f', ' km/h')}",
            f"exit={_format_number(row.get('exit_speed_delta_vs_baseline_kph'), '.2f', ' km/h')}",
            f"time={_format_number(row.get('time_lost_vs_baseline_s'), '.3f', ' s')}",
            f"fuel={_format_number(row.get('fuel_saved_vs_baseline_l'), '.3f', ' L')}",
        ]
        texts.append("<br>".join(details))
    return texts


def _add_trendline(
    figure: go.Figure,
    zone_points: pl.DataFrame,
    *,
    x_column: str,
    y_column: str,
    row: int,
    col: int,
    name: str,
    color: str = "#111827",
) -> None:
    valid = zone_points.select(x_column, y_column).drop_nulls()
    if valid.height < 2:
        return
    x_values = [float(value) for value in valid[x_column].to_list()]
    y_values = [float(value) for value in valid[y_column].to_list()]
    slope, intercept = _fit_line(x_values, y_values)
    if slope is None or intercept is None:
        return
    x_min = min(x_values)
    x_max = max(x_values)
    figure.add_trace(
        go.Scatter(
            x=[x_min, x_max],
            y=[intercept + slope * x_min, intercept + slope * x_max],
            mode="lines",
            line={"color": color, "width": 2, "dash": "dash"},
            name=name,
            showlegend=False,
            hoverinfo="skip",
        ),
        row=row,
        col=col,
    )


def _fit_line(x_values: list[float], y_values: list[float]) -> tuple[float | None, float | None]:
    count = len(x_values)
    if count < 2:
        return None, None
    x_mean = sum(x_values) / count
    y_mean = sum(y_values) / count
    denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
    if abs(denominator) <= 1e-12:
        return None, None
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=False)
    ) / denominator
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _distance_range(minimum: object, maximum: object) -> str:
    if minimum is None or maximum is None:
        return "n/a"
    return f"{float(minimum):.1f} m - {float(maximum):.1f} m"


def _format_number(value: object, fmt: str, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{float(value):{fmt}}{suffix}"


def _badge(text: str, *, tone: str) -> str:
    return f"<span class='badge {tone}'>{_escape(text.replace('_', ' '))}</span>"


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value))
