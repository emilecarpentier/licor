from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from licor.analysis.lap_summary import (
    DatasetLapLabels,
    RunLapLabels,
    load_dataset_lap_labels,
)
from licor.analysis.zone_detection import build_lap_telemetry
from licor.ingestion import LmuTelemetryDatabase
from licor.reports.zone_curve_report import INTENSITY_COLORS


TELEMETRY_METRICS = {
    "ground_speed_kph": ("Ground speed", "km/h"),
    "throttle_pct": ("Throttle", "%"),
    "brake_pct": ("Brake", "%"),
    "fuel_level_l": ("Fuel level", "L"),
    "lap_distance_m": ("Lap distance", "m"),
}


@dataclass(frozen=True)
class LapTelemetryReportConfig:
    include_driver_lap_labels: tuple[str, ...] = ("valid", "borderline")
    include_collection_labels: tuple[str, ...] | None = None
    metrics: tuple[str, ...] = tuple(TELEMETRY_METRICS)


def build_labeled_lap_telemetry_samples(
    dataset_label_file: str | Path,
    *,
    project_root: str | Path = ".",
    config: LapTelemetryReportConfig | None = None,
) -> pl.DataFrame:
    """Load normalized lap telemetry samples for labelled dataset runs."""

    report_config = config or LapTelemetryReportConfig()
    labels = load_dataset_lap_labels(dataset_label_file)
    root = Path(project_root)
    frames = []
    for run in labels.runs:
        if not run.include_in_lap_summary:
            continue
        if not _include_collection_label(run, report_config):
            continue
        lap_numbers = _included_lap_numbers(run, report_config)
        if not lap_numbers:
            continue
        with LmuTelemetryDatabase(root / run.file) as telemetry:
            samples = build_lap_telemetry(telemetry, lap_numbers=lap_numbers)
        if samples.is_empty():
            continue
        frames.append(_with_run_metadata(samples, labels, run))

    if not frames:
        return empty_lap_telemetry_samples_frame()
    return pl.concat(frames, how="diagonal").sort(["run_id", "lap_number", "ts"])


def create_lap_telemetry_report_figure(
    samples: pl.DataFrame,
    *,
    title: str,
    metrics: tuple[str, ...] = tuple(TELEMETRY_METRICS),
) -> go.Figure:
    """Create a multi-lap Plotly report for core telemetry channels."""

    samples = prepare_lap_telemetry_report_samples(samples)
    _validate_report_columns(samples, metrics)
    if not metrics:
        figure = go.Figure()
        figure.update_layout(title=title, template="plotly_white")
        return figure

    subplot_titles = [TELEMETRY_METRICS[metric][0] for metric in metrics]
    figure = make_subplots(
        rows=len(metrics),
        cols=1,
        shared_xaxes=True,
        subplot_titles=subplot_titles,
        vertical_spacing=min(0.07, 0.7 / max(len(metrics), 1)),
    )
    if samples.is_empty():
        figure.update_layout(
            title=title,
            template="plotly_white",
            height=max(360, 210 * len(metrics)),
        )
        return figure

    shown_legends: set[str] = set()
    for group in _sample_groups(samples):
        lap_samples = _filter_group(samples, group)
        collection_label = str(group.get("collection_label") or "unknown")
        driver_label = str(group.get("driver_lap_label") or "")
        legend_name = _legend_name(group)
        color = INTENSITY_COLORS.get(collection_label, "#111827")
        line_style = "dot" if driver_label == "borderline" else "solid"
        showlegend = legend_name not in shown_legends
        shown_legends.add(legend_name)
        customdata = _sample_customdata(lap_samples, group)

        for row_index, metric in enumerate(metrics, start=1):
            figure.add_trace(
                go.Scatter(
                    x=lap_samples["lap_elapsed_s"].to_list(),
                    y=lap_samples[metric].to_list(),
                    mode="lines",
                    name=legend_name,
                    legendgroup=legend_name,
                    showlegend=showlegend if row_index == 1 else False,
                    line={"color": color, "width": 1.5, "dash": line_style},
                    opacity=0.74,
                    customdata=customdata,
                    hovertemplate=_hover_template(metric),
                ),
                row=row_index,
                col=1,
            )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=max(420, 210 * len(metrics)),
        legend_title_text="run / lap",
        hovermode="closest",
    )
    for row_index, metric in enumerate(metrics, start=1):
        figure.update_yaxes(
            title_text=TELEMETRY_METRICS[metric][1],
            row=row_index,
            col=1,
        )
    figure.update_xaxes(title_text="lap elapsed time (s)", row=len(metrics), col=1)
    return figure


