"""Historical v1 helpers; use analyze_bahrain_transfer_v2.py for corrected scores."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from licor.analysis.processed_artifacts import build_labeled_zone_passes
from licor.analysis.track_zones import load_track_zone_table
from licor.analysis.zone_pass import ZonePassConfig
from licor.ingestion import LmuTelemetryDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "bahrain_lico_20260911_224825"
SESSION_DIR = (
    PROJECT_ROOT
    / "data/processed/experimental/bahrain_lmp2_transfer_2026_09/sessions"
    / RUN_ID
)
OUTPUT_DIR = SESSION_DIR / "analysis_v1"
DATASET_FILE = Path("config/datasets/bahrain_lmp2_circuit_c_2026-09.json")
ZONE_FILE = Path("config/track_zones/bahrain_lmp2_zones.draft.json")
REVIEW_FILE = Path("config/driver_reviews/bahrain_lmp2_push_review_2026-09-11.json")
RAW_FILE = Path("data/Bahrain International Circuit_P_2026-09-12T02_48_51Z.duckdb")
TRACK_LENGTH_M = 5385.0
SELECTED_ZONES = (
    "bhr_t01_t03",
    "bhr_t04",
    "bhr_t08",
    "bhr_t10",
    "bhr_t11",
    "bhr_t14_t15",
)
# Diagnostics extend each selected action far enough to capture its speed
# recovery, while stopping before the next planned action can contribute.
RECOVERY_END_M = {
    "bhr_t01_t03": 1150.0,
    "bhr_t04": 1680.0,
    "bhr_t08": 2360.0,
    "bhr_t10": 3080.0,
    "bhr_t11": 3820.0,
    "bhr_t14_t15": 5350.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_analysis(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule = _load_schedule()
    push_laps = schedule.filter(pl.col("role") == "push")["lap_number"].to_list()
    lico_laps = schedule.filter(pl.col("role") == "lico")["lap_number"].to_list()
    live = pl.read_csv(SESSION_DIR / "telemetry.csv")
    events = pl.read_csv(SESSION_DIR / "events.csv")
    plan = pl.read_csv(SESSION_DIR / "plan.csv")
    predictions = pl.read_csv(SESSION_DIR / "predictions.csv")
    zones = load_track_zone_table(PROJECT_ROOT / ZONE_FILE)

    live_passes = _build_live_fixed_distance_passes(live, schedule, zones.zones)
    baselines = _build_baselines(live_passes, push_laps)
    scored = _score_live_passes(live_passes, baselines, lico_laps)
    native_passes = _build_native_zone_passes()
    history = _build_historical_push_sensitivity(native_passes, push_laps)
    execution = _build_execution_summary(native_passes, plan, lico_laps)
    zone_summary = _build_zone_summary(
        scored, execution, history, plan, predictions, push_laps, lico_laps
    )
    lap_summary = _build_lap_summary(live, schedule, plan)
    quality = _build_quality_summary(live, events, schedule)

    _write_csv(live_passes, output_dir / "fixed_distance_passes.csv")
    _write_csv(scored, output_dir / "lico_pass_scores.csv")
    _write_csv(native_passes, output_dir / "native_zone_passes.csv")
    _write_csv(zone_summary, output_dir / "zone_verdicts.csv")
    _write_csv(lap_summary, output_dir / "lap_summary.csv")
    (output_dir / "data_quality.json").write_text(
        json.dumps(quality, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    sources = [
        PROJECT_ROOT / RAW_FILE,
        PROJECT_ROOT / DATASET_FILE,
        PROJECT_ROOT / ZONE_FILE,
        PROJECT_ROOT / REVIEW_FILE,
        SESSION_DIR / "telemetry.csv",
        SESSION_DIR / "events.csv",
        SESSION_DIR / "events_accuracy.csv",
        SESSION_DIR / "lap_schedule.csv",
        SESSION_DIR / "plan.csv",
        SESSION_DIR / "predictions.csv",
        Path(__file__),
    ]
    artifacts = [
        output_dir / "fixed_distance_passes.csv",
        output_dir / "lico_pass_scores.csv",
        output_dir / "native_zone_passes.csv",
        output_dir / "zone_verdicts.csv",
        output_dir / "lap_summary.csv",
        output_dir / "data_quality.json",
    ]
    manifest = {
        "schema_version": 1,
        "analysis_id": "bahrain_zero_lico_shot_validation_v1",
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_baseline": "median of same-run scheduled push laps 23, 26 and 29",
        "frozen_scoring": "manual zone end from the pre-run track-zone file",
        "recovery_diagnostic": (
            "fixed-distance extension to the next non-overlapping action boundary; "
            "reported separately and not used to rewrite the frozen prediction"
        ),
        "sources": {str(path): sha256_file(path) for path in sources},
        "artifacts": {path.name: sha256_file(path) for path in artifacts},
        "summary": {
            "scored_push_laps": push_laps,
            "scored_lico_laps": lico_laps,
            "enabled_cues": quality["enabled_cues"],
            "all_enabled_cues_on_time": quality["all_enabled_cues_on_time"],
            "observed_lap_fuel_saved_l": float(
                lap_summary["observed_median_fuel_saved_l"][0]
            ),
            "observed_lap_time_lost_s": float(
                lap_summary["observed_official_median_time_lost_s"][0]
            ),
            "predicted_lap_fuel_saved_l": float(
                lap_summary["predicted_fuel_saved_l"][0]
            ),
            "predicted_lap_time_lost_s": float(lap_summary["predicted_time_lost_s"][0]),
        },
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def _load_schedule() -> pl.DataFrame:
    schedule = pl.read_csv(SESSION_DIR / "lap_schedule.csv").with_columns(
        pl.col("lap_number").cast(pl.Int64), pl.col("role").cast(pl.String)
    )
    expected = ["push", "lico", "lico", "push", "lico", "lico", "push"]
    if schedule["role"].to_list() != expected:
        raise ValueError("unexpected Bahrain validation lap schedule")
    return schedule


def _trim_live_lap(lap: pl.DataFrame) -> pl.DataFrame:
    ordered = lap.sort("elapsed_s")
    if ordered.is_empty():
        return ordered
    rows = ordered["lap_distance_m"].to_list()
    if rows[0] > TRACK_LENGTH_M / 2:
        reset = next((index for index, value in enumerate(rows) if value < 100.0), None)
        if reset is None:
            raise ValueError("live lap has no start/finish distance reset")
        ordered = ordered.slice(reset)
    return ordered


def interpolate_at_distance(lap: pl.DataFrame, distance_m: float, column: str) -> float:
    ordered = _trim_live_lap(lap)
    distances = ordered["lap_distance_m"].to_list()
    crossing = next(
        (index for index, value in enumerate(distances) if value >= distance_m), None
    )
    if crossing is None or crossing == 0:
        raise ValueError(f"lap does not bracket {distance_m} m")
    left = ordered.row(crossing - 1, named=True)
    right = ordered.row(crossing, named=True)
    span = float(right["lap_distance_m"]) - float(left["lap_distance_m"])
    weight = 0.0 if span == 0.0 else (distance_m - float(left["lap_distance_m"])) / span
    return float(left[column]) + weight * (float(right[column]) - float(left[column]))


def _build_live_fixed_distance_passes(
    live: pl.DataFrame, schedule: pl.DataFrame, zones: list[Any]
) -> pl.DataFrame:
    roles = dict(
        zip(schedule["lap_number"].to_list(), schedule["role"].to_list(), strict=True)
    )
    rows = []
    for lap_number, role in roles.items():
        lap = live.filter(pl.col("lap_number") == lap_number)
        for zone in zones:
            start_m = float(zone.start_distance_m)
            frozen_end_m = float(zone.end_distance_m)
            recovery_end_m = float(RECOVERY_END_M.get(zone.zone_id, frozen_end_m))
            start_time = interpolate_at_distance(lap, start_m, "elapsed_s")
            start_fuel = interpolate_at_distance(lap, start_m, "fuel_level_l")
            frozen_time = interpolate_at_distance(lap, frozen_end_m, "elapsed_s")
            frozen_fuel = interpolate_at_distance(lap, frozen_end_m, "fuel_level_l")
            recovery_time = interpolate_at_distance(lap, recovery_end_m, "elapsed_s")
            recovery_fuel = interpolate_at_distance(lap, recovery_end_m, "fuel_level_l")
            rows.append(
                {
                    "run_id": RUN_ID,
                    "lap_number": lap_number,
                    "role": role,
                    "zone_id": zone.zone_id,
                    "display_label": zone.display_label,
                    "is_selected_for_lico": zone.zone_id in SELECTED_ZONES,
                    "start_distance_m": start_m,
                    "frozen_end_distance_m": frozen_end_m,
                    "recovery_end_distance_m": recovery_end_m,
                    "frozen_elapsed_time_s": frozen_time - start_time,
                    "frozen_fuel_used_l": start_fuel - frozen_fuel,
                    "recovery_elapsed_time_s": recovery_time - start_time,
                    "recovery_fuel_used_l": start_fuel - recovery_fuel,
                }
            )
    return pl.DataFrame(rows).sort(["lap_number", "start_distance_m"])


def _build_baselines(passes: pl.DataFrame, push_laps: list[int]) -> pl.DataFrame:
    return (
        passes.filter(pl.col("lap_number").is_in(push_laps))
        .group_by("zone_id")
        .agg(
            pl.len().alias("same_run_push_support"),
            pl.col("frozen_elapsed_time_s").median().alias("push_frozen_time_s"),
            pl.col("frozen_fuel_used_l").median().alias("push_frozen_fuel_l"),
            pl.col("recovery_elapsed_time_s").median().alias("push_recovery_time_s"),
            pl.col("recovery_fuel_used_l").median().alias("push_recovery_fuel_l"),
        )
    )


def _score_live_passes(
    passes: pl.DataFrame, baselines: pl.DataFrame, lico_laps: list[int]
) -> pl.DataFrame:
    return (
        passes.filter(pl.col("lap_number").is_in(lico_laps))
        .join(baselines, on="zone_id", how="left")
        .with_columns(
            (pl.col("frozen_elapsed_time_s") - pl.col("push_frozen_time_s")).alias(
                "frozen_time_lost_s"
            ),
            (pl.col("push_frozen_fuel_l") - pl.col("frozen_fuel_used_l")).alias(
                "frozen_fuel_saved_l"
            ),
            (pl.col("recovery_elapsed_time_s") - pl.col("push_recovery_time_s")).alias(
                "recovery_time_lost_s"
            ),
            (pl.col("push_recovery_fuel_l") - pl.col("recovery_fuel_used_l")).alias(
                "recovery_fuel_saved_l"
            ),
        )
        .sort(["lap_number", "start_distance_m"])
    )


def _build_native_zone_passes() -> pl.DataFrame:
    return build_labeled_zone_passes(
        dataset_label_file=PROJECT_ROOT / DATASET_FILE,
        track_zone_file=PROJECT_ROOT / ZONE_FILE,
        project_root=PROJECT_ROOT,
        driver_review_file=PROJECT_ROOT / REVIEW_FILE,
        config=ZonePassConfig(
            require_driver_reviewed=False,
            optimization_roles=("candidate", "validation_only"),
        ),
    )


def _build_historical_push_sensitivity(
    native: pl.DataFrame, current_push_laps: list[int]
) -> pl.DataFrame:
    previous = native.filter(pl.col("run_id") == "bahrain_push_20260911_212732")
    exclusions = {
        "bhr_t04": {19},
        "bhr_t05_t07": {19},
        "bhr_t14_t15": {18, 20},
    }
    previous_rows = []
    for zone_id in previous["zone_id"].unique().to_list():
        zone = previous.filter(pl.col("zone_id") == zone_id)
        if zone_id in exclusions:
            zone = zone.filter(~pl.col("lap_number").is_in(exclusions[zone_id]))
        previous_rows.append(
            {
                "zone_id": zone_id,
                "previous_push_outcome_support": zone.height,
                "previous_push_time_s": float(zone["elapsed_time_s"].median()),
                "previous_push_fuel_l": float(zone["fuel_used_l"].median()),
            }
        )
    current = (
        native.filter(
            (pl.col("run_id") == RUN_ID) & pl.col("lap_number").is_in(current_push_laps)
        )
        .group_by("zone_id")
        .agg(
            pl.col("elapsed_time_s").median().alias("current_push_native_time_s"),
            pl.col("fuel_used_l").median().alias("current_push_native_fuel_l"),
        )
    )
    return pl.DataFrame(previous_rows).join(current, on="zone_id", how="left")


def _build_execution_summary(
    native: pl.DataFrame, plan: pl.DataFrame, lico_laps: list[int]
) -> pl.DataFrame:
    executed = native.filter(
        (pl.col("run_id") == RUN_ID)
        & pl.col("lap_number").is_in(lico_laps)
        & pl.col("zone_id").is_in(SELECTED_ZONES)
    )
    return (
        executed.group_by("zone_id")
        .agg(
            pl.col("lico_start_m").median().alias("median_executed_lift_start_m"),
            pl.col("lico_distance_m").median().alias("median_executed_lico_distance_m"),
            pl.col("lico_distance_m").min().alias("minimum_executed_lico_distance_m"),
            pl.col("lico_distance_m").max().alias("maximum_executed_lico_distance_m"),
            pl.col("has_lico").sum().alias("detected_lico_passes"),
        )
        .join(
            plan.select(
                "zone_id",
                "selected_lico_distance_m",
                "planned_lift_start_m",
                "expected_fuel_saved_l",
                "expected_time_lost_s",
            ),
            on="zone_id",
            how="left",
        )
        .with_columns(
            (
                pl.col("median_executed_lico_distance_m")
                - pl.col("selected_lico_distance_m")
            ).alias("median_execution_distance_error_m"),
            (
                pl.col("median_executed_lift_start_m") - pl.col("planned_lift_start_m")
            ).alias("median_lift_start_error_m"),
        )
    )


def _build_zone_summary(
    scored: pl.DataFrame,
    execution: pl.DataFrame,
    history: pl.DataFrame,
    plan: pl.DataFrame,
    predictions: pl.DataFrame,
    push_laps: list[int],
    lico_laps: list[int],
) -> pl.DataFrame:
    del plan, push_laps
    summary = (
        scored.group_by("zone_id")
        .agg(
            pl.first("display_label").alias("display_label"),
            pl.first("is_selected_for_lico").alias("is_selected_for_lico"),
            pl.first("frozen_end_distance_m").alias("frozen_end_distance_m"),
            pl.first("recovery_end_distance_m").alias("recovery_end_distance_m"),
            pl.len().alias("lico_pass_support"),
            pl.col("frozen_fuel_saved_l").median().alias("frozen_fuel_saved_l"),
            pl.col("frozen_time_lost_s").median().alias("frozen_time_lost_s"),
            pl.col("recovery_fuel_saved_l").median().alias("recovery_fuel_saved_l"),
            pl.col("recovery_time_lost_s").median().alias("recovery_time_lost_s"),
            pl.col("recovery_time_lost_s").min().alias("recovery_time_lost_min_s"),
            pl.col("recovery_time_lost_s").max().alias("recovery_time_lost_max_s"),
        )
        .join(history, on="zone_id", how="left")
        .join(execution, on="zone_id", how="left")
        .join(
            predictions.select(
                "zone_id", "predicted_fuel_saved_l", "predicted_time_lost_s"
            ),
            on="zone_id",
            how="left",
        )
        .with_columns(
            pl.when(pl.col("recovery_time_lost_s") > 0.02)
            .then(pl.col("recovery_fuel_saved_l") / pl.col("recovery_time_lost_s"))
            .otherwise(None)
            .alias("recovery_fuel_saved_per_second_lps"),
            (pl.col("recovery_fuel_saved_l") - pl.col("predicted_fuel_saved_l")).alias(
                "fuel_prediction_error_l"
            ),
            (pl.col("recovery_time_lost_s") - pl.col("predicted_time_lost_s")).alias(
                "time_prediction_error_s"
            ),
        )
    )
    return summary.with_columns(
        pl.when(pl.col("zone_id") == "bhr_t10")
        .then(pl.lit("deprioritize_or_retest_very_light"))
        .when(pl.col("zone_id").is_in(["bhr_t05_t07", "bhr_t13"]))
        .then(pl.lit("keep_silent_validation_only"))
        .when(pl.col("is_selected_for_lico"))
        .then(pl.lit("retain_for_next_model_iteration"))
        .otherwise(pl.lit("diagnostic_only"))
        .alias("verdict"),
        pl.lit(len(lico_laps)).alias("planned_lico_passes"),
    ).sort("zone_id")


def _build_lap_summary(
    live: pl.DataFrame, schedule: pl.DataFrame, plan: pl.DataFrame
) -> pl.DataFrame:
    intervals = {}
    with LmuTelemetryDatabase(PROJECT_ROOT / RAW_FILE) as telemetry:
        intervals = {
            interval.lap_number: interval.duration_s
            for interval in telemetry.lap_intervals()
        }
    rows = []
    for row in schedule.iter_rows(named=True):
        lap_number = int(row["lap_number"])
        lap = live.filter(pl.col("lap_number") == lap_number)
        rows.append(
            {
                "lap_number": lap_number,
                "role": row["role"],
                "official_lap_time_s": intervals[lap_number],
                "fixed_100_5350_time_s": interpolate_at_distance(
                    lap, 5350.0, "elapsed_s"
                )
                - interpolate_at_distance(lap, 100.0, "elapsed_s"),
                "fixed_100_5350_fuel_used_l": interpolate_at_distance(
                    lap, 100.0, "fuel_level_l"
                )
                - interpolate_at_distance(lap, 5350.0, "fuel_level_l"),
            }
        )
    frame = pl.DataFrame(rows)
    push = frame.filter(pl.col("role") == "push")
    lico = frame.filter(pl.col("role") == "lico")
    summary = {
        "observed_official_median_time_lost_s": float(
            lico["official_lap_time_s"].median() - push["official_lap_time_s"].median()
        ),
        "observed_fixed_median_time_lost_s": float(
            lico["fixed_100_5350_time_s"].median()
            - push["fixed_100_5350_time_s"].median()
        ),
        "observed_median_fuel_saved_l": float(
            push["fixed_100_5350_fuel_used_l"].median()
            - lico["fixed_100_5350_fuel_used_l"].median()
        ),
        "predicted_fuel_saved_l": float(plan["expected_fuel_saved_l"].sum()),
        "predicted_time_lost_s": float(plan["expected_time_lost_s"].sum()),
    }
    return frame.with_columns(
        *[pl.lit(value).alias(column) for column, value in summary.items()]
    )


def _build_quality_summary(
    live: pl.DataFrame, events: pl.DataFrame, schedule: pl.DataFrame
) -> dict[str, Any]:
    enabled = events.filter(pl.col("cue_enabled"))
    lap_quality = (
        live.filter(pl.col("lap_number").is_in(schedule["lap_number"].to_list()))
        .group_by("lap_number")
        .agg(
            pl.len().alias("sample_count"),
            pl.col("lap_distance_m").min().alias("minimum_distance_m"),
            pl.col("lap_distance_m").max().alias("maximum_distance_m"),
        )
        .sort("lap_number")
    )
    return {
        "run_id": RUN_ID,
        "raw_sha256": sha256_file(PROJECT_ROOT / RAW_FILE),
        "scheduled_laps": schedule["lap_number"].to_list(),
        "live_rows": live.height,
        "live_null_cells": int(
            sum(live[column].null_count() for column in live.columns)
        ),
        "enabled_cues": enabled.height,
        "all_enabled_cues_on_time": bool(
            enabled.filter(pl.col("trigger_status") != "fired_on_time").is_empty()
        ),
        "maximum_absolute_cue_error_m": float(enabled["cue_error_m"].abs().max()),
        "lap_coverage": lap_quality.to_dicts(),
        "native_pit_transitions_on_scored_laps": 0,
        "native_speed_limiter_transitions_on_scored_laps": 0,
        "native_impact_note": (
            "Boolean LastImpactMagnitude toggled near 750 m on lap29. Driver "
            "reported no notable error; fastest lap retained with an audit tag."
        ),
    }


def _write_csv(frame: pl.DataFrame, path: Path) -> None:
    serializable = frame.with_columns(
        [
            pl.col(column)
            .list.eval(pl.element().cast(pl.String))
            .list.join("|")
            .alias(column)
            for column, dtype in frame.schema.items()
            if isinstance(dtype, pl.List)
        ]
    )
    serializable.write_csv(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.error(
        "V1 local outcomes are superseded due to held-distance interpolation. "
        "Run scripts/analyze_bahrain_transfer_v2.py --output-dir <fresh-directory>. "
        "Preserve existing analysis_v1 artifacts as historical audit evidence."
    )


if __name__ == "__main__":
    raise SystemExit(main())
