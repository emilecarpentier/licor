from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from licor.analysis.lap_summary import load_dataset_lap_labels
from licor.analysis.zone_detection import build_lap_telemetry
from licor.ingestion import LmuTelemetryDatabase


EXPERIMENTAL_TYRE_CHANNELS = {
    "TyresCarcassTemp": "carcass_temp_c",
    "TyresRubberTemp": "rubber_temp_c",
    "TyresTempCentre": "centre_temp_c",
    "TyresRimTemp": "rim_temp_c",
}


@dataclass(frozen=True)
class ExperimentalZoneDynamicsConfig:
    brake_threshold_pct: float = 5.0
    high_brake_threshold_pct: float = 80.0
    baseline_intensity: str = "none"
    valid_labels: tuple[str, ...] = ("valid",)
    exclude_detected_lico_from_baseline: bool = True


@dataclass(frozen=True)
class ExperimentalZoneDynamicsBaselineConfig:
    baseline_intensity: str = "none"
    exclude_detected_lico_from_baseline: bool = True


def build_experimental_lap_telemetry(
    telemetry: LmuTelemetryDatabase,
    *,
    lap_numbers: set[int] | None = None,
) -> pl.DataFrame:
    """Extend normalized lap telemetry with average tyre temperature channels."""

    samples = build_lap_telemetry(telemetry, lap_numbers=lap_numbers)
    if samples.is_empty():
        return samples

    channels = telemetry.channels()
    enriched = samples.sort("ts")
    for channel_name, alias in EXPERIMENTAL_TYRE_CHANNELS.items():
        if channel_name not in channels:
            continue
        channel = telemetry.fixed_channel(channel_name)
        if channel.is_empty():
            continue
        mean_frame = channel.select(
            "ts",
            (
                (
                    pl.col("value1")
                    + pl.col("value2")
                    + pl.col("value3")
                    + pl.col("value4")
                )
                / 4.0
            ).alias(alias),
        ).sort("ts")
        enriched = enriched.join_asof(mean_frame, on="ts", strategy="backward")
    return enriched.sort(["lap_number", "ts"])


def build_labeled_experimental_lap_samples(
    *,
    dataset_label_file: str | Path,
    project_root: str | Path = ".",
) -> pl.DataFrame:
    """Rebuild labelled lap telemetry with experimental tyre context columns."""

    labels = load_dataset_lap_labels(dataset_label_file)
    root = Path(project_root)
    frames = []
    for run in labels.runs:
        if not run.include_in_lap_summary:
            continue
        lap_numbers = set(run.valid_laps | run.borderline_laps)
        if not lap_numbers:
            continue
        with LmuTelemetryDatabase(root / run.file) as telemetry:
            samples = build_experimental_lap_telemetry(telemetry, lap_numbers=lap_numbers)
        if samples.is_empty():
            continue
        frames.append(
            samples.with_columns(
                pl.lit(run.run_id).alias("run_id"),
                pl.lit(Path(run.file).name).alias("file_name"),
                pl.lit(run.collection_label).alias("collection_label"),
                pl.lit(run.collection_design).alias("collection_design"),
                pl.lit(run.execution_quality).alias("execution_quality"),
            )
        )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal").sort(["run_id", "lap_number", "ts"])