def write_lap_telemetry_report_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs=True)
    return output_path


def build_spa_lmp2_lap_telemetry_report_artifact(
    *,
    project_root: str | Path = ".",
    output_path: str | Path = "data/processed/spa_lmp2_lap_telemetry_report.html",
    dataset_label_file: str | Path = "config/datasets/spa_lmp2_v2_2026-05-21.json",
    config: LapTelemetryReportConfig | None = None,
) -> Path:
    """Build the current Spa core telemetry Plotly HTML report."""

    root = Path(project_root)
    report_config = config or LapTelemetryReportConfig()
    samples = build_labeled_lap_telemetry_samples(
        root / dataset_label_file,
        project_root=root,
        config=report_config,
    )
    figure = create_lap_telemetry_report_figure(
        samples,
        title="Spa LMP2 core lap telemetry",
        metrics=report_config.metrics,
    )
    return write_lap_telemetry_report_html(figure, root / output_path)


def empty_lap_telemetry_samples_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LAP_TELEMETRY_REPORT_SCHEMA)


def prepare_lap_telemetry_report_samples(samples: pl.DataFrame) -> pl.DataFrame:
    """Normalize user-provided samples for report rendering."""

    if samples.is_empty():
        return samples
    if "lap_elapsed_s" not in samples.columns:
        if "elapsed_s" in samples.columns:
            samples = samples.with_columns(pl.col("elapsed_s").alias("lap_elapsed_s"))
        elif {"ts", "lap_start_ts"}.issubset(samples.columns):
            samples = samples.with_columns(
                (pl.col("ts") - pl.col("lap_start_ts")).alias("lap_elapsed_s")
            )
        elif "ts" in samples.columns:
            samples = samples.with_columns(pl.col("ts").alias("lap_elapsed_s"))
    sort_columns = [
        column
        for column in ("run_id", "lap_number", "lap_elapsed_s")
        if column in samples.columns
    ]
    return samples.sort(sort_columns) if sort_columns else samples


def _include_collection_label(
    run: RunLapLabels,
    config: LapTelemetryReportConfig,
) -> bool:
    if config.include_collection_labels is None:
        return True
    return run.collection_label in config.include_collection_labels


def _included_lap_numbers(
    run: RunLapLabels,
    config: LapTelemetryReportConfig,
) -> set[int]:
    return {
        lap_number
        for lap_number in run.valid_laps | run.borderline_laps | run.context_laps
        if run.driver_label_for_lap(lap_number) in config.include_driver_lap_labels
    }


def _with_run_metadata(
    samples: pl.DataFrame,
    labels: DatasetLapLabels,
    run: RunLapLabels,
) -> pl.DataFrame:
    label_frame = pl.DataFrame(
        [
            {
                "lap_number": lap_number,
                "driver_lap_label": run.driver_label_for_lap(lap_number),
            }
            for lap_number in samples["lap_number"].unique().to_list()
        ]
    )
    return (
        samples.join(label_frame, on="lap_number", how="left")
        .with_columns(
            pl.lit(labels.dataset_id).alias("dataset_id"),
            pl.lit(run.run_id).alias("run_id"),
            pl.lit(Path(run.file).name).alias("file_name"),
            pl.lit(run.track).alias("track"),
            pl.lit(run.car_class).alias("car_class"),
            pl.lit(run.collection_label).alias("collection_label"),
            pl.lit(run.labels_quality).alias("labels_quality"),
            pl.lit(run.collection_protocol_id).alias("collection_protocol_id"),
            pl.lit(run.collection_design).alias("collection_design"),
            pl.lit(run.execution_quality).alias("execution_quality"),
        )
        .select(_LAP_TELEMETRY_REPORT_COLUMNS)
    )


