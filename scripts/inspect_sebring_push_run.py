"""Reproduce the Sebring push intake; no refit or live recommendations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

from licor.analysis.lap_summary import LapSummaryConfig, summarize_laps
from licor.analysis.zone_detection import (
    build_lap_telemetry,
    detect_braking_zones,
    detect_lift_and_coast_zones,
)
from licor.ingestion import LmuTelemetryDatabase

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/Sebring International Raceway_P_2026-09-12T15_41_46Z.duckdb"
OUTPUT = ROOT / (
    "data/processed/experimental/sebring_lmp2_transfer_2026_09/"
    "sessions/sebring_push_20260912_114122/intake_v1"
)
LAPS = {8, 9, 10, 11, 12}
CHANNELS = ("Lap Dist", "Fuel Level", "Ground Speed", "Throttle Pos", "Brake Pos")


def profile_values(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    return {
        "samples": len(values),
        "nonfinite": int((~np.isfinite(values)).sum()),
        "minimum": float(finite.min()) if len(finite) else None,
        "maximum": float(finite.max()) if len(finite) else None,
    }


def classify_coast_context(coasts: pl.DataFrame, brakes: pl.DataFrame) -> list[dict]:
    """Retain detector flags, distinguishing a lift after earlier braking."""
    rows = []
    for row in coasts.filter(pl.col("has_lico")).iter_rows(named=True):
        prior = brakes.filter(
            (pl.col("lap_number") == row["lap_number"])
            & (pl.col("start_ts") < row["brake_start_ts"])
            & (pl.col("end_ts") >= row["brake_start_ts"] - 2.0)
        )
        # Distance establishes that the apparent lift began inside earlier braking.
        overlap = prior.filter(
            (pl.col("start_lap_distance_m") <= row["lico_start_m"])
            & (pl.col("end_lap_distance_m") >= row["lico_start_m"])
        )
        rows.append(
            {
                **row,
                "review_context": "release_within_prior_braking"
                if overlap.height
                else "review_approach_lift",
                "intentional_lico_training_eligible": False,
            }
        )
    return rows


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with LmuTelemetryDatabase(RAW) as db:
        metadata = db.metadata()
        if metadata.get("TrackName") != "Sebring International Raceway":
            raise ValueError("Unexpected circuit")
        if metadata.get("CarClass") != "LMP2_ELMS":
            raise ValueError("Unexpected vehicle class")
        # Native distance coordinate observed around 5815 m; not nominal track length.
        summary = summarize_laps(
            db,
            config=LapSummaryConfig(
                min_lap_distance_m=5800,
                max_lap_distance_m=5900,
            ),
        )
        scored = summary.filter(pl.col("lap_number").is_in(sorted(LAPS)))
        if scored.height != 5 or not scored["passes_basic_validation"].all():
            raise ValueError("Expected five complete non-pit push laps")
        summary.drop("target_zones").write_csv(OUTPUT / "lap_summary.csv")
        profile = []
        for interval in db.lap_intervals():
            if interval.lap_number not in LAPS:
                continue
            for name in CHANNELS:
                frame = db.fixed_channel(name).filter(
                    (pl.col("ts") >= interval.start_ts)
                    & (pl.col("ts") < interval.end_ts)
                )
                values = frame["value"].to_numpy()
                row = {
                    "lap_number": interval.lap_number,
                    "channel": name,
                    **profile_values(values),
                }
                frequency = db.channels()[name].frequency_hz
                row["start_gap_s"] = float(frame["ts"][0] - interval.start_ts)
                row["end_gap_s"] = float(interval.end_ts - frame["ts"][-1])
                row["coverage_ok"] = (
                    max(row["start_gap_s"], row["end_gap_s"]) <= 2 / frequency
                )
                if name == "Lap Dist":
                    row["backward_steps"] = int((np.diff(values) < -1).sum())
                if name == "Fuel Level":
                    row["fuel_increase_steps"] = int((np.diff(values) > 0.01).sum())
                profile.append(row)
        pl.DataFrame(profile).write_csv(OUTPUT / "channel_quality.csv")
        if any(row["nonfinite"] or not row["coverage_ok"] for row in profile):
            raise ValueError("Nonfinite or incomplete core channel coverage")
        samples = build_lap_telemetry(db, lap_numbers=LAPS)
        brakes = detect_braking_zones(samples)
        coasts = detect_lift_and_coast_zones(samples, brakes)
        brakes.write_csv(OUTPUT / "braking_segments.csv")
        # Exploratory main-braking landmarks, not named corners or cue boundaries.
        main_brakes = (
            brakes.filter(pl.col("peak_brake_pct") >= 20)
            .sort(["lap_number", "start_lap_distance_m"])
            .with_columns(
                pl.col("start_ts").rank("ordinal").over("lap_number").alias("landmark")
            )
        )
        if main_brakes.group_by("lap_number").len()["len"].to_list() != [9] * 5:
            raise ValueError(
                "Review main-braking landmark alignment before aggregating"
            )
        main_brakes.group_by("landmark").agg(
            pl.col("lap_number").n_unique().alias("lap_count"),
            pl.col("start_lap_distance_m").median().alias("median_brake_start_m"),
            (
                pl.col("start_lap_distance_m").max()
                - pl.col("start_lap_distance_m").min()
            ).alias("brake_start_range_m"),
            pl.col("brake_start_speed_kph").median().alias("median_arrival_speed_kph"),
            pl.col("min_speed_kph").median().alias("median_braking_min_speed_kph"),
        ).sort("landmark").write_csv(OUTPUT / "braking_landmarks_exploratory.csv")
        coasts.write_csv(OUTPUT / "coast_detector.csv")
        context = classify_coast_context(coasts, brakes)
        pl.DataFrame(context).write_csv(OUTPUT / "coast_review.csv")
        events = {
            name: db.event_series(name).to_dicts()
            for name in (
                "Lap",
                "In Pits",
                "LastImpactMagnitude",
                "Lap Time",
                "Yellow Flag State",
            )
            if name in db.events()
        }
        (OUTPUT / "events.json").write_text(
            json.dumps(events, indent=2), encoding="utf-8"
        )
        result = {
            "run_id": "sebring_push_20260912_114122",
            "source": RAW.relative_to(ROOT).as_posix(),
            "source_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metadata": {
                k: metadata[k]
                for k in (
                    "TrackName",
                    "TrackLayout",
                    "CarName",
                    "CarClass",
                    "SessionType",
                )
            },
            "driver_review": "No notable errors, confirmed 2026-09-12",
            "retained_push_laps": sorted(LAPS),
            "lap_time_min_s": scored["lap_time_s"].min(),
            "lap_time_max_s": scored["lap_time_s"].max(),
            "lap_time_mean_s": scored["lap_time_s"].mean(),
            "lap_time_sample_sd_s": scored["lap_time_s"].std(),
            "mean_fuel_used_l": scored["fuel_used_l"].mean(),
            "braking_segments": brakes.height,
            "raw_coast_flags": len(context),
            "coast_contexts": [row["review_context"] for row in context],
            "zone_start_zero_throttle": "pending: no frozen Sebring zone boundaries yet",
            "status": "push_intake_complete_zone_design_pending",
            "live_authorized": False,
        }
        (OUTPUT / "intake_manifest.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