def summarize_experimental_zone_dynamics(
    zone_passes: pl.DataFrame,
    lap_samples: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsConfig | None = None,
) -> pl.DataFrame:
    """Build an experimental per-zone-pass dynamics table."""

    dynamics_config = config or ExperimentalZoneDynamicsConfig()
    if zone_passes.is_empty() or lap_samples.is_empty():
        return _empty_experimental_zone_dynamics_frame()

    required_zone_columns = {
        "run_id",
        "lap_number",
        "zone_id",
        "display_label",
        "validity_label",
        "zone_start_m",
        "zone_end_m",
        "fuel_used_l",
        "elapsed_time_s",
        "brake_start_m",
        "brake_start_speed_kph",
        "lico_start_distance_before_brake_m",
        "collection_design",
        "lico_intensity",
        "has_lico",
    }
    required_sample_columns = {
        "run_id",
        "lap_number",
        "ts",
        "lap_distance_m",
        "ground_speed_kph",
        "brake_pct",
    }
    _require_columns(zone_passes, required_zone_columns, "zone passes")
    _require_columns(lap_samples, required_sample_columns, "lap samples")

    comparable = zone_passes.filter(pl.col("validity_label").is_in(dynamics_config.valid_labels))
    if comparable.is_empty():
        return _empty_experimental_zone_dynamics_frame()

    stint_map = _stint_index_map(comparable)
    sample_groups = _sample_group_map(lap_samples)
    rows: list[dict[str, object]] = []
    for row in comparable.iter_rows(named=True):
        sample_key = (str(row["run_id"]), int(row["lap_number"]))
        lap_frame = sample_groups.get(sample_key)
        if lap_frame is None or lap_frame.is_empty():
            continue
        zone_samples = lap_frame.filter(
            (pl.col("lap_distance_m") >= float(row["zone_start_m"]))
            & (pl.col("lap_distance_m") <= float(row["zone_end_m"]))
        ).sort("ts")
        if zone_samples.is_empty():
            continue
        dynamics_row = _zone_dynamics_row(
            row,
            zone_samples=zone_samples,
            stint_index=stint_map.get(sample_key),
            config=dynamics_config,
        )
        rows.append(dynamics_row)

    if not rows:
        return _empty_experimental_zone_dynamics_frame()

    dynamics = pl.DataFrame(rows, schema=_EXPERIMENTAL_ZONE_DYNAMICS_SCHEMA, strict=False).select(
        _EXPERIMENTAL_ZONE_DYNAMICS_COLUMNS
    )
    return _attach_baseline_deltas(dynamics, config=dynamics_config).sort(
        ["zone_id", "run_id", "lap_number"]
    )


def build_experimental_zone_dynamics(
    zone_passes: pl.DataFrame,
    lap_telemetry: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsConfig | None = None,
) -> pl.DataFrame:
    """Compatibility wrapper with an explicit experimental builder name."""

    return summarize_experimental_zone_dynamics(zone_passes, lap_telemetry, config=config)


def attach_baseline_deltas_to_experimental_zone_dynamics(
    experimental_passes: pl.DataFrame,
    baseline_passes: pl.DataFrame | None = None,
    *,
    config: ExperimentalZoneDynamicsBaselineConfig | None = None,
) -> pl.DataFrame:
    """Attach baseline means/deltas to an existing experimental dynamics frame."""

    baseline_config = config or ExperimentalZoneDynamicsBaselineConfig()
    dynamics_config = ExperimentalZoneDynamicsConfig(
        baseline_intensity=baseline_config.baseline_intensity,
        exclude_detected_lico_from_baseline=baseline_config.exclude_detected_lico_from_baseline,
    )
    if baseline_passes is None or baseline_passes.is_empty():
        return _attach_baseline_deltas(experimental_passes, config=dynamics_config)
    combined = pl.concat([baseline_passes, experimental_passes], how="diagonal_relaxed")
    attached = _attach_baseline_deltas(combined, config=dynamics_config)
    return attached.join(
        experimental_passes.select("run_id", "lap_number", "zone_id").unique(),
        on=["run_id", "lap_number", "zone_id"],
        how="semi",
    )


