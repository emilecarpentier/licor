from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from licor.analysis.track_zones import TrackZoneDefinition
from licor.reports.zone_curve_report import INTENSITY_COLORS


def build_zone_telemetry_window(
    samples: pl.DataFrame,
    zone: TrackZoneDefinition,
    *,
    before_start_m: float = 100.0,
    after_end_m: float = 50.0,
) -> pl.DataFrame:
    """Return telemetry samples around one track zone."""

    if samples.is_empty():
        return samples
    start_m = max(0.0, float(zone.start_distance_m) - before_start_m)
    end_m = float(zone.end_distance_m) + after_end_m
    return (
        samples.filter((pl.col("lap_distance_m") >= start_m) & (pl.col("lap_distance_m") <= end_m))
        .sort(_sample_group_columns(samples) + ["lap_distance_m"])
    )


def create_zone_telemetry_report_figure(
    samples: pl.DataFrame,
    zone_passes: pl.DataFrame,
    zone: TrackZoneDefinition,
    *,
    title: str,
) -> go.Figure:
    """Create a throttle/brake/speed report for one zone across laps."""

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("Throttle", "Brake", "Ground speed"),
        vertical_spacing=0.07,
    )
    if samples.is_empty():
        figure.update_layout(title=title, template="plotly_white", height=760)
        return figure

    shown_legends: set[str] = set()
    for group in _sample_groups(samples):
        lap_samples = _filter_group(samples, group)
        pass_row = _matching_zone_pass(zone_passes, group, zone.zone_id)
        intensity = str(pass_row.get("lico_intensity", "unknown")) if pass_row else "unknown"
        validity = str(pass_row.get("validity_label", "")) if pass_row else ""
        line_style = "dot" if validity == "driver_excluded" else "solid"
        color = INTENSITY_COLORS.get(intensity, "#111827")
        legend_name = f"{intensity} lap"
        showlegend = legend_name not in shown_legends
        shown_legends.add(legend_name)
        customdata = _sample_customdata(lap_samples, group, intensity, validity)

        for row, column, name, show in (
            (1, "throttle_pct", "Throttle", showlegend),
            (2, "brake_pct", "Brake", False),
            (3, "ground_speed_kph", "Speed", False),
        ):
            figure.add_trace(
                go.Scatter(
                    x=lap_samples["lap_distance_m"].to_list(),
                    y=lap_samples[column].to_list(),
                    mode="lines",
                    name=legend_name,
                    legendgroup=legend_name,
                    showlegend=show,
                    line={"color": color, "width": 1.6, "dash": line_style},
                    opacity=0.72,
                    customdata=customdata,
                    hovertemplate=(
                        f"{name}<br>"
                        "lap=%{customdata[0]}<br>"
                        "run=%{customdata[1]}<br>"
                        "intensity=%{customdata[2]}<br>"
                        "validity=%{customdata[3]}<br>"
                        "distance=%{x:.1f} m<br>"
                        "value=%{y:.2f}<extra></extra>"
                    ),
                ),
                row=row,
                col=1,
            )

    _add_zone_reference_lines(figure, zone)
    _add_lico_markers(figure, zone_passes, zone)
    figure.update_layout(
        title=title,
        template="plotly_white",
        height=820,
        legend_title_text="collection label",
        hovermode="closest",
    )
    figure.update_yaxes(title_text="throttle %", range=[-5, 105], row=1, col=1)
    figure.update_yaxes(title_text="brake %", range=[-5, 105], row=2, col=1)
    figure.update_yaxes(title_text="km/h", row=3, col=1)
    figure.update_xaxes(title_text="lap distance (m)", row=3, col=1)
    return figure


def write_zone_telemetry_report_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _sample_group_columns(samples: pl.DataFrame) -> list[str]:
    columns = []
    if "run_id" in samples.columns:
        columns.append("run_id")
    columns.append("lap_number")
    return columns


def _sample_groups(samples: pl.DataFrame) -> list[dict[str, object]]:
    return [
        dict(zip(_sample_group_columns(samples), row, strict=True))
        for row in samples.select(_sample_group_columns(samples)).unique().sort(
            _sample_group_columns(samples)
        ).rows()
    ]


def _filter_group(samples: pl.DataFrame, group: dict[str, object]) -> pl.DataFrame:
    filtered = samples
    for column, value in group.items():
        filtered = filtered.filter(pl.col(column) == value)
    return filtered.sort("lap_distance_m")


def _matching_zone_pass(
    zone_passes: pl.DataFrame,
    group: dict[str, object],
    zone_id: str,
) -> dict[str, object] | None:
    if zone_passes.is_empty():
        return None
    filtered = zone_passes.filter(pl.col("zone_id") == zone_id)
    for column, value in group.items():
        if column in filtered.columns:
            filtered = filtered.filter(pl.col(column) == value)
    if filtered.is_empty():
        return None
    return filtered.row(0, named=True)


def _sample_customdata(
    samples: pl.DataFrame,
    group: dict[str, object],
    intensity: str,
    validity: str,
) -> list[list[object]]:
    run_id = group.get("run_id", "")
    lap_number = group["lap_number"]
    return [[lap_number, run_id, intensity, validity] for _ in range(samples.height)]


def _add_zone_reference_lines(figure: go.Figure, zone: TrackZoneDefinition) -> None:
    for distance_m, label, color in (
        (zone.start_distance_m, "zone start", "#2ca25f"),
        (zone.brake_reference_m, "brake reference", "#de2d26"),
        (zone.end_distance_m, "zone end", "#3182bd"),
    ):
        figure.add_vline(
            x=float(distance_m),
            line={"color": color, "dash": "dash", "width": 1.3},
            annotation_text=label,
            annotation_position="top left",
        )


def _add_lico_markers(
    figure: go.Figure,
    zone_passes: pl.DataFrame,
    zone: TrackZoneDefinition,
) -> None:
    if zone_passes.is_empty() or "lico_start_m" not in zone_passes.columns:
        return
    markers = zone_passes.filter(
        (pl.col("zone_id") == zone.zone_id)
        & pl.col("has_lico")
        & pl.col("lico_start_m").is_not_null()
        & (pl.col("validity_label") == "valid")
    ).sort(["lico_intensity", "lap_number"])
    if markers.is_empty():
        return
    figure.add_trace(
        go.Scatter(
            x=markers["lico_start_m"].to_list(),
            y=[102.0] * markers.height,
            mode="markers",
            name="detected LICO start",
            marker={"color": "#111827", "size": 8, "symbol": "triangle-down"},
            customdata=[
                [row["lap_number"], row.get("run_id", ""), row["lico_intensity"]]
                for row in markers.iter_rows(named=True)
            ],
            hovertemplate=(
                "LICO start<br>"
                "lap=%{customdata[0]}<br>"
                "run=%{customdata[1]}<br>"
                "intensity=%{customdata[2]}<br>"
                "distance=%{x:.1f} m<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
