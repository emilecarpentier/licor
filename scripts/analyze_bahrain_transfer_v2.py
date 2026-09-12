"""Correct the Bahrain prospective score and audit upstream action headroom."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import polars as pl

from licor.analysis.experimental_zone_dynamics import (
    build_labeled_experimental_lap_samples,
)
from licor.analysis.cross_circuit_ml import BrakingEventConfig, _acceleration_before_ts
from licor.analysis.fixed_distance import (
    NativeDistanceTrace,
    crossing_time,
    distance_anchors,
)
from licor.ingestion import LmuTelemetryDatabase

import analyze_bahrain_lico_validation as previous


ROOT = previous.PROJECT_ROOT
SESSION = previous.SESSION_DIR
OUTPUT = SESSION / "analysis_v2_final"
HEAVY_ZONES = ("bhr_t01_t03", "bhr_t04", "bhr_t11", "bhr_t14_t15")


def build_analysis(output: Path = OUTPUT) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite analysis: {output}")
    frozen = json.loads((SESSION / "track_zones.json").read_text(encoding="utf-8"))
    manifest = json.loads((SESSION / "pack_manifest.json").read_text(encoding="utf-8"))
    frozen_files = [
        "plan.csv",
        "predictions.csv",
        "track_zones.json",
        "plan_manifest.json",
    ]
    for name in frozen_files:
        if previous.sha256_file(SESSION / name) != manifest["artifacts"][name]:
            raise ValueError(f"frozen artifact mismatch: {name}")
    schedule = pl.read_csv(SESSION / "lap_schedule.csv")
    predictions = pl.read_csv(SESSION / "predictions.csv")
    selected = set(pl.read_csv(SESSION / "plan.csv")["zone_id"].to_list())
    live = pl.read_csv(SESSION / "telemetry.csv")
    rows, lap_rows = [], []
    with LmuTelemetryDatabase(ROOT / previous.RAW_FILE) as db:
        trace = NativeDistanceTrace.from_database(db)
        for scheduled in schedule.iter_rows(named=True):
            number = int(scheduled["lap_number"])
            live_lap = live.filter(pl.col("lap_number") == number)
            live_anchors = distance_anchors(live_lap, "elapsed_s")
            for zone in frozen["zones"]:
                for window in ("frozen", "recovery_diagnostic"):
                    start = float(zone["start_distance_m"])
                    end = float(zone["end_distance_m"])
                    if window == "recovery_diagnostic":
                        end = previous.RECOVERY_END_M.get(zone["zone_id"], end)
                    metrics = trace.outcome(number, start, end)
                    live_elapsed = crossing_time(
                        live_anchors, end, "elapsed_s"
                    ) - crossing_time(live_anchors, start, "elapsed_s")
                    rows.append(
                        {
                            "run_id": previous.RUN_ID,
                            "lap_number": number,
                            "role": scheduled["role"],
                            "zone_id": zone["zone_id"],
                            "display_label": zone["display_label"],
                            "window": window,
                            "is_selected_for_lico": zone["zone_id"] in selected,
                            "start_m": start,
                            "end_m": end,
                            **metrics,
                            "corrected_live_elapsed_time_s": live_elapsed,
                        }
                    )
            lap_metrics = trace.outcome(number, 100.0, 5350.0)
            lap_rows.append(
                {
                    "lap_number": number,
                    "role": scheduled["role"],
                    "official_time_s": trace.intervals[number].duration_s,
                    **lap_metrics,
                }
            )
    passes = pl.DataFrame(rows)
    push = (
        passes.filter(pl.col("role") == "push")
        .group_by("zone_id", "window")
        .agg(
            pl.col("elapsed_time_s").median().alias("push_time_s"),
            pl.col("fuel_used_l").median().alias("push_fuel_l"),
            pl.col("corrected_live_elapsed_time_s").median().alias("live_push_time_s"),
        )
    )
    scores = (
        passes.filter(pl.col("role") == "lico")
        .join(push, on=["zone_id", "window"])
        .with_columns(
            (pl.col("elapsed_time_s") - pl.col("push_time_s")).alias("time_lost_s"),
            (pl.col("push_fuel_l") - pl.col("fuel_used_l")).alias("fuel_saved_l"),
            (
                pl.col("corrected_live_elapsed_time_s") - pl.col("live_push_time_s")
            ).alias("live_time_lost_s"),
        )
    )
    summary = (
        scores.group_by("zone_id", "window")
        .agg(
            pl.first("display_label"),
            pl.first("is_selected_for_lico"),
            pl.first("start_m"),
            pl.first("end_m"),
            pl.col("time_lost_s").median(),
            pl.col("time_lost_s").min().alias("time_lost_min_s"),
            pl.col("time_lost_s").max().alias("time_lost_max_s"),
            pl.col("fuel_saved_l").median(),
            pl.col("live_time_lost_s").median(),
            pl.len().alias("support"),
        )
        .join(
            predictions.select(
                "zone_id", "predicted_fuel_saved_l", "predicted_time_lost_s"
            ),
            on="zone_id",
            how="left",
        )
        .with_columns(
            pl.when(pl.col("window") == "frozen")
            .then(pl.col("time_lost_s") - pl.col("predicted_time_lost_s"))
            .otherwise(None)
            .alias("prospective_time_prediction_error_s"),
            pl.when(pl.col("window") == "frozen")
            .then(pl.col("fuel_saved_l") - pl.col("predicted_fuel_saved_l"))
            .otherwise(None)
            .alias("prospective_fuel_prediction_error_l"),
        )
        .sort("zone_id", "window")
    )
    laps = pl.DataFrame(lap_rows)
    lap_push = laps.filter(pl.col("role") == "push")
    lap_lico = laps.filter(pl.col("role") == "lico")
    envelope = upstream_envelope(frozen)
    candidates = candidate_action_grid(envelope)
    result = {
        "analysis_id": "bahrain_native_fixed_distance_v2",
        "supersedes": "analysis_v1 local metrics: held-distance interpolation bug",
        "prediction_status": "original pre-run predictions unchanged; scoring corrected",
        "recovery_status": "post-hoc fixed endpoints; diagnostic, not prospective score",
        "fuel_interval_m": [100, 5350],
        "observed_fuel_saved_l": lap_push["fuel_used_l"].median()
        - lap_lico["fuel_used_l"].median(),
        "observed_official_time_lost_s": lap_lico["official_time_s"].median()
        - lap_push["official_time_s"].median(),
        "observed_fixed_time_lost_s": lap_lico["elapsed_time_s"].median()
        - lap_push["elapsed_time_s"].median(),
        "baseline": "same-run push laps 23,26,29 for prospective score only; not response training",
        "limitations": [
            "Four LICO repetitions at one planned dose per zone; no local response curve identified.",
            "Native scoring distance changes about every 0.2s; channel-timestamp interpolation is approximate.",
            "Negative T1 time difference is not a causal speed-up claim.",
            "Silent-zone deltas are context diagnostics, not measured LICO effects.",
            "The native impact flag on lap29 is a retained driver-reviewed audit note.",
        ],
        "source_hashes": {
            str(path.relative_to(ROOT)): previous.sha256_file(path)
            for path in [
                ROOT / previous.RAW_FILE,
                ROOT
                / "data/Bahrain International Circuit_P_2026-09-12T01_49_14Z.duckdb",
                ROOT / previous.DATASET_FILE,
                ROOT / previous.REVIEW_FILE,
                SESSION / "lap_schedule.csv",
                SESSION / "telemetry.csv",
                SESSION / "physical_references.csv",
                *[SESSION / name for name in frozen_files],
                Path(__file__),
                Path(previous.__file__),
                ROOT / "src/licor/analysis/fixed_distance.py",
            ]
        },
        "prior_analysis_hashes": {
            path.name: previous.sha256_file(path)
            for path in sorted((SESSION / "analysis_v1").iterdir())
            if path.is_file()
        },
    }
    output.mkdir(parents=True)
    passes.write_csv(output / "fixed_distance_passes.csv")
    scores.write_csv(output / "lico_pass_scores.csv")
    summary.write_csv(output / "zone_scores.csv")
    laps.write_csv(output / "lap_summary.csv")
    envelope.write_csv(output / "upstream_envelope.csv")
    candidates.write_csv(output / "candidate_action_grid.csv")
    result["artifact_hashes"] = {
        path.name: previous.sha256_file(path) for path in sorted(output.iterdir())
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def upstream_envelope(frozen: dict) -> pl.DataFrame:
    """Inspect uninterrupted full throttle before each heavy push brake.

    This is capture headroom, not permission to command the maximum lift. Keep
    one second of full-throttle pre-action context and 25m before the lift.
    """
    samples = build_labeled_experimental_lap_samples(
        dataset_label_file=ROOT / previous.DATASET_FILE,
        project_root=ROOT,
        include_run_ids={"bahrain_push_20260911_212732"},
    )
    references = pl.read_csv(SESSION / "physical_references.csv")
    rows = []
    for zone in frozen["zones"]:
        if zone["zone_id"] not in HEAVY_ZONES:
            continue
        ref = references.filter(pl.col("zone_id") == zone["zone_id"]).row(0, named=True)
        brake = float(ref["brake_onset_reference_m"])
        lap_starts = []
        for key, lap in samples.partition_by("lap_number", as_dict=True).items():
            anchors = distance_anchors(lap)
            approach = lap.filter(
                (pl.col("ts") >= anchors["ts"][0])
                & (pl.col("lap_distance_m") < brake - 25.0)
            ).sort("ts")
            if approach.is_empty():
                continue
            values = approach.to_dicts()
            # Ignore short shift cuts; only a sustained non-push period ends
            # the available straight. All thresholds describe capture, not an
            # approved action magnitude or a fitted response boundary.
            last_interruption = -1
            interruption_start = None
            for index, row in enumerate(values):
                interrupted = row["throttle_pct"] < 98.0 or row["brake_pct"] > 2.0
                if interrupted and interruption_start is None:
                    interruption_start = index
                if not interrupted and interruption_start is not None:
                    if row["ts"] - values[interruption_start]["ts"] >= 0.25:
                        last_interruption = index - 1
                    interruption_start = None
            if (
                interruption_start is not None
                and values[-1]["ts"] - values[interruption_start]["ts"] >= 0.25
            ):
                last_interruption = len(values) - 1
            segment = values[last_interruption + 1 :]
            if not segment:
                continue
            # Full pre-action history plus space for the audio/capture margin.
            context_end = segment[0]["ts"] + 1.0
            stable = next((row for row in segment if row["ts"] >= context_end), None)
            if stable:
                lap_starts.append(float(stable["lap_distance_m"]) + 25.0)
        if len(lap_starts) < 3:
            raise ValueError(f"insufficient upstream coverage: {zone['zone_id']}")
        # Respect the detector's current 500m lookback and stay inside the lap.
        candidate = math.ceil(max(max(lap_starts), brake - 500.0, 25.0) / 5.0) * 5.0
        rows.append(
            {
                "zone_id": zone["zone_id"],
                "display_label": zone["display_label"],
                "push_brake_reference_m": brake,
                "push_deceleration_distance_m": ref[
                    "deceleration_distance_reference_m"
                ],
                "push_brake_speed_kph": ref["approach_speed_reference_kph"],
                "push_minimum_speed_kph": ref["min_speed_reference_kph"],
                "frozen_lift_window_start_m": zone["lico_window_start_m"],
                "frozen_maximum_lift_lead_m": brake - zone["lico_window_start_m"],
                "v1_ratio_guard_maximum_lead_m": 0.85
                * ref["deceleration_distance_reference_m"],
                "proposed_capture_start_m": candidate - 25.0,
                "proposed_lift_window_start_m": candidate,
                "proposed_maximum_lift_lead_m": brake - candidate,
                "push_pass_support": len(lap_starts),
                "status": "capture_proposal_only_large_action_response_unvalidated",
            }
        )
    return pl.DataFrame(rows)


def candidate_action_grid(envelope: pl.DataFrame) -> pl.DataFrame:
    """Sample actual push context at each candidate, including beyond ratio 1.5.

    This grid never issues cues. Its acceleration windows precede the candidate
    by 0.2s; no LICO outcome participates in constructing candidate features.
    """
    samples = build_labeled_experimental_lap_samples(
        dataset_label_file=ROOT / previous.DATASET_FILE,
        project_root=ROOT,
        include_run_ids={"bahrain_push_20260911_212732"},
    )
    laps = [lap.sort("ts") for lap in samples.partition_by("lap_number")]
    rows = []
    for zone in envelope.iter_rows(named=True):
        for lead in range(25, int(zone["proposed_maximum_lift_lead_m"]) + 1, 25):
            lift = zone["push_brake_reference_m"] - lead
            values = []
            for lap in laps:
                anchors = distance_anchors(lap)
                cutoff = crossing_time(anchors, lift)
                value = _acceleration_before_ts(
                    lap.to_dicts(),
                    point_ts=cutoff,
                    config=BrakingEventConfig(),
                    sensor_valid=False,
                )
                if value is not None:
                    values.append(value)
            ratio = lead / zone["push_deceleration_distance_m"]
            rows.append(
                {
                    "zone_id": zone["zone_id"],
                    "candidate_lift_m": lift,
                    "lead_vs_push_brake_m": lead,
                    "lead_to_push_deceleration_ratio": ratio,
                    "push_acceleration_at_candidate_mps2": pl.Series(values).median(),
                    "acceleration_support": len(values),
                    "within_original_ratio_guard": ratio <= 0.85,
                    "within_original_acceleration_grid": ratio <= 1.5,
                    "response_status": "unvalidated_candidate_not_a_live_plan",
                }
            )
    return pl.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_analysis(args.output_dir), indent=2))
