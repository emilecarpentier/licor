"""Audit fixed phases/carryover; create conservative response inputs, no live changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from licor.analysis.fixed_distance import (
    NativeDistanceTrace,
    crossing_time,
    distance_anchors,
)
from licor.ingestion import LmuTelemetryDatabase

from analyze_sebring_lico_sessions import BASE, NATIVE, PACK, ROOT, RUNS, sample, sha

ANALYSIS = BASE / "combined_lico_analysis_final"
OUTPUT = BASE / "phase_qualification_v1"
# Structural sensitivity, declared before this audit's numerical results.
# T1/T3 share carryover; T17 requires a cross-line outcome not in the frozen target.
COUPLED = {"sbr_t01", "sbr_t03", "sbr_t17"}


def quality_tier(cohort: str, zone_id: str, pedal: float, technical_ok: bool) -> str:
    return (
        "strict_retry"
        if cohort == "retry" and zone_id not in COUPLED and pedal >= 95 and technical_ok
        else "exploratory_only"
    )


def interpolate_acceleration(grid: pl.DataFrame, zone: str, lead: float) -> float:
    profile = (
        grid.filter(pl.col("zone_id") == zone)
        .group_by("lead_m")
        .agg(pl.col("acceleration_mps2").median())
        .sort("lead_m")
    )
    if not profile["lead_m"][0] <= lead <= profile["lead_m"][-1]:
        raise ValueError(
            "executed lift is outside push acceleration capture; no clipping"
        )
    return float(
        np.interp(
            lead, profile["lead_m"].to_numpy(), profile["acceleration_mps2"].to_numpy()
        )
    )


def after_line_time(
    trace: NativeDistanceTrace, lap: int, next_lap_start: float, endpoint: float
) -> float:
    """Use actual next-lap anchors; never extrapolate a stopped or absent next lap."""
    if lap + 1 in trace.intervals:
        return crossing_time(trace.lap_anchors(lap + 1), endpoint)
    # Partial final lap may still cover endpoint; trim beyond endpoint plus one update
    # before a later pit teleport, without using the previous lap's held distance.
    partial = trace.distance.filter(pl.col("ts") >= next_lap_start)
    values = partial["lap_distance_m"].to_numpy()
    resets = np.flatnonzero(np.diff(values) < -100)
    if len(resets) and resets[0] <= 2:
        partial = partial.slice(int(resets[0]) + 1)
    hit = np.flatnonzero(partial["lap_distance_m"].to_numpy() >= endpoint)
    if not len(hit):
        raise ValueError("partial next lap does not reach recovery endpoint")
    return crossing_time(distance_anchors(partial.head(int(hit[0]) + 1)), endpoint)


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing overwrite: {output}")
    prior_manifest = json.loads((ANALYSIS / "manifest.json").read_text())
    for name, digest in prior_manifest["artifact_hashes"].items():
        if sha(ANALYSIS / name) != digest:
            raise ValueError(f"Analysis artifact changed: {name}")
    scores = pl.read_csv(ANALYSIS / "zone_scores.csv").filter(
        pl.col("baseline") == "prior_push_5"
    )
    execution = pl.read_csv(ANALYSIS / "execution.csv")
    laps = pl.read_csv(ANALYSIS / "lap_summary.csv").filter(pl.col("complete"))
    zones = json.loads((PACK / "track_zones.json").read_text())["zones"]
    refs = pl.read_csv(PACK / "physical_references.csv")
    grid = pl.read_csv(PACK / "approach_grid.csv")
    plan = pl.read_csv(PACK / "plan.csv")
    sources = {
        str(p): sha(p)
        for p in (
            Path(__file__),
            ANALYSIS / "manifest.json",
            PACK / "physical_references.csv",
            PACK / "approach_grid.csv",
            PACK / "track_zones.json",
            PACK / "plan.csv",
        )
    }
    phases, recovery, boundaries = [], [], []
    for index, zone in enumerate(zones):
        next_zone = zones[(index + 1) % len(zones)]["zone_id"]
        next_cue = plan.filter(pl.col("zone_id") == next_zone)["cue_distance_m"].min()
        endpoint = (
            100.0
            if index == 6
            else min(zone["end_distance_m"] + 100.0, next_cue - 25.0)
        )
        boundaries.append(
            {
                "zone_id": zone["zone_id"],
                "frozen_end_m": zone["end_distance_m"],
                "diagnostic_end_m": endpoint,
                "next_lap": index == 6,
                "next_cue_m": next_cue,
            }
        )
    for run_id, suffix, cohort in RUNS:
        filename = f"Sebring International Raceway_P_2026-09-12T{suffix}Z.duckdb"
        path = ROOT / "data" / filename
        if not path.exists():
            path = NATIVE / filename
        if sha(path) != prior_manifest["source_hashes"][str(path)]:
            raise ValueError("Raw source changed since frozen analysis")
        sources[str(path)] = sha(path)
        with LmuTelemetryDatabase(path) as db:
            trace = NativeDistanceTrace.from_database(db)
            for row in laps.filter(pl.col("run_id") == run_id).iter_rows(named=True):
                lap = row["lap_number"]
                for zone, boundary in zip(zones, boundaries):
                    ref = refs.filter(pl.col("zone_id") == zone["zone_id"]).to_dicts()[
                        0
                    ]
                    cuts = [
                        zone["start_distance_m"],
                        ref["brake_reference_m"],
                        ref["minimum_point_m"],
                        zone["end_distance_m"],
                    ]
                    identity = {
                        "run_id": run_id,
                        "cohort": cohort,
                        "lap_number": lap,
                        "role": row["role"],
                        "zone_id": zone["zone_id"],
                    }
                    for phase, left, right in zip(
                        ("approach", "push_deceleration_interval", "exit"),
                        cuts,
                        cuts[1:],
                    ):
                        phases.append(
                            {
                                **identity,
                                "phase": phase,
                                "start_m": left,
                                "end_m": right,
                                **trace.outcome(lap, left, right),
                            }
                        )
                    frozen_end = crossing_time(
                        trace.lap_anchors(lap), zone["end_distance_m"]
                    )
                    try:
                        end = (
                            after_line_time(
                                trace,
                                lap,
                                trace.intervals[lap].end_ts,
                                boundary["diagnostic_end_m"],
                            )
                            if boundary["next_lap"]
                            else crossing_time(
                                trace.lap_anchors(lap), boundary["diagnostic_end_m"]
                            )
                        )
                        if end <= frozen_end:
                            raise ValueError("nonpositive recovery duration")
                        fuel_used = sample(trace.fuel, frozen_end) - sample(
                            trace.fuel, end
                        )
                        if fuel_used < 0:
                            raise ValueError("refuel inside recovery window")
                        recovery.append(
                            {
                                **identity,
                                **boundary,
                                "status": "covered",
                                "additional_time_s": end - frozen_end,
                                "additional_fuel_l": fuel_used,
                                "exit_speed_kph": sample(trace.speed, end),
                            }
                        )
                    except ValueError as error:
                        recovery.append(
                            {
                                **identity,
                                **boundary,
                                "status": str(error),
                                "additional_time_s": None,
                                "additional_fuel_l": None,
                                "exit_speed_kph": None,
                            }
                        )
        if sha(path) != sources[str(path)]:
            raise ValueError("Raw file changed while reading")
    phase_frame = pl.DataFrame(phases)
    push = (
        phase_frame.filter(pl.col("cohort") == "prior_push")
        .group_by("zone_id", "phase")
        .agg(
            pl.col("elapsed_time_s").median().alias("push_time_s"),
            pl.col("fuel_used_l").median().alias("push_fuel_l"),
        )
    )
    phase_scores = (
        phase_frame.filter(pl.col("role").is_in(["A", "B"]))
        .join(push, on=["zone_id", "phase"])
        .with_columns(
            (pl.col("elapsed_time_s") - pl.col("push_time_s")).alias("time_lost_s"),
            (pl.col("push_fuel_l") - pl.col("fuel_used_l")).alias("fuel_saved_l"),
        )
    )
    rec = pl.DataFrame(recovery)
    recpush = (
        rec.filter((pl.col("cohort") == "prior_push") & (pl.col("status") == "covered"))
        .group_by("zone_id")
        .agg(
            pl.len().alias("push_support"),
            pl.col("additional_time_s").median().alias("push_additional_time_s"),
            pl.col("additional_fuel_l").median().alias("push_additional_fuel_l"),
        )
    )
    recscores = (
        rec.filter(pl.col("role").is_in(["A", "B"]))
        .join(recpush, on="zone_id", how="left")
        .with_columns(
            (pl.col("additional_time_s") - pl.col("push_additional_time_s")).alias(
                "additional_time_lost_s"
            ),
            (pl.col("push_additional_fuel_l") - pl.col("additional_fuel_l")).alias(
                "additional_fuel_saved_l"
            ),
        )
    )
    response, annotations = [], []
    for row in scores.join(
        execution, on=["run_id", "lap_number", "zone_id"], suffix="_execution"
    ).iter_rows(named=True):
        ref = refs.filter(pl.col("zone_id") == row["zone_id"]).to_dicts()[0]
        lead = ref["brake_reference_m"] - row["observed_lift_m"]
        action = lead / ref["deceleration_reference_m"]
        tier = quality_tier(
            row["cohort"],
            row["zone_id"],
            row["start_driver_throttle_pct"],
            row["quality_ok"],
        )
        reasons = []
        if row["cohort"] == "first_attempt":
            reasons.append("unlocalized_driver_errors")
        if row["zone_id"] in COUPLED:
            reasons.append("structural_carryover_sensitivity")
        if row["start_driver_throttle_pct"] < 95:
            reasons.append("entry_driver_pedal_below_95")
        if row["start_throttle_pct"] < 1 and row["start_driver_throttle_pct"] >= 95:
            reasons.append("filtered_cut_not_driver_lift")
        annotations.append(
            {
                "run_id": row["run_id"],
                "lap_number": row["lap_number"],
                "zone_id": row["zone_id"],
                "quality_tier": tier,
                "reasons": "|".join(reasons),
                "is_driver_error_confirmation": False,
            }
        )
        response.append(
            {
                "observation_id": f"sebring::{row['run_id']}::{row['lap_number']}::{row['zone_id']}",
                "circuit_id": "sebring",
                "run_id": row["run_id"],
                "lap_number": row["lap_number"],
                "zone_id": row["zone_id"],
                "action": action,
                "acceleration": interpolate_acceleration(grid, row["zone_id"], lead),
                "fuel_saved_l": row["fuel_saved_l"],
                "time_lost_s": row["time_lost_s"],
                "planned_action": row["selected_lico_distance_m"]
                / ref["deceleration_reference_m"],
                "quality_tier": tier,
            }
        )
    output.mkdir(parents=True)
    for name, frame in (
        ("phase_outcomes", phase_frame),
        ("phase_scores", phase_scores),
        ("recovery_outcomes", rec),
        ("recovery_scores", recscores),
        ("qualified_response_rows", pl.DataFrame(response)),
        ("annotations", pl.DataFrame(annotations)),
    ):
        frame.write_csv(output / f"{name}.csv")
    result = {
        "status": "retrospective_qualification_not_clean_certification",
        "policy": "First-attempt errors unresolved; strict sensitivity uses retry uncoupled T7/T10/T13/T15 only. No target-value residual filter. Frozen original metrics unchanged.",
        "phase_definition": "Fixed prior push brake/minimum distances, not each LICO apex. Preserve physical isolated-event denominator.",
        "recovery_policy": "100m beyond frozen endpoint capped 25m before earliest next cue; T17 to nextlap100m. Diagnostics overlap frozen adjacent windows: never add them to full-lap totals.",
        "boundaries": boundaries,
        "counts": pl.DataFrame(response).group_by("quality_tier").len().to_dicts(),
        "sources": sources,
    }
    result["artifact_hashes"] = {
        p.name: sha(p) for p in output.iterdir() if p.is_file()
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    print(json.dumps(build(parser.parse_args().output), indent=2))