def _zone_dynamics_row(
    zone_pass_row: dict[str, object],
    *,
    zone_samples: pl.DataFrame,
    stint_index: int | None,
    config: ExperimentalZoneDynamicsConfig,
) -> dict[str, object]:
    first = zone_samples.row(0, named=True)
    last = zone_samples.row(-1, named=True)
    zone_start_ts = float(first["ts"])
    zone_end_ts = float(last["ts"])
    brake_mask = pl.col("brake_pct") >= config.brake_threshold_pct
    brake_samples = zone_samples.filter(brake_mask)

    apex_index = int(zone_samples["ground_speed_kph"].arg_min())
    apex = zone_samples.row(apex_index, named=True)
    apex_ts = float(apex["ts"])

    zone_start_speed_kph = _optional_float(first.get("ground_speed_kph"))
    apex_distance_m = _optional_float(apex.get("lap_distance_m"))
    apex_speed_kph = _optional_float(apex.get("ground_speed_kph"))
    brake_peak_pct = float(zone_samples["brake_pct"].max())

    if brake_samples.is_empty():
        time_start_to_brake_s = None
        time_brake_to_apex_s = None
        brake_duration_s = 0.0
        brake_area_pct_s = 0.0
        time_above_80pct_brake_s = 0.0
        brake_release_rate_pct_per_s = None
    else:
        first_brake = brake_samples.row(0, named=True)
        first_brake_ts = float(first_brake["ts"])
        time_start_to_brake_s = first_brake_ts - zone_start_ts
        time_brake_to_apex_s = apex_ts - first_brake_ts
        brake_duration_s = _duration_above_threshold(
            zone_samples,
            threshold=config.brake_threshold_pct,
        )
        brake_area_pct_s = _integrated_brake_area(zone_samples, threshold=config.brake_threshold_pct)
        time_above_80pct_brake_s = _duration_above_threshold(
            zone_samples,
            threshold=config.high_brake_threshold_pct,
        )
        brake_release_rate_pct_per_s = _brake_release_rate(
            zone_samples,
            threshold=config.brake_threshold_pct,
        )

    output = {
        "run_id": str(zone_pass_row["run_id"]),
        "lap_number": int(zone_pass_row["lap_number"]),
        "zone_id": str(zone_pass_row["zone_id"]),
        "display_label": str(zone_pass_row["display_label"]),
        "lico_intensity": str(zone_pass_row["lico_intensity"]),
        "collection_design": str(zone_pass_row.get("collection_design") or ""),
        "has_lico": bool(zone_pass_row["has_lico"]),
        "validity_label": str(zone_pass_row["validity_label"]),
        "stint_index": stint_index,
        "zone_start_m": float(zone_pass_row["zone_start_m"]),
        "zone_end_m": float(zone_pass_row["zone_end_m"]),
        "zone_start_speed_kph": zone_start_speed_kph,
        "lico_distance_before_brake_m": _coalesced_distance_before_brake(zone_pass_row),
        "fuel_used_l": _optional_float(zone_pass_row.get("fuel_used_l")),
        "elapsed_time_s": _optional_float(zone_pass_row.get("elapsed_time_s")),
        "brake_start_m": _optional_float(zone_pass_row.get("brake_start_m")),
        "brake_start_speed_kph": _optional_float(zone_pass_row.get("brake_start_speed_kph")),
        "apex_distance_m": apex_distance_m,
        "apex_speed_kph": apex_speed_kph,
        "exit_speed_kph": _optional_float(zone_pass_row.get("exit_speed_kph")),
        "time_start_to_brake_s": time_start_to_brake_s,
        "time_brake_to_apex_s": time_brake_to_apex_s,
        "time_apex_to_end_s": zone_end_ts - apex_ts,
        "brake_peak_pct": brake_peak_pct,
        "brake_duration_s": brake_duration_s,
        "brake_area_pct_s": brake_area_pct_s,
        "time_above_80pct_brake_s": time_above_80pct_brake_s,
        "brake_release_rate_pct_per_s": brake_release_rate_pct_per_s,
        "carcass_temp_zone_start_c": _optional_float(first.get("carcass_temp_c")),
        "rubber_temp_zone_start_c": _optional_float(first.get("rubber_temp_c")),
        "centre_temp_zone_start_c": _optional_float(first.get("centre_temp_c")),
        "rim_temp_zone_start_c": _optional_float(first.get("rim_temp_c")),
    }
    return output


