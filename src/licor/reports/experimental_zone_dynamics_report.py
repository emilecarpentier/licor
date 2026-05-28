from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from licor.reports.zone_curve_report import INTENSITY_COLORS


_FALLBACK_SERIES_COLORS = (
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
    "#be123c",
)


@dataclass(frozen=True)
class ExperimentalZoneDynamicsReportConfig:
    distance_column_candidates: tuple[str, ...] = (
        "mean_lico_distance_m",
        "lico_distance_m",
        "selected_lico_distance_m",
        "lico_distance_before_brake_m",
        "mean_lico_start_distance_before_brake_m",
        "observed_lico_distance_m",
    )
    apex_speed_column_candidates: tuple[str, ...] = (
        "apex_speed_delta_vs_baseline_kph",
        "min_speed_delta_vs_baseline_kph",
    )
    series_column_candidates: tuple[str, ...] = (
        "lico_intensity",
        "collection_label",
        "strategy_role",
        "plan_status",
        "model_status",
    )
    point_size_column_candidates: tuple[str, ...] = (
        "pass_count",
        "source_bin_count",
        "nonzero_source_bin_count",
    )
    include_brake_to_apex_subplot: bool = True


@dataclass(frozen=True)
class _SubplotSpec:
    title_suffix: str
    x_column: str
    x_title: str
    x_label: str
    x_format: str
    x_unit: str
    y_column: str
    y_title: str
    y_label: str
    y_format: str
    y_unit: str


def create_experimental_zone_dynamics_report_figure(
    experimental_points: pl.DataFrame,
    *,
    title: str,
    config: ExperimentalZoneDynamicsReportConfig | None = None,
) -> go.Figure:
    """Create a faceted Plotly report for experimental LICO dynamics anomalies."""

    report_config = config or ExperimentalZoneDynamicsReportConfig()
    if experimental_points.is_empty():
        figure = go.Figure()
        figure.update_layout(title=title, template="plotly_white")
        return figure

    _validate_report_columns(experimental_points, config=report_config)
    points = prepare_experimental_zone_dynamics_report_samples(
        experimental_points,
        config=report_config,
    )
    zones = _zone_rows(points)
    subplot_specs = _subplot_specs(config=report_config)

    subplot_titles = []
    for zone in zones:
        label = str(zone["display_label"])
        subplot_titles.extend(f"{label} {spec.title_suffix}" for spec in subplot_specs)

    figure = make_subplots(
        rows=len(zones),
        cols=len(subplot_specs),
        subplot_titles=subplot_titles,
        horizontal_spacing=0.04,
        vertical_spacing=min(0.08, 0.65 / len(zones)),
    )

    shown_legends: set[str] = set()
    series_colors = _series_color_map(points)
    for row_index, zone in enumerate(zones, start=1):
        zone_id = str(zone["zone_id"])
        zone_points = points.filter(pl.col("zone_id") == zone_id)
        for series in _series_values(zone_points):
            series_points = zone_points.filter(pl.col("_report_series") == series)
            color = series_colors[str(series)]
            for col_index, spec in enumerate(subplot_specs, start=1):
                metric_points = (
                    series_points.filter(
                        pl.col(spec.x_column).is_not_null() & pl.col(spec.y_column).is_not_null()
                    )
                    .sort(spec.x_column)
                )
                if metric_points.is_empty():
                    continue

                legend_name = str(series)
                showlegend = legend_name not in shown_legends
                shown_legends.add(legend_name)
                figure.add_trace(
                    go.Scatter(
                        x=metric_points[spec.x_column].to_list(),
                        y=metric_points[spec.y_column].to_list(),
                        mode="markers",
                        name=legend_name,
                        legendgroup=legend_name,
                        showlegend=showlegend,
                        marker={
                            "color": color,
                            "size": _marker_sizes(metric_points),
                            "opacity": 0.8,
                            "line": {"color": "#111827", "width": 0.7},
                        },
                        customdata=_point_customdata(metric_points),
                        hovertemplate=_hover_template(spec),
                    ),
                    row=row_index,
                    col=col_index,
                )

    for row_index in range(1, len(zones) + 1):
        for col_index in range(1, len(subplot_specs) + 1):
            figure.add_hline(
                y=0.0,
                line_color="#d1d5db",
                line_width=1,
                row=row_index,
                col=col_index,
            )
            figure.add_vline(
                x=0.0,
                line_color="#e5e7eb",
                line_width=1,
                row=row_index,
                col=col_index,
            )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=max(420, 280 * len(zones)),
        legend_title_text="experimental series",
        hovermode="closest",
    )
    for col_index, spec in enumerate(subplot_specs, start=1):
        figure.update_xaxes(
            title_text=spec.x_title,
            col=col_index,
            showgrid=True,
            gridcolor="#f3f4f6",
            showline=True,
            linecolor="#d1d5db",
        )
        figure.update_yaxes(
            title_text=spec.y_title,
            col=col_index,
            showgrid=True,
            gridcolor="#f3f4f6",
            showline=True,
            linecolor="#d1d5db",
        )
    return figure


