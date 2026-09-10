"""Score a completed Paul Ricard static live-cue session without refitting it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import polars as pl

from licor.analysis import extract_zone_passes, load_track_zone_table
from licor.analysis.zone_detection import build_lap_telemetry
from licor.ingestion import LmuTelemetryDatabase
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import (
    _effective_lap_distance_m,
    _stabilize_effective_lap_distance_m,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    PROJECT_ROOT
    / "data/processed/experimental/paul_ricard_prediction_validation_2026_09"
)
DEFAULT_PACK_DIR = EXPERIMENT_ROOT / "pilot_pack"
ZONE_CONFIG = PROJECT_ROOT / "config/track_zones/paul_ricard_lmp2_zones.draft.json"
REQUIRED_SESSION_FILES = (
    "events.csv",
    "telemetry.csv",
    "lap_schedule.csv",
    "session_config.json",
    "run_metadata_template.json",
    "pack_manifest.json",
)
SAMPLING_GAP_THRESHOLD_S = 0.05


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def latest_session_dir(root: Path = EXPERIMENT_ROOT / "sessions") -> Path:
    sessions = sorted(path for path in root.iterdir() if path.is_dir())
    if not sessions:
        raise FileNotFoundError(f"No live validation sessions found under {root}")
    return sessions[-1]


def build_lap_validation(
    telemetry: pl.DataFrame,
    schedule: pl.DataFrame,
    *,
    predicted_fuel_saved_l: float,
    predicted_time_lost_s: float,
) -> pl.DataFrame:
    scored = telemetry.filter(
        pl.col("lap_number").is_in(schedule["lap_number"].to_list())
    )
    laps = (
        scored.sort("ts")
        .group_by("lap_number")
        .agg(
            pl.len().alias("sample_count"),
            pl.col("lap_distance_m").min().alias("min_lap_distance_m"),
            pl.col("lap_distance_m").max().alias("max_lap_distance_m"),
            pl.col("lap_distance_m").last().alias("final_lap_distance_m"),
            (pl.col("ts").max() - pl.col("ts").min()).alias("lap_time_s"),
            (pl.col("fuel_level_l").first() - pl.col("fuel_level_l").last()).alias(
                "fuel_used_l"
            ),
        )
        .join(schedule.select("lap_number", "role", "cue_enabled"), on="lap_number")
        .sort("lap_number")
    )
    comparisons = _build_reference_comparisons(
        laps,
        group_columns=(),
        fuel_column="fuel_used_l",
        time_column="lap_time_s",
    )
    return laps.join(comparisons, on="lap_number", how="left").with_columns(
        (pl.col("reference_fuel_used_l") - pl.col("fuel_used_l")).alias(
            "fuel_saved_vs_push_reference_l"
        ),
        (pl.col("lap_time_s") - pl.col("reference_time_s")).alias(
            "time_lost_vs_push_reference_s"
        ),
        pl.lit(predicted_fuel_saved_l).alias("plan_predicted_fuel_saved_l"),
        pl.lit(predicted_time_lost_s).alias("plan_predicted_time_lost_s"),
        (
            (pl.col("min_lap_distance_m") <= 10.0)
            & (pl.col("final_lap_distance_m") >= 5700.0)
        ).alias("complete_distance_coverage"),
    )


def build_sampling_gap_table(
    telemetry: pl.DataFrame, enabled_events: pl.DataFrame
) -> pl.DataFrame:
    timeline = telemetry.sort("ts").select(
        pl.col("ts").alias("sample_ts"),
        (pl.col("ts").shift(-1) - pl.col("ts")).alias("sampling_gap_after_cue_s"),
    )
    return (
        enabled_events.select("lap_number", "zone_id", "sample_ts")
        .join(timeline, on="sample_ts", how="left")
        .with_columns(
            (pl.col("sampling_gap_after_cue_s") > SAMPLING_GAP_THRESHOLD_S).alias(
                "sampling_gap_after_cue"
            )
        )
    )


def project_telemetry_distance(
    telemetry: pl.DataFrame, *, track_length_m: float | None
) -> pl.DataFrame:
    """Apply the exact live-runtime distance projection to a recorded CSV."""
    anchors: dict[int, LmuLiveTelemetrySample] = {}
    previous: dict[int, float] = {}
    projected_rows: list[dict[str, object]] = []
    for row in telemetry.sort("ts").iter_rows(named=True):
        sample = LmuLiveTelemetrySample(**row)
        lap_number = sample.lap_number
        effective_m, anchor, method, projection_age_s = _effective_lap_distance_m(
            sample,
            anchor=anchors.get(lap_number),
            track_length_m=track_length_m,
        )
        anchors[lap_number] = anchor
        effective_m = _stabilize_effective_lap_distance_m(
            effective_m,
            previous_distance_m=previous.get(lap_number),
            track_length_m=track_length_m,
        )
        previous[lap_number] = effective_m
        projected = dict(row)
        projected["raw_lap_distance_m"] = row["lap_distance_m"]
        projected["lap_distance_m"] = effective_m
        projected["distance_projection_method"] = method
        projected["distance_projection_age_s"] = projection_age_s
        projected_rows.append(projected)
    return pl.DataFrame(projected_rows)


def _build_reference_comparisons(
    rows: pl.DataFrame,
    *,
    group_columns: tuple[str, ...],
    fuel_column: str,
    time_column: str,
) -> pl.DataFrame:
    references = rows.filter(pl.col("role") == "push")
    if "has_lico" in rows.columns:
        references = references.filter(~pl.col("has_lico"))
    targets = rows.filter(pl.col("role") == "lico")
    comparisons: list[dict[str, object]] = []
    for target in targets.iter_rows(named=True):
        local = references
        for column in group_columns:
            local = local.filter(pl.col(column) == target[column])
        if local.is_empty():
            raise ValueError(f"No clean push reference for lap {target['lap_number']}")
        target_lap = int(target["lap_number"])
        before = local.filter(pl.col("lap_number") < target_lap).sort("lap_number")
        after = local.filter(pl.col("lap_number") > target_lap).sort("lap_number")
        if not before.is_empty() and not after.is_empty():
            left = before.row(-1, named=True)
            right = after.row(0, named=True)
            span = int(right["lap_number"]) - int(left["lap_number"])
            weight = (target_lap - int(left["lap_number"])) / span
            reference_fuel = float(left[fuel_column]) + weight * (
                float(right[fuel_column]) - float(left[fuel_column])
            )
            reference_time = float(left[time_column]) + weight * (
                float(right[time_column]) - float(left[time_column])
            )
            method = "bracketing_linear_interpolation"
            source_laps = f"{left['lap_number']}|{right['lap_number']}"
        else:
            reference = min(
                local.iter_rows(named=True),
                key=lambda row: abs(int(row["lap_number"]) - target_lap),
            )
            reference_fuel = float(reference[fuel_column])
            reference_time = float(reference[time_column])
            method = "nearest_clean_push_fallback"
            source_laps = str(reference["lap_number"])
        comparisons.append(
            {
                "lap_number": target_lap,
                **{column: target[column] for column in group_columns},
                "reference_method": method,
                "reference_laps": source_laps,
                "reference_fuel_used_l": reference_fuel,
                "reference_time_s": reference_time,
            }
        )
    return pl.DataFrame(comparisons)


def validate_event_coverage(
    events: pl.DataFrame, schedule: pl.DataFrame, plan: pl.DataFrame
) -> None:
    scored_laps = schedule["lap_number"].to_list()
    zones = plan["zone_id"].to_list()
    scored = events.filter(pl.col("lap_number").is_in(scored_laps))
    expected = {(lap, zone) for lap in scored_laps for zone in zones}
    actual = scored.select("lap_number", "zone_id").rows()
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Session has missing or duplicate scored cue crossings")
    enabled_laps = schedule.filter(pl.col("cue_enabled"))["lap_number"].to_list()
    expected_enabled = {(lap, zone) for lap in enabled_laps for zone in zones}
    actual_enabled = (
        scored.filter(pl.col("cue_enabled")).select("lap_number", "zone_id").rows()
    )
    if (
        len(actual_enabled) != len(expected_enabled)
        or set(actual_enabled) != expected_enabled
    ):
        raise ValueError("Session audible cue set disagrees with the lap schedule")
    if scored.filter(pl.col("cue_error_m").abs() > pl.col("cue_tolerance_m")).height:
        raise ValueError("Session contains a scored cue outside its distance tolerance")


def validate_observation_coverage(
    observations: pl.DataFrame, *, expected_observations: int
) -> int:
    """Require every scheduled row while preserving failed LICO executions."""
    if observations.height != expected_observations:
        raise ValueError("Not every audible cue has a zone observation")
    return int(observations["has_lico"].sum())


def build_refit_blockers(
    *,
    metadata_complete: bool,
    lap_quality_resolved: bool,
    telemetry_duckdb_linked: bool,
    audible_gap_count: int,
) -> list[str]:
    blockers = ["CSV-only evaluation is not authoritative"]
    if not metadata_complete:
        blockers.append("operator context metadata are incomplete")
    if not lap_quality_resolved:
        blockers.append(
            "driver reports unclean laps but their lap numbers are unknown"
        )
    if not telemetry_duckdb_linked:
        blockers.append("no authoritative session DuckDB is linked")
    if audible_gap_count:
        blockers.append(
            "system beep creates treatment-correlated telemetry gaps at audible cues"
        )
    return blockers


def build_zone_validation(
    telemetry: pl.DataFrame,
    schedule: pl.DataFrame,
    events: pl.DataFrame,
    plan: pl.DataFrame,
    *,
    zone_config_path: Path = ZONE_CONFIG,
    measure_sampling_gaps: bool = True,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    scored_laps = schedule["lap_number"].to_list()
    track_lengths = plan["track_length_m"].drop_nulls().unique().to_list()
    track_length_m = float(track_lengths[0]) if track_lengths else None
    samples = project_telemetry_distance(
        telemetry.filter(pl.col("lap_number").is_in(scored_laps)),
        track_length_m=track_length_m,
    ).rename({"speed_kph": "ground_speed_kph"})
    passes = extract_zone_passes(samples, load_track_zone_table(zone_config_path))
    lap_roles = schedule.select("lap_number", "role", "cue_enabled").with_columns(
        pl.when(pl.col("role") == "push")
        .then(pl.lit("none"))
        .otherwise(pl.lit("live_static"))
        .alias("__lico_intensity"),
        pl.when(pl.col("role") == "push")
        .then(pl.lit("baseline"))
        .otherwise(pl.lit("recommendation_execution"))
        .alias("__collection_design"),
    )
    passes = (
        passes.join(lap_roles, on="lap_number")
        .with_columns(
            pl.col("__lico_intensity").alias("lico_intensity"),
            pl.col("__collection_design").alias("collection_design"),
        )
        .drop("__lico_intensity", "__collection_design")
    )
    comparisons = _build_reference_comparisons(
        passes,
        group_columns=("zone_id",),
        fuel_column="fuel_used_l",
        time_column="elapsed_time_s",
    )
    lico_points = (
        passes.filter(pl.col("role") == "lico")
        .join(comparisons, on=("lap_number", "zone_id"))
        .rename(
            {
                "lico_start_distance_before_brake_m": "actual_lico_distance_before_brake_m"
            }
        )
        .with_columns(
            (pl.col("reference_fuel_used_l") - pl.col("fuel_used_l")).alias(
                "observed_fuel_saved_l"
            ),
            (pl.col("elapsed_time_s") - pl.col("reference_time_s")).alias(
                "observed_time_lost_s"
            ),
        )
    )
    enabled_events = events.filter(
        pl.col("cue_enabled") & pl.col("lap_number").is_in(scored_laps)
    )
    if measure_sampling_gaps:
        gaps = build_sampling_gap_table(telemetry, enabled_events)
    else:
        gaps = enabled_events.select("lap_number", "zone_id").with_columns(
            pl.lit(None).cast(pl.Float64).alias("sampling_gap_after_cue_s"),
            pl.lit(False).alias("sampling_gap_after_cue"),
        )
    plan_columns = plan.select(
        "zone_id",
        "selected_lico_distance_m",
        "expected_fuel_saved_l",
        "expected_time_lost_s",
    )
    observations = (
        lico_points.join(plan_columns, on="zone_id")
        .join(
            enabled_events.select(
                "lap_number",
                "zone_id",
                "cue_error_m",
                "trigger_status",
                "cue_distance_method",
                "distance_projection_age_s",
            ),
            on=("lap_number", "zone_id"),
        )
        .join(gaps, on=("lap_number", "zone_id"))
        .with_columns(
            (
                pl.col("actual_lico_distance_before_brake_m")
                - pl.col("selected_lico_distance_m")
            ).alias("lico_distance_error_m"),
            (pl.col("observed_fuel_saved_l") - pl.col("expected_fuel_saved_l")).alias(
                "fuel_prediction_error_l"
            ),
            (pl.col("observed_time_lost_s") - pl.col("expected_time_lost_s")).alias(
                "time_prediction_error_s"
            ),
        )
        .select(
            "lap_number",
            "zone_id",
            "display_label",
            "role",
            "cue_enabled",
            "validity_label",
            "has_lico",
            "actual_lico_distance_before_brake_m",
            "selected_lico_distance_m",
            "lico_distance_error_m",
            "lico_duration_s",
            "brake_start_m",
            "fuel_used_l",
            "elapsed_time_s",
            "reference_method",
            "reference_laps",
            "reference_fuel_used_l",
            "reference_time_s",
            "observed_fuel_saved_l",
            "expected_fuel_saved_l",
            "fuel_prediction_error_l",
            "observed_time_lost_s",
            "expected_time_lost_s",
            "time_prediction_error_s",
            "cue_error_m",
            "trigger_status",
            "cue_distance_method",
            "distance_projection_age_s",
            "sampling_gap_after_cue_s",
            "sampling_gap_after_cue",
        )
        .sort(("zone_id", "lap_number"))
    )
    baseline_support = (
        passes.filter((pl.col("role") == "push") & ~pl.col("has_lico"))
        .group_by("zone_id")
        .agg(pl.len().alias("clean_push_reference_count"))
    )
    summary = summarize_zone_observations(observations, baseline_support)
    return observations, summary


def summarize_zone_observations(
    observations: pl.DataFrame, baseline_support: pl.DataFrame
) -> pl.DataFrame:
    return (
        observations.group_by("zone_id", "display_label")
        .agg(
            pl.len().alias("lico_lap_count"),
            pl.col("has_lico").mean().alias("lico_execution_rate"),
            pl.col("actual_lico_distance_before_brake_m")
            .mean()
            .alias("mean_actual_lico_distance_m"),
            pl.col("lico_distance_error_m").mean().alias("mean_lico_distance_error_m"),
            pl.col("lico_distance_error_m")
            .abs()
            .mean()
            .alias("mean_abs_lico_distance_error_m"),
            pl.col("observed_fuel_saved_l").mean().alias("mean_observed_fuel_saved_l"),
            pl.col("expected_fuel_saved_l").first().alias("expected_fuel_saved_l"),
            pl.col("fuel_prediction_error_l")
            .mean()
            .alias("mean_fuel_prediction_error_l"),
            pl.col("observed_time_lost_s").mean().alias("mean_observed_time_lost_s"),
            pl.col("expected_time_lost_s").first().alias("expected_time_lost_s"),
            pl.col("time_prediction_error_s")
            .mean()
            .alias("mean_time_prediction_error_s"),
            pl.col("cue_error_m").abs().max().alias("max_abs_cue_error_m"),
            pl.col("sampling_gap_after_cue")
            .sum()
            .alias("sampling_gaps_after_cue_count"),
            pl.col("sampling_gap_after_cue_s").max().alias("max_sampling_gap_s"),
        )
        .join(baseline_support, on="zone_id", how="left")
        .sort("zone_id")
    )


def apply_driver_review(
    lap_validation: pl.DataFrame,
    observations: pl.DataFrame,
    operator_metadata: dict[str, object],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    valid_laps = {int(value) for value in operator_metadata.get("valid_laps", [])}
    lap_reasons = {
        int(lap): str(reason)
        for lap, reason in operator_metadata.get(
            "excluded_laps_with_reasons", {}
        ).items()
    }
    reviewed_laps = lap_validation.with_columns(
        pl.col("lap_number").is_in(valid_laps).alias("driver_included"),
        pl.col("lap_number")
        .replace_strict(lap_reasons, default=None, return_dtype=pl.String)
        .alias("driver_exclusion_reason"),
    )
    zone_reviews = pl.DataFrame(
        [
            {
                "lap_number": int(row["lap_number"]),
                "zone_id": str(row["zone_id"]),
                "driver_exclusion_reason": str(row["reason"]),
            }
            for row in operator_metadata.get("zone_exclusions", [])
        ],
        schema={
            "lap_number": pl.Int64,
            "zone_id": pl.String,
            "driver_exclusion_reason": pl.String,
        },
    )
    reviewed_observations = observations.join(
        zone_reviews, on=("lap_number", "zone_id"), how="left"
    ).with_columns(
        pl.col("driver_exclusion_reason").is_null().alias("driver_included")
    )
    return reviewed_laps, reviewed_observations


def load_authoritative_duckdb_samples(
    duckdb_path: Path,
    *,
    schedule: pl.DataFrame,
    expected_car_class: str,
) -> tuple[pl.DataFrame, dict[str, str]]:
    with LmuTelemetryDatabase(duckdb_path) as telemetry:
        metadata = telemetry.metadata()
        if "Paul Ricard" not in metadata.get("TrackName", ""):
            raise ValueError("Authoritative DuckDB track is not Paul Ricard")
        if metadata.get("CarClass") != expected_car_class:
            raise ValueError("Authoritative DuckDB car class disagrees with session")
        scored_laps = {int(value) for value in schedule["lap_number"].to_list()}
        samples = build_lap_telemetry(telemetry, lap_numbers=scored_laps)
        available_laps = set(samples["lap_number"].unique().to_list())
        if available_laps != scored_laps:
            raise ValueError(
                "Authoritative DuckDB does not contain every scored lap: "
                f"{sorted(scored_laps ^ available_laps)}"
            )
        start_ts = telemetry.session_start_ts()
    normalized = samples.select(
        "lap_number",
        "lap_distance_m",
        "ts",
        (pl.col("ts") - start_ts).alias("elapsed_s"),
        "fuel_level_l",
        pl.col("ground_speed_kph").alias("speed_kph"),
        "throttle_pct",
        "brake_pct",
        pl.lit(None).cast(pl.Int64).alias("gear"),
    )
    return normalized, metadata


def analyze_session(
    session_dir: Path,
    *,
    pack_dir: Path = DEFAULT_PACK_DIR,
    output_dir: Path | None = None,
) -> dict[str, object]:
    for name in REQUIRED_SESSION_FILES:
        if not (session_dir / name).is_file():
            raise FileNotFoundError(f"Missing session file: {session_dir / name}")
    output = output_dir or session_dir / "validation"
    output.mkdir(parents=True, exist_ok=True)
    session_config = read_json(session_dir / "session_config.json")
    operator_metadata = read_json(session_dir / "run_metadata_template.json")
    session_pack_manifest = read_json(session_dir / "pack_manifest.json")
    schedule = pl.read_csv(session_dir / "lap_schedule.csv")
    telemetry = pl.read_csv(session_dir / "telemetry.csv")
    events = pl.read_csv(session_dir / "events.csv")
    plan_path = next(
        (
            path
            for path in (
                session_dir / "plan.csv",
                output / "plan_used.csv",
                pack_dir / "plan.csv",
            )
            if path.is_file()
        ),
        None,
    )
    if plan_path is None:
        raise FileNotFoundError(
            "No session-snapshot or matching pack plan is available"
        )
    plan = pl.read_csv(plan_path)
    if session_config["run_id"] != session_dir.name:
        raise ValueError("Session directory and run_id disagree")
    plan_sha256 = _sha256(plan_path)
    if plan_sha256.lower() != str(session_config["plan_sha256"]).lower():
        raise ValueError("Session plan hash disagrees with the selected plan snapshot")
    zone_snapshot_path = next(
        (
            path
            for path in (
                session_dir / "track_zones.json",
                output / "track_zones_used.json",
                ZONE_CONFIG,
            )
            if path.is_file()
        ),
        None,
    )
    if zone_snapshot_path is None:
        raise FileNotFoundError("No track-zone snapshot is available")
    zone_source_key = ZONE_CONFIG.relative_to(PROJECT_ROOT).as_posix()
    expected_zone_sha256 = session_pack_manifest["sources"].get(zone_source_key)
    if (
        expected_zone_sha256 is None
        or _sha256(zone_snapshot_path) != expected_zone_sha256
    ):
        raise ValueError("Track-zone snapshot disagrees with the session pack lineage")
    validate_event_coverage(events, schedule, plan)
    lap_validation = build_lap_validation(
        telemetry,
        schedule,
        predicted_fuel_saved_l=float(plan["expected_fuel_saved_l"].sum()),
        predicted_time_lost_s=float(plan["expected_time_lost_s"].sum()),
    )
    if lap_validation.height != int(session_config["scored_laps"]):
        raise ValueError("Scored lap count disagrees with session_config")
    if not lap_validation["complete_distance_coverage"].all():
        raise ValueError("At least one scored lap lacks complete distance coverage")
    observations, zone_summary = build_zone_validation(
        telemetry,
        schedule,
        events,
        plan,
        zone_config_path=zone_snapshot_path,
    )
    expected_observations = int(schedule["cue_enabled"].sum()) * plan.height
    detected_lico_execution_count = validate_observation_coverage(
        observations, expected_observations=expected_observations
    )

    authoritative_laps: pl.DataFrame | None = None
    authoritative_observations: pl.DataFrame | None = None
    authoritative_zone_summary: pl.DataFrame | None = None
    authoritative_metadata: dict[str, str] | None = None
    duckdb_path_value = str(operator_metadata.get("telemetry_duckdb") or "")
    duckdb_path = Path(duckdb_path_value) if duckdb_path_value else None
    if duckdb_path is not None:
        if not duckdb_path.is_file():
            raise FileNotFoundError(f"Linked authoritative DuckDB is missing: {duckdb_path}")
        duckdb_samples, authoritative_metadata = load_authoritative_duckdb_samples(
            duckdb_path,
            schedule=schedule,
            expected_car_class=str(session_config.get("car_class") or operator_metadata["car_class"]),
        )
        authoritative_laps = build_lap_validation(
            duckdb_samples,
            schedule,
            predicted_fuel_saved_l=float(plan["expected_fuel_saved_l"].sum()),
            predicted_time_lost_s=float(plan["expected_time_lost_s"].sum()),
        )
        authoritative_observations, unfiltered_authoritative_summary = (
            build_zone_validation(
                duckdb_samples,
                schedule,
                events,
                plan,
                zone_config_path=zone_snapshot_path,
                measure_sampling_gaps=False,
            )
        )
        validate_observation_coverage(
            authoritative_observations,
            expected_observations=expected_observations,
        )
        authoritative_laps, authoritative_observations = apply_driver_review(
            authoritative_laps, authoritative_observations, operator_metadata
        )
        authoritative_zone_summary = summarize_zone_observations(
            authoritative_observations.filter(pl.col("driver_included")),
            unfiltered_authoritative_summary.select(
                "zone_id", "clean_push_reference_count"
            ),
        )

    lico_laps = lap_validation.filter(pl.col("role") == "lico")
    enabled_events = events.filter(
        pl.col("cue_enabled")
        & pl.col("lap_number").is_in(schedule["lap_number"].to_list())
    )
    metadata_complete = (
        operator_metadata.get("status") != "template_not_collected"
        and bool(operator_metadata.get("car"))
        and bool(operator_metadata.get("driver"))
        and bool(operator_metadata.get("setup"))
        and operator_metadata.get("starting_fuel_l") is not None
        and bool(operator_metadata.get("weather_and_track_conditions"))
    )
    lap_quality = operator_metadata.get("lap_quality_debrief") or {}
    valid_laps = operator_metadata.get("valid_laps") or []
    lap_quality_resolved = bool(valid_laps) and (
        bool(lap_quality.get("all_laps_clean"))
        or bool(lap_quality.get("affected_laps_known"))
    )
    audio_debrief = operator_metadata.get("audio_cue_debrief") or {}
    audible_cues_heard = audio_debrief.get("heard")
    audio_debrief_complete = (
        audible_cues_heard == enabled_events.height
        and audio_debrief.get("missed") == 0
    )
    telemetry_duckdb_linked = duckdb_path is not None
    authoritative_duckdb_analyzed = authoritative_laps is not None
    audible_gap_count = int(observations["sampling_gap_after_cue"].sum())
    refit_blockers = build_refit_blockers(
        metadata_complete=metadata_complete,
        lap_quality_resolved=lap_quality_resolved,
        telemetry_duckdb_linked=telemetry_duckdb_linked,
        audible_gap_count=audible_gap_count,
    )
    evaluation_status = "provisional_csv_only_awaiting_driver_metadata"
    if authoritative_duckdb_analyzed and lap_quality_resolved:
        evaluation_status = (
            "authoritative_validation_complete"
            if audio_debrief_complete
            else "authoritative_performance_scored_audio_debrief_pending"
        )
        refit_blockers = [
            "prospective confirmation is retained as held-out validation and is not authorized for refit"
        ]
    if audio_debrief_complete and not lap_quality_resolved:
        evaluation_status = (
            "operational_cue_validation_passed_performance_unscorable"
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": session_config["run_id"],
        "evaluation_status": evaluation_status,
        "refit_authorized": False,
        "refit_blockers": refit_blockers,
        "plan_sha256": plan_sha256,
        "scored_laps": lap_validation.height,
        "push_laps": lap_validation.filter(pl.col("role") == "push").height,
        "lico_laps": lico_laps.height,
        "zone_count": plan.height,
        "audible_cue_count": enabled_events.height,
        "audible_cues_heard_by_driver": audible_cues_heard,
        "audio_debrief_complete": audio_debrief_complete,
        "all_audible_cues_on_time": bool(
            enabled_events["trigger_status"].eq("fired_on_time").all()
        ),
        "max_abs_audible_cue_error_m": float(enabled_events["cue_error_m"].abs().max()),
        "detected_lico_execution_count": detected_lico_execution_count,
        "mean_fuel_saved_vs_push_l": float(
            lico_laps["fuel_saved_vs_push_reference_l"].mean()
        ),
        "mean_time_lost_vs_push_s": float(
            lico_laps["time_lost_vs_push_reference_s"].mean()
        ),
        "fuel_saved_vs_push_std_l": float(
            lico_laps["fuel_saved_vs_push_reference_l"].std()
        ),
        "time_lost_vs_push_std_s": float(
            lico_laps["time_lost_vs_push_reference_s"].std()
        ),
        "sum_zone_mean_observed_fuel_saved_l": float(
            zone_summary["mean_observed_fuel_saved_l"].sum()
        ),
        "sum_zone_mean_observed_time_lost_s": float(
            zone_summary["mean_observed_time_lost_s"].sum()
        ),
        "whole_lap_reference_method": "bracketing_linear_interpolation",
        "zone_reference_methods": sorted(
            observations["reference_method"].unique().to_list()
        ),
        "plan_predicted_fuel_saved_l": float(plan["expected_fuel_saved_l"].sum()),
        "plan_predicted_time_lost_s": float(plan["expected_time_lost_s"].sum()),
        "operator_metadata_complete": metadata_complete,
        "lap_quality_resolved": lap_quality_resolved,
        "telemetry_duckdb_linked": telemetry_duckdb_linked,
        "authoritative_duckdb_analyzed": authoritative_duckdb_analyzed,
        "sampling_gap_threshold_s": SAMPLING_GAP_THRESHOLD_S,
        "audible_cues_with_sampling_gap": audible_gap_count,
        "max_sampling_gap_after_cue_s": float(
            observations["sampling_gap_after_cue_s"].max()
        ),
        "source_files": {
            name: _sha256(session_dir / name) for name in REQUIRED_SESSION_FILES
        },
        "analysis_files": {
            Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix(): _sha256(
                Path(__file__)
            ),
            "src/licor/live/runtime.py": _sha256(
                PROJECT_ROOT / "src/licor/live/runtime.py"
            ),
            "src/licor/analysis/zone_pass.py": _sha256(
                PROJECT_ROOT / "src/licor/analysis/zone_pass.py"
            ),
            "track_zones_used.json": _sha256(zone_snapshot_path),
        },
    }
    if authoritative_duckdb_analyzed:
        assert authoritative_laps is not None
        assert authoritative_observations is not None
        assert authoritative_zone_summary is not None
        assert authoritative_metadata is not None
        assert duckdb_path is not None
        clean_authoritative_lico = authoritative_laps.filter(
            (pl.col("role") == "lico") & pl.col("driver_included")
        )
        manifest["authoritative_duckdb"] = {
            "path": str(duckdb_path),
            "sha256": _sha256(duckdb_path),
            "track_name": authoritative_metadata.get("TrackName"),
            "track_layout": authoritative_metadata.get("TrackLayout"),
            "car_name": authoritative_metadata.get("CarName"),
            "car_class": authoritative_metadata.get("CarClass"),
            "weather_conditions": authoritative_metadata.get("WeatherConditions"),
            "clean_lico_lap_count": clean_authoritative_lico.height,
            "included_zone_observation_count": authoritative_observations.filter(
                pl.col("driver_included")
            ).height,
            "excluded_zone_observation_count": authoritative_observations.filter(
                ~pl.col("driver_included")
            ).height,
            "mean_fuel_saved_vs_push_l": float(
                clean_authoritative_lico["fuel_saved_vs_push_reference_l"].mean()
            ),
            "mean_time_lost_vs_push_s": float(
                clean_authoritative_lico["time_lost_vs_push_reference_s"].mean()
            ),
            "detected_lico_execution_count_included": int(
                authoritative_observations.filter(pl.col("driver_included"))[
                    "has_lico"
                ].sum()
            ),
        }
    manifest["whole_lap_minus_zone_sum_fuel_l"] = float(
        manifest["mean_fuel_saved_vs_push_l"]
        - manifest["sum_zone_mean_observed_fuel_saved_l"]
    )
    manifest["whole_lap_minus_zone_sum_time_s"] = float(
        manifest["mean_time_lost_vs_push_s"]
        - manifest["sum_zone_mean_observed_time_lost_s"]
    )
    lap_validation.write_csv(output / "lap_validation.csv")
    observations.write_csv(output / "zone_execution_observations.csv")
    zone_summary.write_csv(output / "zone_execution_summary.csv")
    if authoritative_duckdb_analyzed:
        assert authoritative_laps is not None
        assert authoritative_observations is not None
        assert authoritative_zone_summary is not None
        authoritative_laps.write_csv(output / "duckdb_lap_validation.csv")
        authoritative_observations.write_csv(
            output / "duckdb_zone_execution_observations.csv"
        )
        authoritative_zone_summary.write_csv(
            output / "duckdb_zone_execution_summary.csv"
        )
    plan.write_csv(output / "plan_used.csv")
    (output / "track_zones_used.json").write_bytes(zone_snapshot_path.read_bytes())
    report_zones = (
        authoritative_zone_summary
        if authoritative_zone_summary is not None
        else zone_summary
    )
    (output / "validation_report.md").write_text(
        _validation_report(manifest, report_zones), encoding="utf-8"
    )
    manifest["artifacts"] = {
        name: _sha256(output / name)
        for name in (
            "lap_validation.csv",
            "zone_execution_observations.csv",
            "zone_execution_summary.csv",
            "plan_used.csv",
            "track_zones_used.json",
            "validation_report.md",
            "duckdb_lap_validation.csv",
            "duckdb_zone_execution_observations.csv",
            "duckdb_zone_execution_summary.csv",
        )
        if (output / name).is_file()
    }
    (output / "validation_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _validation_report(manifest: dict[str, object], zones: pl.DataFrame) -> str:
    zone_heading = (
        "## Authoritative zone observations"
        if manifest.get("authoritative_duckdb_analyzed")
        else "## Zone observations"
    )
    rows = [
        "# Paul Ricard six-zone live validation",
        "",
        f"Run: `{manifest['run_id']}`",
        "",
        "## Automated result",
        "",
        f"- {manifest['scored_laps']} scored laps: {manifest['push_laps']} push and {manifest['lico_laps']} LiCo.",
        f"- {manifest['audible_cue_count']} audible cues; all on time: {manifest['all_audible_cues_on_time']}.",
        f"- Audible cues confirmed heard by the driver: {manifest['audible_cues_heard_by_driver']}.",
        f"- Maximum audible cue error: {manifest['max_abs_audible_cue_error_m']:.3f} m.",
        f"- Mean whole-lap fuel saved versus bracketing push interpolation: {manifest['mean_fuel_saved_vs_push_l']:.4f} ± {manifest['fuel_saved_vs_push_std_l']:.4f} L.",
        f"- Mean whole-lap time lost versus bracketing push interpolation: {manifest['mean_time_lost_vs_push_s']:.4f} ± {manifest['time_lost_vs_push_std_s']:.4f} s.",
        f"- Zone-sum residual: {manifest['whole_lap_minus_zone_sum_fuel_l']:+.4f} L and {manifest['whole_lap_minus_zone_sum_time_s']:+.4f} s.",
        "",
        zone_heading,
        "",
        "| Zone | Actual LiCo m | Planned m | Fuel saved L | Predicted L | Time lost s | Predicted s | Clean push refs |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not manifest["lap_quality_resolved"]:
        rows.insert(
            6,
            "- Fuel/time values below are retained for audit only; the unresolved dirty laps make them unscorable.",
        )
    for row in zones.iter_rows(named=True):
        planned_m = float(row["mean_actual_lico_distance_m"]) - float(
            row["mean_lico_distance_error_m"]
        )
        rows.append(
            f"| {row['display_label']} | {row['mean_actual_lico_distance_m']:.2f} | "
            f"{planned_m:.2f} | {row['mean_observed_fuel_saved_l']:.4f} | "
            f"{row['expected_fuel_saved_l']:.4f} | {row['mean_observed_time_lost_s']:.4f} | "
            f"{row['expected_time_lost_s']:.4f} | {row['clean_push_reference_count']} |"
        )
    blockers = "; ".join(str(value) for value in manifest["refit_blockers"])
    authoritative = manifest.get("authoritative_duckdb")
    if isinstance(authoritative, dict):
        rows.extend(
            [
                "",
                "## Authoritative DuckDB result",
                "",
                f"- Clean LICO laps used for whole-lap scoring: {authoritative['clean_lico_lap_count']}.",
                f"- Driver-included zone observations: {authoritative['included_zone_observation_count']}; excluded: {authoritative['excluded_zone_observation_count']}.",
                f"- Fuel saved versus bracketing push laps: {authoritative['mean_fuel_saved_vs_push_l']:.4f} L.",
                f"- Time lost versus bracketing push laps: {authoritative['mean_time_lost_vs_push_s']:.4f} s.",
            ]
        )
    rows.extend(["", "## Decision gate", ""])
    if manifest["audio_debrief_complete"]:
        audio_verdict = "the driver confirmed hearing all of them"
    else:
        audio_verdict = "the driver-heard count is still pending"
    decision = f"All expected software cues were on time; {audio_verdict}. "
    if isinstance(authoritative, dict):
        decision += (
            "The authoritative DuckDB result respects the recorded driver "
            "exclusions. "
        )
    else:
        decision += "Fuel/time results remain CSV-only. "
    rows.append(decision + f"Refit remains blocked because {blockers}.")
    rows.append("")
    return "\n".join(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    session_dir = args.session_dir or latest_session_dir()
    manifest = analyze_session(
        session_dir.resolve(),
        pack_dir=args.pack_dir.resolve(),
        output_dir=args.output_dir.resolve() if args.output_dir else None,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