def _attach_baseline_deltas(
    dynamics: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsConfig,
) -> pl.DataFrame:
    baseline_condition = pl.col("lico_intensity") == config.baseline_intensity
    if "collection_design" in dynamics.columns:
        baseline_condition = baseline_condition | (pl.col("collection_design") == "baseline")
    baseline = dynamics.filter(baseline_condition)
    if config.exclude_detected_lico_from_baseline and "has_lico" in baseline.columns:
        baseline = baseline.filter(~pl.col("has_lico"))
    if baseline.is_empty():
        return dynamics.with_columns(_null_baseline_columns())

    baseline_summary = baseline.group_by("zone_id").agg(
        pl.col("fuel_used_l").mean().alias("baseline_mean_fuel_used_l"),
        pl.col("elapsed_time_s").mean().alias("baseline_mean_elapsed_time_s"),
        pl.col("brake_start_m").mean().alias("baseline_mean_brake_start_m"),
        pl.col("brake_start_speed_kph").mean().alias("baseline_mean_brake_start_speed_kph"),
        pl.col("apex_speed_kph").mean().alias("baseline_mean_apex_speed_kph"),
        pl.col("exit_speed_kph").mean().alias("baseline_mean_exit_speed_kph"),
        pl.col("carcass_temp_zone_start_c").mean().alias("baseline_mean_carcass_temp_zone_start_c"),
        pl.col("rubber_temp_zone_start_c").mean().alias("baseline_mean_rubber_temp_zone_start_c"),
        pl.col("centre_temp_zone_start_c").mean().alias("baseline_mean_centre_temp_zone_start_c"),
        pl.col("rim_temp_zone_start_c").mean().alias("baseline_mean_rim_temp_zone_start_c"),
    )
    return (
        dynamics.join(baseline_summary, on="zone_id", how="left")
        .with_columns(
            (
                pl.col("baseline_mean_fuel_used_l") - pl.col("fuel_used_l")
            ).alias("fuel_saved_vs_baseline_l"),
            (
                pl.col("elapsed_time_s") - pl.col("baseline_mean_elapsed_time_s")
            ).alias("time_lost_vs_baseline_s"),
            (
                pl.col("brake_start_m") - pl.col("baseline_mean_brake_start_m")
            ).alias("brake_start_delta_vs_baseline_m"),
            (
                pl.col("brake_start_speed_kph")
                - pl.col("baseline_mean_brake_start_speed_kph")
            ).alias("brake_start_speed_delta_vs_baseline_kph"),
            (
                pl.col("apex_speed_kph") - pl.col("baseline_mean_apex_speed_kph")
            ).alias("apex_speed_delta_vs_baseline_kph"),
            (
                pl.col("exit_speed_kph") - pl.col("baseline_mean_exit_speed_kph")
            ).alias("exit_speed_delta_vs_baseline_kph"),
            (
                pl.col("carcass_temp_zone_start_c")
                - pl.col("baseline_mean_carcass_temp_zone_start_c")
            ).alias("carcass_temp_zone_start_delta_vs_baseline_c"),
            (
                pl.col("rubber_temp_zone_start_c")
                - pl.col("baseline_mean_rubber_temp_zone_start_c")
            ).alias("rubber_temp_zone_start_delta_vs_baseline_c"),
            (
                pl.col("centre_temp_zone_start_c")
                - pl.col("baseline_mean_centre_temp_zone_start_c")
            ).alias("centre_temp_zone_start_delta_vs_baseline_c"),
            (
                pl.col("rim_temp_zone_start_c") - pl.col("baseline_mean_rim_temp_zone_start_c")
            ).alias("rim_temp_zone_start_delta_vs_baseline_c"),
        )
        .select(_EXPERIMENTAL_ZONE_DYNAMICS_WITH_BASELINE_COLUMNS)
    )


def _sample_group_map(samples: pl.DataFrame) -> dict[tuple[str, int], pl.DataFrame]:
    groups = {}
    for keys, frame in samples.sort(["run_id", "lap_number", "ts"]).group_by(
        ["run_id", "lap_number"], maintain_order=True
    ):
        run_id, lap_number = keys
        groups[(str(run_id), int(lap_number))] = frame
    return groups


def _stint_index_map(zone_passes: pl.DataFrame) -> dict[tuple[str, int], int]:
    mapping = {}
    lap_rows = (
        zone_passes.select("run_id", "lap_number")
        .unique()
        .sort(["run_id", "lap_number"])
        .iter_rows(named=True)
    )
    current_run = None
    current_index = 0
    for row in lap_rows:
        run_id = str(row["run_id"])
        if run_id != current_run:
            current_run = run_id
            current_index = 1
        else:
            current_index += 1
        mapping[(run_id, int(row["lap_number"]))] = current_index
    return mapping


def _duration_above_threshold(samples: pl.DataFrame, *, threshold: float) -> float:
    return _integrate_mask(samples, mask=samples["brake_pct"] >= threshold)


def _integrated_brake_area(samples: pl.DataFrame, *, threshold: float) -> float:
    durations = _sample_durations(samples)
    brake_values = samples["brake_pct"].to_list()
    total = 0.0
    for duration_s, brake_pct in zip(durations, brake_values):
        if brake_pct >= threshold:
            total += duration_s * float(brake_pct) / 100.0
    return total