def prepare_experimental_zone_dynamics_report_samples(
    experimental_points: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsReportConfig | None = None,
) -> pl.DataFrame:
    """Normalize experimental rows so the report can accept common LICOR aliases."""

    report_config = config or ExperimentalZoneDynamicsReportConfig()
    if experimental_points.is_empty():
        return experimental_points

    distance_column = _resolve_column_name(
        experimental_points,
        report_config.distance_column_candidates,
    )
    apex_speed_column = _resolve_column_name(
        experimental_points,
        report_config.apex_speed_column_candidates,
    )
    series_column = _resolve_column_name(
        experimental_points,
        report_config.series_column_candidates,
    )
    point_size_column = _resolve_column_name(
        experimental_points,
        report_config.point_size_column_candidates,
    )

    points = experimental_points
    if "display_label" not in points.columns:
        points = points.with_columns(pl.col("zone_id").cast(pl.String).alias("display_label"))
    points = points.with_columns(
        pl.coalesce(
            [
                pl.col("display_label").cast(pl.String),
                pl.col("zone_id").cast(pl.String),
            ]
        ).alias("display_label"),
        pl.col(distance_column).cast(pl.Float64, strict=False).alias("_report_distance_m"),
        pl.col("brake_start_delta_vs_baseline_m")
        .cast(pl.Float64, strict=False)
        .alias("brake_start_delta_vs_baseline_m"),
        pl.col("brake_start_speed_delta_vs_baseline_kph")
        .cast(pl.Float64, strict=False)
        .alias("brake_start_speed_delta_vs_baseline_kph"),
        pl.col(apex_speed_column)
        .cast(pl.Float64, strict=False)
        .alias("_report_apex_speed_delta_vs_baseline_kph"),
        pl.col("exit_speed_delta_vs_baseline_kph")
        .cast(pl.Float64, strict=False)
        .alias("exit_speed_delta_vs_baseline_kph"),
        pl.col("time_lost_vs_baseline_s")
        .cast(pl.Float64, strict=False)
        .alias("time_lost_vs_baseline_s"),
    )
    if series_column is None:
        points = points.with_columns(pl.lit("experimental").alias("_report_series"))
    else:
        points = points.with_columns(
            pl.when(pl.col(series_column).is_null())
            .then(pl.lit("experimental"))
            .otherwise(pl.col(series_column).cast(pl.String))
            .alias("_report_series")
        )
    if point_size_column is None:
        points = points.with_columns(
            pl.lit(1.0).alias("_report_marker_weight"),
        )
    else:
        points = points.with_columns(
            pl.coalesce(
                [
                    pl.col(point_size_column).cast(pl.Float64, strict=False),
                    pl.lit(1.0),
                ]
            ).alias("_report_marker_weight"),
        )

    return points.sort(
        [
            "zone_id",
            "_report_series",
            "_report_distance_m",
            "brake_start_delta_vs_baseline_m",
        ]
    )


