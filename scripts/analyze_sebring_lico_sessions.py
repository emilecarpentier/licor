"""Read-only native scoring of both Sebring LICO sessions; never refit models."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

from licor.analysis.fixed_distance import NativeDistanceTrace, crossing_time
from licor.analysis.lap_summary import LapSummaryConfig, summarize_laps
from licor.ingestion import LmuTelemetryDatabase

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/processed/experimental/sebring_lmp2_transfer_2026_09"
PACK = BASE / "lico_validation_pack_v1"
NATIVE = Path(
    "C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry"
)
RUNS = (
    ("sebring_push_20260912_114122", "15_41_46", "prior_push"),
    ("sebring_lico_20260912_132042", "17_20_59", "first_attempt"),
    ("sebring_abab_20260912_134132", "17_41_51", "retry"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample(frame: pl.DataFrame, ts: float) -> float:
    if not frame["ts"][0] <= ts <= frame["ts"][-1]:
        raise ValueError("channel does not bracket requested timestamp")
    return float(np.interp(ts, frame["ts"].to_numpy(), frame["value"].to_numpy()))


def sustained_onset(
    frame: pl.DataFrame, start: float, end: float, *, above: bool
) -> float | None:
    """First >=0.10 s sustained threshold crossing; 5 percent pedal threshold."""
    part = frame.filter(pl.col("ts").is_between(start, end))
    times, values = part["ts"].to_numpy(), part["value"].to_numpy()
    active = values >= 5 if above else values <= 5
    beginning = None
    for ts, match in zip(times, active):
        if not match:
            beginning = None
        elif beginning is None:
            beginning = float(ts)
        elif ts - beginning >= 0.1 - 1e-8:
            return beginning
    return None


def contrasts(passes: pl.DataFrame) -> pl.DataFrame:
    """Keep prior and same-attempt baselines separate, never pool references."""
    outputs = []
    for baseline, cohort in (
        ("prior_push_5", "prior_push"),
        ("first_attempt_push_2", "first_attempt"),
    ):
        refs = passes.filter(
            (pl.col("cohort") == cohort)
            & (pl.col("role") == "push")
            & pl.col("quality_ok")
        )
        ref = refs.group_by("zone_id").agg(
            pl.len().alias("push_support"),
            (pl.col("impact_event_count") > 0)
            .sum()
            .alias("baseline_impact_pass_count"),
            pl.col("elapsed_time_s").median().alias("push_time_s"),
            pl.col("fuel_used_l").median().alias("push_fuel_l"),
            pl.col("exit_speed_kph").median().alias("push_exit_speed_kph"),
            pl.col("entry_speed_kph").median().alias("push_entry_speed_kph"),
        )
        outputs.append(
            passes.filter(pl.col("role").is_in(["A", "B"]) & pl.col("quality_ok"))
            .join(ref, on="zone_id")
            .with_columns(
                pl.lit(baseline).alias("baseline"),
                (pl.col("elapsed_time_s") - pl.col("push_time_s")).alias("time_lost_s"),
                (pl.col("push_fuel_l") - pl.col("fuel_used_l")).alias("fuel_saved_l"),
                (pl.col("exit_speed_kph") - pl.col("push_exit_speed_kph")).alias(
                    "exit_speed_delta_kph"
                ),
                (pl.col("entry_speed_kph") - pl.col("push_entry_speed_kph")).alias(
                    "entry_speed_delta_kph"
                ),
            )
        )
    return pl.concat(outputs)


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    zones = json.loads((PACK / "track_zones.json").read_text())["zones"]
    predictions = pl.read_csv(PACK / "predictions.csv")
    sources = {
        str(p): sha(p)
        for p in (
            Path(__file__),
            ROOT / "src/licor/analysis/fixed_distance.py",
            PACK / "track_zones.json",
            PACK / "predictions.csv",
            PACK / "plan.csv",
        )
    }
    passes, laps, channels, cues, execution, audit = [], [], [], [], [], []
    for run_id, suffix, cohort in RUNS:
        filename = f"Sebring International Raceway_P_2026-09-12T{suffix}Z.duckdb"
        path = ROOT / "data" / filename
        if not path.exists():
            path = NATIVE / filename
        sources[str(path)] = sha(path)
        session = BASE / "sessions" / run_id
        if cohort == "prior_push":
            schedule = [{"lap_number": n, "role": "push"} for n in range(8, 13)]
        else:
            schedule = pl.read_csv(session / "lap_schedule.csv").to_dicts()
            frozen = json.loads((session / "pack_manifest.json").read_text())
            for name in (
                "plan.csv",
                "predictions.csv",
                "track_zones.json",
                "plan_manifest.json",
            ):
                if sha(session / name) != frozen["artifacts"][name]:
                    raise ValueError(f"Frozen artifact changed: {run_id}/{name}")
                sources[str(session / name)] = sha(session / name)
            if sha(session / "plan.csv") != sha(PACK / "plan.csv"):
                raise ValueError("Different cue doses across sessions")
            for name in ("events.csv", "telemetry.csv", "lap_schedule.csv"):
                sources[str(session / name)] = sha(session / name)
            events = pl.read_csv(session / "events.csv").filter(pl.col("cue_enabled"))
            if events.select("lap_number", "zone_id").is_duplicated().any():
                raise ValueError("Duplicate audible lap-zone event")
            cues.extend(events.to_dicts())
        with LmuTelemetryDatabase(path) as db:
            meta = db.metadata()
            if (
                meta.get("TrackName") != "Sebring International Raceway"
                or meta.get("CarClass") != "LMP2_ELMS"
            ):
                raise ValueError("Wrong track or class")
            trace = NativeDistanceTrace.from_database(db)
            summary = summarize_laps(
                db,
                config=LapSummaryConfig(
                    min_lap_distance_m=5800, max_lap_distance_m=5900
                ),
            )
            fixed = {
                name: db.fixed_channel(name)
                for name in (
                    "Throttle Pos",
                    "Throttle Pos Unfiltered",
                    "Brake Pos",
                    "Fuel Level",
                    "Ground Speed",
                )
            }
            impacts = db.event_series("LastImpactMagnitude")
            audit.append(
                {
                    "run_id": run_id,
                    "metadata": meta,
                    "impact_events": impacts.to_dicts(),
                    "pit_events": db.event_series("In Pits").to_dicts(),
                }
            )
            for planned in schedule:
                number, role = int(planned["lap_number"]), planned["role"]
                identity = {
                    "run_id": run_id,
                    "cohort": cohort,
                    "lap_number": number,
                    "role": role,
                }
                if number not in trace.intervals:
                    laps.append(
                        {
                            **identity,
                            "complete": False,
                            "quality_ok": False,
                            "note": "No native closing lap event; not scored",
                        }
                    )
                    continue
                interval = trace.intervals[number]
                basic = summary.filter(pl.col("lap_number") == number).to_dicts()[0]
                quality = bool(basic["passes_basic_validation"])
                for name, frame in fixed.items():
                    part = frame.filter(
                        pl.col("ts").is_between(
                            interval.start_ts, interval.end_ts, closed="left"
                        )
                    )
                    frequency = db.channels()[name].frequency_hz
                    ok = part.height > 0 and np.isfinite(part["value"].to_numpy()).all()
                    if ok:
                        ok = (
                            max(
                                part["ts"][0] - interval.start_ts,
                                interval.end_ts - part["ts"][-1],
                            )
                            <= 2 / frequency
                        )
                    quality = quality and bool(ok)
                    channels.append(
                        {
                            **identity,
                            "channel": name,
                            "samples": part.height,
                            "coverage_finite_ok": bool(ok),
                        }
                    )
                try:
                    whole = trace.outcome(number, 100, 5800)
                    if whole["fuel_used_l"] <= 0:
                        raise ValueError("Invalid fuel use")
                    laps.append(
                        {
                            **identity,
                            "complete": True,
                            "quality_ok": quality,
                            "official_time_s": interval.duration_s,
                            **whole,
                            "fuel_at_100_m_l": sample(trace.fuel, whole["start_ts"]),
                            "note": "Driver errors unlocalized; exploratory"
                            if cohort == "first_attempt" and role != "push"
                            else "No major driver error reported",
                        }
                    )
                except ValueError as error:
                    laps.append(
                        {
                            **identity,
                            "complete": True,
                            "quality_ok": False,
                            "note": str(error),
                        }
                    )
                    continue
                anchors = trace.lap_anchors(number)
                for zone in zones:
                    metrics = trace.outcome(
                        number, zone["start_distance_m"], zone["end_distance_m"]
                    )
                    flags = impacts.filter(
                        (pl.col("ts") >= metrics["start_ts"])
                        & (pl.col("ts") < metrics["end_ts"])
                        & (pl.col("value") > 0)
                    )
                    passes.append(
                        {
                            **identity,
                            "zone_id": zone["zone_id"],
                            "display_label": zone["display_label"],
                            "quality_ok": quality,
                            "driver_review_pending": cohort == "first_attempt"
                            and role != "push",
                            "impact_event_count": flags.height,
                            "start_throttle_pct": sample(
                                fixed["Throttle Pos"], metrics["start_ts"]
                            ),
                            "start_driver_throttle_pct": sample(
                                fixed["Throttle Pos Unfiltered"], metrics["start_ts"]
                            ),
                            **metrics,
                        }
                    )
                    if role == "push":
                        continue
                    prediction = predictions.filter(
                        (pl.col("role") == role)
                        & (pl.col("zone_id") == zone["zone_id"])
                    ).to_dicts()[0]
                    planned_lift = (
                        zone["brake_reference_m"]
                        - prediction["selected_lico_distance_m"]
                    )
                    low = crossing_time(
                        anchors, max(zone["start_distance_m"], planned_lift - 100)
                    )
                    high = crossing_time(
                        anchors,
                        min(zone["end_distance_m"], zone["brake_reference_m"] + 100),
                    )
                    lift = sustained_onset(
                        fixed["Throttle Pos Unfiltered"], low, high, above=False
                    )
                    brake = sustained_onset(fixed["Brake Pos"], low, high, above=True)

                    def distance(ts):
                        return (
                            float(
                                np.interp(
                                    ts,
                                    anchors["ts"].to_numpy(),
                                    anchors["lap_distance_m"].to_numpy(),
                                )
                            )
                            if ts is not None
                            else None
                        )

                    lift_m, brake_m = distance(lift), distance(brake)
                    execution.append(
                        {
                            **identity,
                            "zone_id": zone["zone_id"],
                            "planned_lift_m": planned_lift,
                            "observed_lift_m": lift_m,
                            "observed_brake_m": brake_m,
                            "lift_error_m": lift_m - planned_lift
                            if lift_m is not None
                            else None,
                            "brake_shift_from_prior_push_m": brake_m
                            - zone["brake_reference_m"]
                            if brake_m is not None
                            else None,
                            "coast_before_brake_s": brake - lift
                            if lift is not None and brake is not None
                            else None,
                            "push_acceleration_at_planned_lift_mps2": prediction[
                                "push_acceleration_at_planned_lift_mps2"
                            ],
                        }
                    )
        if sha(path) != sources[str(path)]:
            raise ValueError(
                "Native file changed during analysis; stop recording and retry"
            )
    p = pl.DataFrame(passes)
    scores = contrasts(p).join(
        predictions.select(
            "role",
            "zone_id",
            "dose",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
        ),
        on=["role", "zone_id"],
    )
    summary = (
        scores.group_by("baseline", "cohort", "role", "zone_id")
        .agg(
            pl.first("display_label"),
            pl.len().alias("support"),
            pl.col("driver_review_pending").sum().alias("pending_review_count"),
            pl.first("baseline_impact_pass_count"),
            pl.col("start_driver_throttle_pct")
            .min()
            .alias("entry_driver_throttle_min_pct"),
            pl.col("start_throttle_pct").min().alias("entry_filtered_throttle_min_pct"),
            pl.col("fuel_saved_l").median(),
            pl.col("time_lost_s").median(),
            pl.col("time_lost_s").min().alias("time_min_s"),
            pl.col("time_lost_s").max().alias("time_max_s"),
            pl.col("exit_speed_delta_kph").median(),
            pl.first("predicted_fuel_saved_l"),
            pl.first("predicted_time_lost_s"),
        )
        .sort("baseline", "zone_id", "cohort", "role")
    )
    output.mkdir(parents=True)
    for name, frame in (
        ("zone_passes", p),
        ("zone_scores", scores),
        ("zone_summary", summary),
        ("lap_summary", pl.DataFrame(laps)),
        ("channel_quality", pl.DataFrame(channels)),
        ("cue_events", pl.DataFrame(cues)),
        ("execution", pl.DataFrame(execution)),
    ):
        frame.write_csv(output / f"{name}.csv")
    (output / "native_audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    result = {
        "source_hashes": sources,
        "status": "exploratory_no_refit",
        "lap_counts": pl.DataFrame(laps)
        .filter(pl.col("complete"))
        .group_by("cohort", "role")
        .len()
        .to_dicts(),
        "limits": [
            "First-attempt unlocalized driving errors remain flagged, not silently discarded or certified clean.",
            "Prior-push baseline is prospective; first-attempt push baseline is a sensitivity check, not interchangeable.",
            "Shared references and sequential laps are not independent samples. No causal fuel-mass correction or significance claim.",
            "Frozen windows retained; T3/T15 include silent downstream turns, T17 carryover beyond finish is not scored.",
            "No training or retrospective split selection; original first-attempt laps 2/3 calibration and 5/6 test roles remain historical.",
        ],
    }
    result["artifact_hashes"] = {
        x.name: sha(x) for x in output.iterdir() if x.is_file()
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=BASE / "combined_lico_analysis_final"
    )
    print(json.dumps(build(parser.parse_args().output), indent=2))