def _integrate_mask(samples: pl.DataFrame, *, mask: pl.Series) -> float:
    durations = _sample_durations(samples)
    include = mask.to_list()
    return sum(duration_s for duration_s, keep in zip(durations, include) if keep)


def _sample_durations(samples: pl.DataFrame) -> list[float]:
    timestamps = [float(value) for value in samples["ts"].to_list()]
    if len(timestamps) <= 1:
        return [0.0] * len(timestamps)
    durations = [
        max(0.0, right - left) for left, right in zip(timestamps, timestamps[1:])
    ]
    durations.append(durations[-1] if durations else 0.0)
    return durations


def _brake_release_rate(samples: pl.DataFrame, *, threshold: float) -> float | None:
    active = samples.filter(pl.col("brake_pct") >= threshold).sort("ts")
    if active.height <= 1:
        return None
    peak_index = int(active["brake_pct"].arg_max())
    peak = active.row(peak_index, named=True)
    release = active.row(-1, named=True)
    delta_pct = float(peak["brake_pct"]) - float(release["brake_pct"])
    delta_s = float(release["ts"]) - float(peak["ts"])
    if delta_pct <= 0.0 or delta_s <= 0.0:
        return None
    return delta_pct / delta_s


def _coalesced_distance_before_brake(row: dict[str, object]) -> float:
    value = row.get("lico_start_distance_before_brake_m")
    if value is None:
        return 0.0
    return float(value)


def _null_baseline_columns() -> list[pl.Expr]:
    return [
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_fuel_used_l"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_elapsed_time_s"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_brake_start_m"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_brake_start_speed_kph"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_apex_speed_kph"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_exit_speed_kph"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_carcass_temp_zone_start_c"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_rubber_temp_zone_start_c"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_centre_temp_zone_start_c"),
        pl.lit(None, dtype=pl.Float64).alias("baseline_mean_rim_temp_zone_start_c"),
        pl.lit(None, dtype=pl.Float64).alias("fuel_saved_vs_baseline_l"),
        pl.lit(None, dtype=pl.Float64).alias("time_lost_vs_baseline_s"),
        pl.lit(None, dtype=pl.Float64).alias("brake_start_delta_vs_baseline_m"),
        pl.lit(None, dtype=pl.Float64).alias("brake_start_speed_delta_vs_baseline_kph"),
        pl.lit(None, dtype=pl.Float64).alias("apex_speed_delta_vs_baseline_kph"),
        pl.lit(None, dtype=pl.Float64).alias("exit_speed_delta_vs_baseline_kph"),
        pl.lit(None, dtype=pl.Float64).alias("carcass_temp_zone_start_delta_vs_baseline_c"),
        pl.lit(None, dtype=pl.Float64).alias("rubber_temp_zone_start_delta_vs_baseline_c"),
        pl.lit(None, dtype=pl.Float64).alias("centre_temp_zone_start_delta_vs_baseline_c"),
        pl.lit(None, dtype=pl.Float64).alias("rim_temp_zone_start_delta_vs_baseline_c"),
    ]


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number):
        return None
    return number


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{label} are missing required columns: {missing_text}")


_EXPERIMENTAL_ZONE_DYNAMICS_COLUMNS = [
    "run_id",
    "lap_number",
    "zone_id",
    "display_label",
    "lico_intensity",
    "collection_design",
    "has_lico",
    "validity_label",
    "stint_index",
    "zone_start_m",
    "zone_end_m",
    "zone_start_speed_kph",
    "lico_distance_before_brake_m",
    "fuel_used_l",
    "elapsed_time_s",
    "brake_start_m",
    "brake_start_speed_kph",
    "apex_distance_m",
    "apex_speed_kph",
    "exit_speed_kph",
    "time_start_to_brake_s",
    "time_brake_to_apex_s",
    "time_apex_to_end_s",
    "brake_peak_pct",
    "brake_duration_s",
    "brake_area_pct_s",
    "time_above_80pct_brake_s",
    "brake_release_rate_pct_per_s",
    "carcass_temp_zone_start_c",
    "rubber_temp_zone_start_c",
    "centre_temp_zone_start_c",
    "rim_temp_zone_start_c",
]