def _validate_report_columns(samples: pl.DataFrame, metrics: tuple[str, ...]) -> None:
    unknown_metrics = set(metrics) - set(TELEMETRY_METRICS)
    if unknown_metrics:
        unknown = ", ".join(sorted(unknown_metrics))
        raise ValueError(f"unknown telemetry metrics: {unknown}")
    required = {"lap_elapsed_s", "lap_number", "lap_distance_m", *metrics}
    missing = required - set(samples.columns)
    if missing and not samples.is_empty():
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"lap telemetry samples missing required columns: {missing_text}")


def _sample_group_columns(samples: pl.DataFrame) -> list[str]:
    columns = []
    for column in ("collection_label", "run_id", "lap_number", "driver_lap_label"):
        if column in samples.columns:
            columns.append(column)
    if not columns:
        columns.append("lap_number")
    return columns


def _sample_groups(samples: pl.DataFrame) -> list[dict[str, object]]:
    columns = _sample_group_columns(samples)
    return [
        dict(zip(columns, row, strict=True))
        for row in samples.select(columns).unique().sort(columns).rows()
    ]


def _filter_group(samples: pl.DataFrame, group: dict[str, object]) -> pl.DataFrame:
    filtered = samples
    for column, value in group.items():
        if value is None:
            filtered = filtered.filter(pl.col(column).is_null())
        else:
            filtered = filtered.filter(pl.col(column) == value)
    return filtered.sort("lap_elapsed_s")


def _legend_name(group: dict[str, object]) -> str:
    label = str(group.get("collection_label") or "unknown")
    run_id = str(group.get("run_id") or "run")
    lap_number = group.get("lap_number", "")
    driver_label = str(group.get("driver_lap_label") or "")
    suffix = f" ({driver_label})" if driver_label else ""
    return f"{label} {run_id} L{lap_number}{suffix}"


def _sample_customdata(
    samples: pl.DataFrame,
    group: dict[str, object],
) -> list[list[object]]:
    run_id = group.get("run_id", "")
    collection_label = group.get("collection_label", "")
    driver_label = group.get("driver_lap_label", "")
    lap_number = group.get("lap_number", "")
    return [
        [
            run_id,
            lap_number,
            collection_label,
            driver_label,
            distance_m,
        ]
        for distance_m in samples["lap_distance_m"].to_list()
    ]


def _hover_template(metric: str) -> str:
    metric_label, unit = TELEMETRY_METRICS[metric]
    return (
        f"{metric_label}<br>"
        "run=%{customdata[0]}<br>"
        "lap=%{customdata[1]}<br>"
        "label=%{customdata[2]}<br>"
        "driver_lap=%{customdata[3]}<br>"
        "elapsed=%{x:.2f} s<br>"
        "distance=%{customdata[4]:.1f} m<br>"
        f"value=%{{y:.3f}} {unit}<extra></extra>"
    )


_LAP_TELEMETRY_REPORT_COLUMNS = [
    "dataset_id",
    "run_id",
    "file_name",
    "track",
    "car_class",
    "collection_label",
    "collection_protocol_id",
    "collection_design",
    "execution_quality",
    "labels_quality",
    "driver_lap_label",
    "lap_number",
    "lap_start_ts",
    "lap_end_ts",
    "ts",
    "lap_elapsed_s",
    "lap_distance_m",
    "brake_pct",
    "throttle_pct",
    "ground_speed_kph",
    "fuel_level_l",
]

_LAP_TELEMETRY_REPORT_SCHEMA = {
    "dataset_id": pl.String,
    "run_id": pl.String,
    "file_name": pl.String,
    "track": pl.String,
    "car_class": pl.String,
    "collection_label": pl.String,
    "collection_protocol_id": pl.String,
    "collection_design": pl.String,
    "execution_quality": pl.String,
    "labels_quality": pl.String,
    "driver_lap_label": pl.String,
    "lap_number": pl.Int64,
    "lap_start_ts": pl.Float64,
    "lap_end_ts": pl.Float64,
    "ts": pl.Float64,
    "lap_elapsed_s": pl.Float64,
    "lap_distance_m": pl.Float64,
    "brake_pct": pl.Float64,
    "throttle_pct": pl.Float64,
    "ground_speed_kph": pl.Float64,
    "fuel_level_l": pl.Float64,
}
