from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots


INTENSITY_COLORS = {
    "none": "#6b7280",
    "low": "#2ca25f",
    "medium": "#3182bd",
    "high": "#de2d26",
}


def create_zone_curve_report_figure(
    curve_points: pl.DataFrame,
    curve_bins: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    """Create a faceted Plotly report for descriptive zone curves."""

    zones = _zone_rows(curve_points, curve_bins)
    if not zones:
        figure = go.Figure()
        figure.update_layout(title=title, template="plotly_white")
        return figure

    subplot_titles = []
    for zone in zones:
        label = str(zone["display_label"])
        subplot_titles.extend([f"{label} fuel", f"{label} time"])

    figure = make_subplots(
        rows=len(zones),
        cols=2,
        subplot_titles=subplot_titles,
        horizontal_spacing=0.08,
        vertical_spacing=min(0.08, 0.65 / len(zones)),
    )

    shown_legends: set[str] = set()
    for row_index, zone in enumerate(zones, start=1):
        zone_id = str(zone["zone_id"])
        zone_points = curve_points.filter(pl.col("zone_id") == zone_id)
        zone_bins = curve_bins.filter(pl.col("zone_id") == zone_id)

        _add_point_traces(
            figure,
            zone_points,
            row=row_index,
            shown_legends=shown_legends,
        )
        _add_bin_trace(
            figure,
            zone_bins,
            metric_column="mean_fuel_saved_l",
            name="bin fuel mean",
            row=row_index,
            col=1,
            shown_legends=shown_legends,
        )
        _add_bin_trace(
            figure,
            zone_bins,
            metric_column="mean_time_lost_s",
            name="bin time mean",
            row=row_index,
            col=2,
            shown_legends=shown_legends,
        )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=max(360, 260 * len(zones)),
        legend_title_text="curve item",
        hovermode="closest",
    )
    figure.update_xaxes(title_text="LICO distance before brake (m)")
    figure.update_yaxes(title_text="fuel saved vs none (L)", col=1)
    figure.update_yaxes(title_text="time lost vs none (s)", col=2)
    return figure


def write_zone_curve_report_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _zone_rows(curve_points: pl.DataFrame, curve_bins: pl.DataFrame) -> list[dict[str, str]]:
    frames = []
    for frame in (curve_points, curve_bins):
        if not frame.is_empty():
            frames.append(frame.select("zone_id", "display_label"))
    if not frames:
        return []
    return list(
        pl.concat(frames)
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    )


def _add_point_traces(
    figure: go.Figure,
    zone_points: pl.DataFrame,
    *,
    row: int,
    shown_legends: set[str],
) -> None:
    if zone_points.is_empty():
        return

    for intensity in sorted(zone_points["lico_intensity"].unique().to_list()):
        points = zone_points.filter(pl.col("lico_intensity") == intensity)
        color = INTENSITY_COLORS.get(str(intensity), "#111827")
        legend_name = f"{intensity} pass"
        showlegend = legend_name not in shown_legends
        shown_legends.add(legend_name)

        customdata = _point_customdata(points)
        common = {
            "x": points["lico_distance_before_brake_m"].to_list(),
            "mode": "markers",
            "name": legend_name,
            "legendgroup": legend_name,
            "showlegend": showlegend,
            "marker": {"color": color, "size": 7, "opacity": 0.62},
            "customdata": customdata,
            "hovertemplate": (
                "lap=%{customdata[0]}<br>"
                "run=%{customdata[1]}<br>"
                "intensity=%{customdata[2]}<br>"
                "LICO=%{x:.1f} m<br>"
                "%{y:.4f}<extra></extra>"
            ),
        }
        figure.add_trace(
            go.Scatter(
                y=points["fuel_saved_vs_baseline_l"].to_list(),
                **common,
            ),
            row=row,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                y=points["time_lost_vs_baseline_s"].to_list(),
                **{**common, "showlegend": False},
            ),
            row=row,
            col=2,
        )


def _add_bin_trace(
    figure: go.Figure,
    zone_bins: pl.DataFrame,
    *,
    metric_column: str,
    name: str,
    row: int,
    col: int,
    shown_legends: set[str],
) -> None:
    if zone_bins.is_empty():
        return

    showlegend = name not in shown_legends
    shown_legends.add(name)
    figure.add_trace(
        go.Scatter(
            x=zone_bins["lico_distance_bin_mid_m"].to_list(),
            y=zone_bins[metric_column].to_list(),
            mode="lines+markers",
            name=name,
            legendgroup=name,
            showlegend=showlegend,
            line={"color": "#111827", "width": 2},
            marker={
                "color": "#111827",
                "size": [6 + int(count) for count in zone_bins["pass_count"].to_list()],
            },
            customdata=_bin_customdata(zone_bins),
            hovertemplate=(
                "bin=%{customdata[0]:.0f}-%{customdata[1]:.0f} m<br>"
                "passes=%{customdata[2]}<br>"
                "LICO passes=%{customdata[3]}<br>"
                "%{y:.4f}<extra></extra>"
            ),
        ),
        row=row,
        col=col,
    )


def _point_customdata(points: pl.DataFrame) -> list[list[object]]:
    return [
        [row["lap_number"], row["run_id"], row["lico_intensity"]]
        for row in points.iter_rows(named=True)
    ]


def _bin_customdata(bins: pl.DataFrame) -> list[list[object]]:
    return [
        [
            row["lico_distance_bin_start_m"],
            row["lico_distance_bin_end_m"],
            row["pass_count"],
            row["detected_lico_passes"],
        ]
        for row in bins.iter_rows(named=True)
    ]