_EXPERIMENTAL_ZONE_DYNAMICS_WITH_BASELINE_COLUMNS = [
    *_EXPERIMENTAL_ZONE_DYNAMICS_COLUMNS,
    "baseline_mean_fuel_used_l",
    "baseline_mean_elapsed_time_s",
    "baseline_mean_brake_start_m",
    "baseline_mean_brake_start_speed_kph",
    "baseline_mean_apex_speed_kph",
    "baseline_mean_exit_speed_kph",
    "baseline_mean_carcass_temp_zone_start_c",
    "baseline_mean_rubber_temp_zone_start_c",
    "baseline_mean_centre_temp_zone_start_c",
    "baseline_mean_rim_temp_zone_start_c",
    "fuel_saved_vs_baseline_l",
    "time_lost_vs_baseline_s",
    "brake_start_delta_vs_baseline_m",
    "brake_start_speed_delta_vs_baseline_kph",
    "apex_speed_delta_vs_baseline_kph",
    "exit_speed_delta_vs_baseline_kph",
    "carcass_temp_zone_start_delta_vs_baseline_c",
    "rubber_temp_zone_start_delta_vs_baseline_c",
    "centre_temp_zone_start_delta_vs_baseline_c",
    "rim_temp_zone_start_delta_vs_baseline_c",
]

_EXPERIMENTAL_ZONE_DYNAMICS_SCHEMA = {
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_intensity": pl.String,
    "collection_design": pl.String,
    "has_lico": pl.Boolean,
    "validity_label": pl.String,
    "stint_index": pl.Int64,
    "zone_start_m": pl.Float64,
    "zone_end_m": pl.Float64,
    "zone_start_speed_kph": pl.Float64,
    "lico_distance_before_brake_m": pl.Float64,
    "fuel_used_l": pl.Float64,
    "elapsed_time_s": pl.Float64,
    "brake_start_m": pl.Float64,
    "brake_start_speed_kph": pl.Float64,
    "apex_distance_m": pl.Float64,
    "apex_speed_kph": pl.Float64,
    "exit_speed_kph": pl.Float64,
    "time_start_to_brake_s": pl.Float64,
    "time_brake_to_apex_s": pl.Float64,
    "time_apex_to_end_s": pl.Float64,
    "brake_peak_pct": pl.Float64,
    "brake_duration_s": pl.Float64,
    "brake_area_pct_s": pl.Float64,
    "time_above_80pct_brake_s": pl.Float64,
    "brake_release_rate_pct_per_s": pl.Float64,
    "carcass_temp_zone_start_c": pl.Float64,
    "rubber_temp_zone_start_c": pl.Float64,
    "centre_temp_zone_start_c": pl.Float64,
    "rim_temp_zone_start_c": pl.Float64,
    "baseline_mean_fuel_used_l": pl.Float64,
    "baseline_mean_elapsed_time_s": pl.Float64,
    "baseline_mean_brake_start_m": pl.Float64,
    "baseline_mean_brake_start_speed_kph": pl.Float64,
    "baseline_mean_apex_speed_kph": pl.Float64,
    "baseline_mean_exit_speed_kph": pl.Float64,
    "baseline_mean_carcass_temp_zone_start_c": pl.Float64,
    "baseline_mean_rubber_temp_zone_start_c": pl.Float64,
    "baseline_mean_centre_temp_zone_start_c": pl.Float64,
    "baseline_mean_rim_temp_zone_start_c": pl.Float64,
    "fuel_saved_vs_baseline_l": pl.Float64,
    "time_lost_vs_baseline_s": pl.Float64,
    "brake_start_delta_vs_baseline_m": pl.Float64,
    "brake_start_speed_delta_vs_baseline_kph": pl.Float64,
    "apex_speed_delta_vs_baseline_kph": pl.Float64,
    "exit_speed_delta_vs_baseline_kph": pl.Float64,
    "carcass_temp_zone_start_delta_vs_baseline_c": pl.Float64,
    "rubber_temp_zone_start_delta_vs_baseline_c": pl.Float64,
    "centre_temp_zone_start_delta_vs_baseline_c": pl.Float64,
    "rim_temp_zone_start_delta_vs_baseline_c": pl.Float64,
}


def _empty_experimental_zone_dynamics_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_EXPERIMENTAL_ZONE_DYNAMICS_SCHEMA)
