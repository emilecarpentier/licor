"""Freeze Sebring push-derived, two-dose prospective LICO validation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from licor.analysis.cross_circuit_ml import (
    BrakingEventConfig,
    _acceleration_before_ts,
    _sensor_speed_acceleration_correlation,
    _nonnegative_two_feature_slopes,
    extract_physical_braking_events,
)
from licor.analysis.experimental_zone_dynamics import (
    build_labeled_experimental_lap_samples,
)
from licor.analysis.fixed_distance import NativeDistanceTrace, crossing_time
from licor.analysis.live_plan import LiveCuePlanConfig, build_live_cue_plan
from licor.analysis.collection_metadata import validate_dataset_collection_metadata
from licor.analysis.track_zones import TrackZoneTable
from licor.analysis.zone_detection import build_lap_telemetry
from licor.live.audio import RecordingAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session
from licor.ingestion import LmuTelemetryDatabase

ROOT = Path(__file__).resolve().parents[1]
RAW = Path("data/Sebring International Raceway_P_2026-09-12T15_41_46Z.duckdb")
DATASET = Path("config/datasets/sebring_lmp2_circuit_d_reviewed_2026-09-12.json")
TRANSFER = ROOT / "data/processed/experimental/sebring_lmp2_transfer_2026_09"
DEFAULT_PACK = TRANSFER / "lico_validation_pack_v1"
RUN_ID = "sebring_push_20260912_114122"
LAPS = (8, 9, 10, 11, 12)
TRACK_LENGTH = 5820.0
# Bounds isolate each main physical event; outcome groups are separate below.
EVENT_WINDOWS = (
    ("sbr_t01", "T1", 250, 600),
    ("sbr_t03", "T3-T5", 730, 1020),
    ("sbr_t05", "T5 (silent)", 1000, 1400),
    ("sbr_t07", "T7", 1700, 2250),
    ("sbr_t10", "T10", 2500, 2950),
    ("sbr_t13", "T13", 3040, 3460),
    ("sbr_t15", "T15-T16", 3800, 4140),
    ("sbr_t16", "T16 (silent)", 4090, 4600),
    ("sbr_t17", "T17", 5070, 5790),
)
OUTCOMES = {
    "sbr_t01": (100, 650),
    "sbr_t03": (650, 1400),
    "sbr_t07": (1400, 2200),
    "sbr_t10": (2200, 2900),
    "sbr_t13": (2900, 3450),
    "sbr_t15": (3450, 4600),
    "sbr_t17": (4600, 5800),
}
HISTORICAL = Path("data/processed/experimental/cross_circuit_ml_v2_release")
PROTOCOL = Path("config/collection_protocols/sebring_lmp2_two_dose_v1.json")
RUN_SHEET = Path("docs/sebring_lico_validation_run_sheet.md")
PATTERN = ("push", "A", "B", "push", "B", "A", "push")
DOSES = {
    "sbr_t01": (35, 65),
    "sbr_t03": (35, 70),
    "sbr_t07": (45, 95),
    "sbr_t10": (40, 80),
    "sbr_t13": (30, 60),
    "sbr_t15": (35, 75),
    "sbr_t17": (50, 110),
}


def plan_id(role: str) -> str:
    return f"sebring_lmp2_static_{role}_v1"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_push(output: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    output.mkdir(parents=True, exist_ok=True)
    samples = build_labeled_experimental_lap_samples(
        dataset_label_file=ROOT / DATASET,
        project_root=ROOT,
        include_run_ids={RUN_ID},
    )
    passes = pl.DataFrame(
        [
            {
                "run_id": RUN_ID,
                "lap_number": lap,
                "zone_id": zone,
                "zone_start_m": float(start),
                "zone_end_m": float(end),
            }
            for zone, _, start, end in EVENT_WINDOWS
            for lap in LAPS
        ]
    )
    events = extract_physical_braking_events(
        passes,
        samples,
        track_length_m=TRACK_LENGTH,
        config=BrakingEventConfig(post_zone_capture_margin_m=0),
    )
    events.write_csv(output / "physical_events.csv")
    references, approaches, outcomes = [], [], []
    with LmuTelemetryDatabase(ROOT / RAW) as db:
        trace = NativeDistanceTrace.from_database(db)
        driver_throttle = db.fixed_channel("Throttle Pos Unfiltered")
        filtered_throttle = db.fixed_channel("Throttle Pos")
        for zone, label, _, _ in EVENT_WINDOWS:
            selected = events.filter(
                (pl.col("zone_id") == zone)
                & (pl.col("braking_event_quality") == "ready")
            )
            if selected.height != 5:
                raise ValueError(
                    f"{zone}: incomplete physical support {selected.height}"
                )
            brake = float(selected["main_brake_onset_m"].median())
            decels = selected["push_deceleration_distance_observed_m"].to_list()
            references.append(
                {
                    "zone_id": zone,
                    "display_label": label,
                    "support": selected.height,
                    "brake_reference_m": brake,
                    "deceleration_reference_m": statistics.median(decels),
                    "deceleration_cv": statistics.stdev(decels)
                    / statistics.mean(decels),
                    "arrival_speed_kph": selected[
                        "main_brake_onset_speed_kph"
                    ].median(),
                    "minimum_speed_kph": selected["min_speed_point_kph"].median(),
                    "minimum_point_m": selected["min_speed_point_m"].median(),
                    "sensor_correlation_min": selected[
                        "acceleration_sensor_speed_correlation"
                    ].min(),
                }
            )
            for lap in LAPS:
                rows = list(
                    samples.filter(pl.col("lap_number") == lap)
                    .sort("ts")
                    .iter_rows(named=True)
                )
                anchors = trace.lap_anchors(lap)
                sensor_valid = (
                    _sensor_speed_acceleration_correlation(rows) or 0
                ) >= 0.8
                for lead in range(0, 501, 5):
                    point = brake - lead
                    if point < anchors["lap_distance_m"].min():
                        continue
                    ts = crossing_time(anchors, point)
                    before = [r for r in rows if ts - 1.2 <= r["ts"] <= ts - 0.2]
                    near = [r for r in rows if abs(r["ts"] - ts) <= 0.04]
                    approaches.append(
                        {
                            "zone_id": zone,
                            "lap_number": lap,
                            "lead_m": lead,
                            "point_m": point,
                            "acceleration_mps2": _acceleration_before_ts(
                                rows,
                                point_ts=ts,
                                config=BrakingEventConfig(),
                                sensor_valid=sensor_valid,
                            ),
                            "sensor_valid": sensor_valid,
                            "driver_throttle_min_pct": float(
                                driver_throttle.filter(
                                    (pl.col("ts") >= ts - 0.04)
                                    & (pl.col("ts") <= ts + 0.04)
                                )["value"].min()
                            ),
                            "throttle_at_point_min_pct": min(
                                r["throttle_pct"] for r in near
                            ),
                            "brake_at_point_max_pct": max(r["brake_pct"] for r in near),
                            "window_throttle_min_pct": min(
                                r["throttle_pct"] for r in before
                            )
                            if before
                            else None,
                            "window_brake_max_pct": max(r["brake_pct"] for r in before)
                            if before
                            else None,
                            "speed_kph": float(
                                np.interp(
                                    ts,
                                    trace.speed["ts"].to_numpy(),
                                    trace.speed["value"].to_numpy(),
                                )
                            ),
                        }
                    )
                if zone in OUTCOMES:
                    start, end = OUTCOMES[zone]
                    start_ts = crossing_time(anchors, start)
                    foot = float(
                        np.interp(
                            start_ts,
                            driver_throttle["ts"].to_numpy(),
                            driver_throttle["value"].to_numpy(),
                        )
                    )
                    filtered = float(
                        np.interp(
                            start_ts,
                            filtered_throttle["ts"].to_numpy(),
                            filtered_throttle["value"].to_numpy(),
                        )
                    )
                    outcomes.append(
                        {
                            "zone_id": zone,
                            "lap_number": lap,
                            "zone_start_driver_throttle_pct": foot,
                            "zone_start_zero_throttle": filtered <= 1.0,
                            "zone_start_zero_driver_throttle": foot <= 1.0,
                            **trace.outcome(lap, start, end),
                        }
                    )
    refs = pl.DataFrame(references)
    grid = pl.DataFrame(approaches)
    refs.write_csv(output / "physical_references.csv")
    grid.write_csv(output / "approach_grid.csv")
    pl.DataFrame(outcomes).write_csv(output / "fixed_push_outcomes.csv")
    return refs, grid


def fit_history() -> tuple[dict, pl.DataFrame]:
    views = pl.read_parquet(ROOT / HISTORICAL / "fold_feature_views.parquet")
    train = views.filter(
        (pl.col("split_role") == "train")
        & pl.col("model_eligible")
        & pl.col("has_lico")
    )
    if set(train["circuit_id"].unique()) != {
        "spa_francorchamps",
        "paul_ricard",
        "bahrain",
    }:
        raise ValueError("Training circuit whitelist violated")
    if train.filter(pl.col("run_id").str.contains("sebring|232207")).height:
        raise ValueError("Destination or locked confirmation leaked into training")
    train = train.sort(["observation_id", "fold_id"]).unique(
        "observation_id", keep="first", maintain_order=True
    )
    diagnostics = pl.read_csv(ROOT / HISTORICAL / "diagnostic_predictions.csv")
    result = {}
    for target, column in (
        ("fuel", "target_fuel_saved_vs_fold_push_l"),
        ("time", "target_time_lost_vs_fold_push_s"),
    ):
        clean = train.filter(
            pl.col(column).is_not_null()
            & pl.col("executed_lift_lead_to_push_deceleration_ratio").is_not_null()
        )
        x = clean["executed_lift_lead_to_push_deceleration_ratio"].to_numpy()
        y = clean[column].to_numpy()
        if (
            not len(x)
            or not np.isfinite(x).all()
            or not np.isfinite(y).all()
            or np.dot(x, x) <= 0
        ):
            raise ValueError("Historical response lacks finite support")
        shadow = clean.filter(
            (pl.col("executed_acceleration_lookup_status") == "in_range")
            & pl.col("executed_acceleration_weighted_action").is_not_null()
        )
        slopes = _nonnegative_two_feature_slopes(
            shadow["executed_lift_lead_to_push_deceleration_ratio"].to_list(),
            shadow["executed_acceleration_weighted_action"].to_list(),
            shadow[column].to_list(),
        )
        errors = diagnostics.filter(
            (pl.col("model_name") == "pooled_monotone_action_only_v1")
            & (
                pl.col("target_name")
                == ("fuel_saved_l" if target == "fuel" else "time_lost_s")
            )
        )
        result[target] = {
            "slope": max(0.0, float(np.dot(x, y) / np.dot(x, x))),
            "training_rows": len(x),
            "shadow_action_slope": slopes[0],
            "shadow_acceleration_slope": slopes[1],
            "shadow_training_rows": shadow.height,
            "historical_heldout_p90_absolute_error": float(
                errors["error"].abs().quantile(0.9)
            ),
            "ratio_min": float(x.min()),
            "ratio_max": float(x.max()),
        }
    return result, train.select(
        "observation_id",
        "circuit_id",
        "run_id",
        "lap_number",
        "zone_id",
        "source_raw_sha256",
    )


def design(
    refs: pl.DataFrame, grid: pl.DataFrame, model: dict
) -> tuple[pl.DataFrame, dict, list]:
    predictions, zones, capture = [], [], []
    for index, (zone, distances) in enumerate(DOSES.items()):
        ref = refs.filter(pl.col("zone_id") == zone).row(0, named=True)
        available = (
            grid.filter(pl.col("zone_id") == zone)
            .group_by("lead_m")
            .agg(
                pl.len().alias("support"),
                pl.col("driver_throttle_min_pct").min().alias("foot"),
                pl.col("brake_at_point_max_pct").max().alias("brake"),
                pl.col("acceleration_mps2").count().alias("accel_support"),
            )
            .sort("lead_m")
        )
        contiguous = 25
        for row in available.filter(pl.col("lead_m") >= 25).iter_rows(named=True):
            if row["support"] != 5 or row["foot"] < 99 or row["brake"] >= 1:
                break
            contiguous = row["lead_m"]
        capture.append(
            {
                "zone_id": zone,
                "upstream_capture_start_m": ref["brake_reference_m"] - contiguous,
                "available_lead_observed_m": contiguous,
                "scan_limit_m": 500,
                "limited_by_scan_or_lap_start": contiguous >= 500 or zone == "sbr_t01",
                "future_large_lifts_authorized": False,
            }
        )
        start, end = OUTCOMES[zone]
        turn = int(zone[-2:])
        turns = [3, 4, 5] if turn == 3 else [15, 16] if turn == 15 else [turn]
        zones.append(
            {
                "zone_id": zone,
                "turn_numbers": turns,
                "display_label": ref["display_label"],
                "start_distance_m": start,
                "lico_window_start_m": start,
                "brake_reference_m": ref["brake_reference_m"],
                "end_distance_m": end,
                "lico_eligible": True,
                "optimization_role": "candidate",
                "validation_end_rule": "manual_distance",
                "review_status": "needs_driver_review",
                "notes": "Prospective validation only. Fixed outcome boundary, not upstream capture limit. T3/T15 include downstream silent corner; T17 may retain a beyond-line carryover.",
            }
        )
        for role in ("A", "B"):
            # Stagger the larger dose across zones to balance overall lap disruption.
            high = (index % 2 == 1) if role == "A" else (index % 2 == 0)
            lead = distances[int(high)]
            row_grid = grid.filter(
                (pl.col("zone_id") == zone) & (pl.col("lead_m") == lead)
            )
            ratio = lead / ref["deceleration_reference_m"]
            accel = float(row_grid["acceleration_mps2"].median())
            weighted = ratio * max(accel, 0)
            speed = float(row_grid["speed_kph"].median())
            cue = ref["brake_reference_m"] - lead - 0.35 * speed / 3.6
            if (
                ref["deceleration_cv"] > 0.15
                or row_grid.height != 5
                or row_grid["acceleration_mps2"].null_count()
                or row_grid["driver_throttle_min_pct"].min() < 99
                or row_grid["brake_at_point_max_pct"].max() >= 1
                or weighted > 2.75547
                or not 0.15 <= ratio <= 0.85
                or lead + 0.35 * speed / 3.6 > contiguous
                or not start < cue < ref["brake_reference_m"] < end
            ):
                raise ValueError(f"Prospective action guard failed: {zone}/{role}")
            predictions.append(
                {
                    "plan_id": plan_id(role),
                    "role": role,
                    "zone_id": zone,
                    "display_label": ref["display_label"],
                    "dose": "higher" if high else "lower",
                    "selected_lico_distance_m": float(lead),
                    "action_ratio": ratio,
                    "push_acceleration_at_planned_lift_mps2": accel,
                    "acceleration_weighted_action": weighted,
                    "physical_support": 5,
                    "driver_throttle_min_pct": float(
                        row_grid["driver_throttle_min_pct"].min()
                    ),
                    "cue_latency_reference_speed_kph": speed,
                    "brake_start_speed_kph": ref["arrival_speed_kph"],
                    "predicted_fuel_saved_l": model["fuel"]["slope"] * ratio,
                    "predicted_time_lost_s": model["time"]["slope"] * ratio,
                    "shadow_fuel_saved_l": model["fuel"]["shadow_action_slope"] * ratio
                    + model["fuel"]["shadow_acceleration_slope"] * weighted,
                    "shadow_time_lost_s": model["time"]["shadow_action_slope"] * ratio
                    + model["time"]["shadow_acceleration_slope"] * weighted,
                    "is_selected_for_lico": True,
                    "plan_status": "prospective_validation_only",
                    "model_status": "three_circuit_action_only_v2",
                    "quality_flags": "local_response_unvalidated;new_outcome_windows;acceleration_shadow_only",
                    "strategy_role": "prediction_validation",
                }
            )
    table = {
        "schema_version": 1,
        "track_name": "Sebring International Raceway",
        "car_class": "LMP2_ELMS",
        "status": "needs_driver_review",
        "source": "Five clean push laps; derived before local LICO; geometry reviewed by agent, not driver certification.",
        "zones": zones,
    }
    issues = TrackZoneTable.model_validate(table).validation_issues()
    if issues:
        raise ValueError(issues)
    return pl.DataFrame(predictions), table, capture


class SyntheticSource:
    def __init__(self, samples):
        self.samples = iter(samples)

    def read_next_sample(self, *, timeout_ms):
        del timeout_ms
        return next(self.samples)

    def close(self):
        pass


def preflight(plan_path: Path) -> dict:
    plan = pl.read_csv(plan_path)
    positions = sorted(
        {0.0, *[x + d for x in plan["cue_distance_m"] for d in (-0.5, 0.5)]}
    )
    samples = [
        LmuLiveTelemetrySample(lap_number=lap, lap_distance_m=distance, ts=float(i))
        for i, (lap, distance) in enumerate(
            (lap, d) for lap in range(9, 18) for d in positions
        )
    ]
    audio = RecordingAudioCueAdapter()
    with tempfile.TemporaryDirectory(prefix="sebring_check_", dir=TRANSFER) as tmp:
        events = run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=Path(tmp) / "events.csv",
            sample_source=SyntheticSource(samples),
            audio_adapter=audio,
            config=LiveStaticCueSessionConfig(
                cue_lap_numbers=(11, 12, 14, 15),
                stop_after_lap_number=16,
                lap_plan_schedule=(
                    (11, plan_id("A")),
                    (12, plan_id("B")),
                    (14, plan_id("B")),
                    (15, plan_id("A")),
                ),
            ),
        )
    expected = {
        (lap, plan_id(role), z)
        for lap, role in ((11, "A"), (12, "B"), (14, "B"), (15, "A"))
        for z in DOSES
    }
    actual = {(c.lap_number, c.plan_id, c.zone_id) for c in audio.cues}
    if actual != expected or len(audio.cues) != 28 or events.height != 84:
        raise ValueError("Two-dose preflight failed")
    return {
        "scored_laps": 7,
        "cue_count": len(audio.cues),
        "logged_crossings": events.height,
        "system_audio_emitted": False,
    }


def source_paths() -> list[Path]:
    return [
        RAW,
        DATASET,
        PROTOCOL,
        RUN_SHEET,
        Path(__file__).relative_to(ROOT),
        HISTORICAL / "fold_feature_views.parquet",
        HISTORICAL / "diagnostic_predictions.csv",
        HISTORICAL / "build_manifest.json",
        Path("scripts/templates/sebring_lico_validation.ps1"),
        Path("scripts/templates/sebring_lico_validation.cmd"),
        *[
            Path(p)
            for p in (
                "src/licor/live/runtime.py",
                "src/licor/live/lmu_live_cli.py",
                "src/licor/live/audio.py",
                "src/licor/live/lmu_shared_memory.py",
                "src/licor/analysis/live_plan.py",
                "src/licor/analysis/fixed_distance.py",
                "src/licor/analysis/cross_circuit_ml.py",
                "src/licor/analysis/experimental_zone_dynamics.py",
                "src/licor/analysis/zone_detection.py",
                "src/licor/analysis/live_cue_runner.py",
                "src/licor/ingestion/duckdb_reader.py",
            )
        ],
    ]


def replay_native(plan_path: Path) -> dict:
    """Replay recorded push trajectories through the cue engine, with no sound."""
    with LmuTelemetryDatabase(ROOT / RAW) as db:
        recorded = build_lap_telemetry(db, lap_numbers=set(LAPS))
    samples = []
    offset = 0.0
    for index, live_lap in enumerate(range(9, 18)):
        lap = recorded.filter(pl.col("lap_number") == LAPS[index % len(LAPS)])
        duration = float(lap["lap_end_ts"][0] - lap["lap_start_ts"][0])
        for row in lap.iter_rows(named=True):
            samples.append(
                LmuLiveTelemetrySample(
                    lap_number=live_lap,
                    lap_distance_m=row["lap_distance_m"],
                    ts=offset + row["lap_elapsed_s"],
                    speed_kph=row["ground_speed_kph"],
                    throttle_pct=row["throttle_pct"],
                    brake_pct=row["brake_pct"],
                    fuel_level_l=row["fuel_level_l"],
                )
            )
        offset += duration
    audio = RecordingAudioCueAdapter()
    with tempfile.TemporaryDirectory(prefix="sebring_replay_", dir=TRANSFER) as tmp:
        events = run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=Path(tmp) / "events.csv",
            sample_source=SyntheticSource(samples),
            audio_adapter=audio,
            config=LiveStaticCueSessionConfig(
                cue_lap_numbers=(11, 12, 14, 15),
                stop_after_lap_number=16,
                lap_plan_schedule=(
                    (11, plan_id("A")),
                    (12, plan_id("B")),
                    (14, plan_id("B")),
                    (15, plan_id("A")),
                ),
            ),
        )
    expected = {
        (lap, plan_id(role), z)
        for lap, role in ((11, "A"), (12, "B"), (14, "B"), (15, "A"))
        for z in DOSES
    }
    if {(c.lap_number, c.plan_id, c.zone_id) for c in audio.cues} != expected or len(
        audio.cues
    ) != 28:
        raise ValueError("Native replay cue schedule failed")
    enabled = events.filter(pl.col("cue_enabled"))
    if enabled.filter(pl.col("trigger_status") != "fired_on_time").height:
        raise ValueError("Native replay has out-of-tolerance cues")
    return {
        "cue_count": 28,
        "all_cues_on_time": True,
        "system_audio_emitted": False,
        "scope": "Recorded push trajectories replayed in scheduled slots; not a prospective LICO or hardware latency test.",
    }


def verify_pack(pack_dir: Path) -> dict:
    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    for group, root in (("sources", ROOT), ("artifacts", pack_dir)):
        for name, digest in manifest[group].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
                raise ValueError(f"{group} hash mismatch: {name}")
    return {
        "pack": str(pack_dir),
        "hashes_verified": True,
        "silent_preflight": preflight(pack_dir / "plan.csv"),
    }


def build_pack(pack_dir: Path) -> dict:
    if pack_dir.exists():
        raise FileExistsError(f"Refusing to replace frozen pack: {pack_dir}")
    if (
        sha256(ROOT / RAW)
        != "8c29be2086faf8f790c0fe0de176527e8c6111f187ed3229799deba264708e13"
    ):
        raise ValueError("Reviewed push source changed; redo intake before freezing")
    ready = validate_dataset_collection_metadata(
        ROOT / DATASET,
        ROOT / "config/collection_protocols/sebring_lmp2_circuit_d_v1.json",
    )
    if ready["metadata_status"].to_list() != ["ready"]:
        raise ValueError("Push metadata not ready")
    for path in source_paths():
        if not (ROOT / path).is_file():
            raise FileNotFoundError(path)
    refs, grid = audit_push(TRANSFER / "lico_design_audit_v1")
    model, training = fit_history()
    predictions, zones, capture = design(refs, grid, model)
    pack_dir.mkdir(parents=True)
    plans = [
        build_live_cue_plan(
            predictions.filter(pl.col("role") == role),
            refs,
            config=LiveCuePlanConfig(
                plan_id=plan_id(role),
                track_name="Sebring International Raceway",
                car_class="LMP2_ELMS",
                race_context_id="sebring_two_dose_prospective_v1",
                minimum_confidence_label="prospective_validation_only",
                track_length_m=TRACK_LENGTH,
                cue_tolerance_m=5.0,
                cue_latency_compensation_s=0.35,
                notes="Frozen A/B doses. Full release at beep; normal braking. No online adaptation.",
            ),
        )
        for role in ("A", "B")
    ]
    pl.concat(plans).write_csv(pack_dir / "plan.csv")
    predictions.write_csv(pack_dir / "predictions.csv")
    refs.write_csv(pack_dir / "physical_references.csv")
    training.write_csv(pack_dir / "training_observations.csv")
    for name in ("physical_events.csv", "approach_grid.csv", "fixed_push_outcomes.csv"):
        (pack_dir / name).write_bytes(
            (TRANSFER / "lico_design_audit_v1" / name).read_bytes()
        )
    metadata = {
        "schema_version": 1,
        "run_id": "",
        "telemetry_duckdb": "",
        "status": "prepared_not_run",
        "collection_protocol_id": "sebring_lmp2_two_dose_v1",
        "collection_session_id": "two_dose_validation_01",
        "collection_design": "recommendation_execution",
        "target_zones": list(DOSES),
        "planned_lico_profile_id": "sebring_lmp2_two_dose_v1",
        "audio_cue_plan_id": "sebring_lmp2_two_dose_v1",
        "execution_quality": "unknown",
        "labels_quality": "pending_driver_review",
        "driver_notes": "",
        "starting_fuel_l": 55,
        "tire_wear_multiplier": 0,
        "weather_constant": True,
        "setup_id": "constant_not_recorded",
        "expected_beeps": 28,
        "lap_pattern": list(PATTERN),
    }
    plan_manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_lico_outcomes_observed": False,
        "training_circuits": ["spa_francorchamps", "paul_ricard", "bahrain"],
        "model": model,
        "pattern": list(PATTERN),
        "plan_totals": predictions.group_by("role")
        .agg(
            pl.col("predicted_fuel_saved_l").sum(),
            pl.col("predicted_time_lost_s").sum(),
        )
        .sort("role")
        .to_dicts(),
        "acceleration_role": "Direct push sampling at proposed lift, weighted-action guard 2.75547, separate shadow prediction; no proved predictive gain.",
        "future_evaluation": {
            "calibration_scored_indices": [2, 3],
            "test_scored_indices": [5, 6],
            "same_fixed_test_at_local_budgets": [0, 1, 2],
            "prior_push_references_only_for_transfer_benchmark": True,
            "same_run_push_controls_for_operational_score": [1, 4, 7],
            "within_run_independence_limited": True,
        },
        "outcome_rule": "Native fixed-distance interpolation, non-overlapping grouped windows. New endpoints are a transfer limitation; T17 beyond-line recovery remains diagnostic, not silently added.",
        "silent_corners": [5, 16],
        "expected_beeps": 28,
        "adaptive_mode": "offline_only",
    }
    for name, obj in (
        ("track_zones.json", zones),
        ("capture_envelope.json", capture),
        ("run_metadata_template.json", metadata),
        ("plan_manifest.json", plan_manifest),
    ):
        (pack_dir / name).write_text(
            json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    pl.DataFrame(
        [
            {
                "relative_lap": i,
                "role": role,
                "driver_lap_label": "",
                "errors_by_turn_phase": "",
                "beeps_heard": "",
            }
            for i, role in enumerate(PATTERN, 1)
        ]
    ).write_csv(pack_dir / "lap_notes_template.csv")
    launcher = (ROOT / "scripts/templates/sebring_lico_validation.ps1").read_text(
        encoding="utf-8"
    )
    (pack_dir / "start_lico_validation.ps1").write_text(
        launcher.replace("__ROOT__", Path(os.path.relpath(ROOT, pack_dir)).as_posix()),
        encoding="utf-8",
    )
    (pack_dir / "start_lico_validation.cmd").write_bytes(
        (ROOT / "scripts/templates/sebring_lico_validation.cmd").read_bytes()
    )
    (pack_dir / "README.md").write_bytes((ROOT / RUN_SHEET).read_bytes())
    (pack_dir / "native_replay_check.json").write_text(
        json.dumps(replay_native(pack_dir / "plan.csv"), indent=2), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "sources": {p.as_posix(): sha256(ROOT / p) for p in source_paths()},
        "artifacts": {
            p.name: sha256(p) for p in sorted(pack_dir.iterdir()) if p.is_file()
        },
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return verify_pack(pack_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    if args.audit_only:
        refs, _ = audit_push(TRANSFER / "lico_design_audit_v1")
        print(refs.write_csv())
    else:
        print(
            json.dumps(
                verify_pack(args.pack_dir)
                if args.verify_only
                else build_pack(args.pack_dir),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