def write_experimental_zone_dynamics_report_html(
    figure: go.Figure,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _validate_report_columns(
    experimental_points: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsReportConfig,
) -> None:
    required = {
        "zone_id",
        "brake_start_delta_vs_baseline_m",
        "brake_start_speed_delta_vs_baseline_kph",
        "exit_speed_delta_vs_baseline_kph",
        "time_lost_vs_baseline_s",
    }
    missing = required - set(experimental_points.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"experimental zone dynamics samples missing required columns: {missing_text}"
        )

    if _resolve_column_name(experimental_points, config.distance_column_candidates) is None:
        expected = ", ".join(config.distance_column_candidates)
        raise ValueError(
            "experimental zone dynamics samples missing LICO distance column; "
            f"expected one of: {expected}"
        )
    if _resolve_column_name(experimental_points, config.apex_speed_column_candidates) is None:
        expected = ", ".join(config.apex_speed_column_candidates)
        raise ValueError(
            "experimental zone dynamics samples missing apex speed delta column; "
            f"expected one of: {expected}"
        )


def _subplot_specs(
    *,
    config: ExperimentalZoneDynamicsReportConfig,
) -> list[_SubplotSpec]:
    specs = [
        _SubplotSpec(
            title_suffix="brake start delta",
            x_column="_report_distance_m",
            x_title="LICO distance before brake (m)",
            x_label="LICO distance",
            x_format=".1f",
            x_unit="m",
            y_column="brake_start_delta_vs_baseline_m",
            y_title="brake start delta vs baseline (m)",
            y_label="brake start delta",
            y_format=".2f",
            y_unit="m",
        ),
        _SubplotSpec(
            title_suffix="brake start speed delta",
            x_column="_report_distance_m",
            x_title="LICO distance before brake (m)",
            x_label="LICO distance",
            x_format=".1f",
            x_unit="m",
            y_column="brake_start_speed_delta_vs_baseline_kph",
            y_title="brake start speed delta vs baseline (km/h)",
            y_label="brake start speed delta",
            y_format=".2f",
            y_unit="km/h",
        ),
        _SubplotSpec(
            title_suffix="apex speed delta",
            x_column="_report_distance_m",
            x_title="LICO distance before brake (m)",
            x_label="LICO distance",
            x_format=".1f",
            x_unit="m",
            y_column="_report_apex_speed_delta_vs_baseline_kph",
            y_title="apex speed delta vs baseline (km/h)",
            y_label="apex speed delta",
            y_format=".2f",
            y_unit="km/h",
        ),
        _SubplotSpec(
            title_suffix="exit speed delta",
            x_column="_report_distance_m",
            x_title="LICO distance before brake (m)",
            x_label="LICO distance",
            x_format=".1f",
            x_unit="m",
            y_column="exit_speed_delta_vs_baseline_kph",
            y_title="exit speed delta vs baseline (km/h)",
            y_label="exit speed delta",
            y_format=".2f",
            y_unit="km/h",
        ),
        _SubplotSpec(
            title_suffix="time lost",
            x_column="_report_distance_m",
            x_title="LICO distance before brake (m)",
            x_label="LICO distance",
            x_format=".1f",
            x_unit="m",
            y_column="time_lost_vs_baseline_s",
            y_title="time lost vs baseline (s)",
            y_label="time lost",
            y_format=".3f",
            y_unit="s",
        ),
    ]
    if config.include_brake_to_apex_subplot:
        specs.append(
            _SubplotSpec(
                title_suffix="apex vs brake",
                x_column="brake_start_delta_vs_baseline_m",
                x_title="brake start delta vs baseline (m)",
                x_label="brake start delta",
                x_format=".2f",
                x_unit="m",
                y_column="_report_apex_speed_delta_vs_baseline_kph",
                y_title="apex speed delta vs baseline (km/h)",
                y_label="apex speed delta",
                y_format=".2f",
                y_unit="km/h",
            )
        )
    return specs


def _zone_rows(experimental_points: pl.DataFrame) -> list[dict[str, str]]:
    return list(
        experimental_points.select("zone_id", "display_label")
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    )


def _series_values(experimental_points: pl.DataFrame) -> list[str]:
    return sorted(
        str(value)
        for value in experimental_points["_report_series"].drop_nulls().unique().to_list()
    )


def _series_color_map(experimental_points: pl.DataFrame) -> dict[str, str]:
    colors: dict[str, str] = {}
    fallback_index = 0
    for series in _series_values(experimental_points):
        if series in INTENSITY_COLORS:
            colors[series] = INTENSITY_COLORS[series]
            continue
        colors[series] = _FALLBACK_SERIES_COLORS[
            fallback_index % len(_FALLBACK_SERIES_COLORS)
        ]
        fallback_index += 1
    return colors


def _marker_sizes(experimental_points: pl.DataFrame) -> list[float]:
    weights = [
        max(float(value), 0.0)
        for value in experimental_points["_report_marker_weight"].to_list()
    ]
    if not weights:
        return []
    minimum = min(weights)
    maximum = max(weights)
    if maximum - minimum <= 1e-9:
        return [10.0] * len(weights)
    return [8.0 + (6.0 * ((value - minimum) / (maximum - minimum))) for value in weights]


def _point_customdata(experimental_points: pl.DataFrame) -> list[list[object]]:
    return [
        [
            row["display_label"],
            row["_report_series"],
            _row_context(row),
            _format_quality_flags(row.get("quality_flags")),
        ]
        for row in experimental_points.iter_rows(named=True)
    ]


def _row_context(row: dict[str, Any]) -> str:
    fields = []
    for column, label in (
        ("run_id", "run"),
        ("lap_number", "lap"),
        ("lico_intensity", "intensity"),
        ("strategy_role", "role"),
        ("plan_status", "plan"),
        ("model_status", "status"),
        ("pass_count", "pass_count"),
        ("source_bin_count", "source_bin_count"),
        ("nonzero_source_bin_count", "nonzero_source_bin_count"),
    ):
        value = row.get(column)
        if value is None or value == "":
            continue
        fields.append(f"{label}={value}")
    return ", ".join(fields)


def _hover_template(spec: _SubplotSpec) -> str:
    return (
        "zone=%{customdata[0]}<br>"
        "series=%{customdata[1]}<br>"
        "details=%{customdata[2]}<br>"
        f"{spec.x_label}=%{{x:{spec.x_format}}} {spec.x_unit}<br>"
        f"{spec.y_label}=%{{y:{spec.y_format}}} {spec.y_unit}<br>"
        "flags=%{customdata[3]}<extra></extra>"
    )


def _resolve_column_name(
    frame: pl.DataFrame,
    candidates: tuple[str, ...],
) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _format_quality_flags(flags: object) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)
