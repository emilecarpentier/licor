"""Read-only reconciliation of the Oct 1 race. No fitting or live decisions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from licor.ingestion import LmuTelemetryDatabase

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = (
    ROOT / "data/processed/experimental/native_race_capture/race_20261002_011124_945002"
)
EARLY = (
    ROOT / "data/processed/experimental/native_race_capture/race_20261002_010905_769963"
)
DATABASE = Path(
    "C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry/Bahrain International Circuit_R_2026-10-02T01_11_27Z.duckdb"
)
HUD = ROOT / "docs/evidence/bahrain_race_hud_2026-10-01.json"
OUTPUT = ROOT / "data/processed/experimental/bahrain_race_audit_2026-10-01"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit():
    rows = [
        json.loads(line)
        for line in (CAPTURE / "samples.jsonl").read_text().splitlines()
    ]
    manifest = json.loads((CAPTURE / "manifest.json").read_text())
    annotations = json.loads(HUD.read_text())
    assert len(rows) == manifest["samples"] == manifest["matched_samples"]
    assert {r["track"] for r in rows} == {"Bahrain International Circuit"}
    assert {r["session"] for r in rows} == {10}
    assert {r["player"]["vehicle_id"] for r in rows} == {0}
    assert all(r["status"] == "matched" for r in rows)
    green = next(r for r in rows if r["game_phase"] == 5 and r["in_realtime"])
    leader_finish = next(r for r in rows if r["leader"]["finish_status"] == 1)
    finish = next(r for r in rows if r["player"]["finish_status"] == 1)
    zero = next(
        r
        for r in rows
        if r["game_phase"] in (5, 8) and r["session_time_remaining_s"] <= 0
    )
    active = [
        r
        for r in rows
        if r["in_realtime"]
        and r["game_phase"] in (3, 5, 8)
        and r["capture_elapsed_s"] <= finish["capture_elapsed_s"]
    ]
    assert all(
        b["player"]["completed_laps"] >= a["player"]["completed_laps"]
        for a, b in zip(active, active[1:])
    )
    with LmuTelemetryDatabase(DATABASE, read_only=True) as db:
        metadata = db.metadata()
        assert metadata["TrackName"] == rows[0]["track"]
        assert metadata["CarClass"] == "LMP2_ELMS"
        fuel = db.fixed_channel("Fuel Level")
        laps = db.event_series("Lap").to_dicts()
        finish_events = db.event_series("Finish Status").to_dicts()
        impacts = db.event_series("LastImpactMagnitude").to_dicts()
        pit_events = db.event_series("In Pits").to_dicts()
        table_counts = {
            name: db.connection.execute(
                'SELECT count(*) FROM "' + name.replace('"', '""') + '"'
            ).fetchone()[0]
            for name in db.table_names()
        }
    ts = fuel["ts"].to_numpy()
    litres = fuel["value"].to_numpy()
    assert np.isfinite(litres).all() and (litres >= 0).all()
    assert np.all(np.diff(ts) > 0)
    assert not any(r["value"] for r in pit_events)
    native_finish = next(r["ts"] for r in finish_events if r["value"] == 1)
    assert abs(native_finish - finish["player"]["lap_start_s"]) < 0.05
    comparisons = []
    for r in active:
        t = r["player"]["telemetry_elapsed_s"]
        if ts[0] <= t <= ts[-1]:
            native = float(np.interp(t, ts, litres))
            comparisons.append(abs(r["player"]["fuel_l"] - native))
    boundaries = []
    for event in laps:
        if event["value"] <= 0:
            continue
        n = int(event["value"])
        sample = next(r for r in active if r["player"]["completed_laps"] == n)
        boundaries.append(
            {
                "race_lap_completed": n,
                "native_ts": event["ts"],
                "fuel_l": float(np.interp(event["ts"], ts, litres)),
                "capture_fuel_l": sample["player"]["fuel_l"],
                "capture_detection_lag_s": sample["player"]["telemetry_elapsed_s"]
                - event["ts"],
                "finish_status": sample["player"]["finish_status"],
            }
        )
    # First race lap starts at rolling green, NOT the beginning of native Lap0.
    start = green["player"]["lap_start_s"]
    previous_fuel = float(np.interp(start, ts, litres))
    for boundary in boundaries:
        boundary["lap_duration_s"] = boundary["native_ts"] - start
        boundary["fuel_used_l"] = previous_fuel - boundary["fuel_l"]
        boundary["impact_boolean_events"] = sum(
            bool(event["value"]) and start <= event["ts"] < boundary["native_ts"]
            for event in impacts
        )
        boundary["model_ready"] = False
        start = boundary["native_ts"]
        previous_fuel = boundary["fuel_l"]
    resets = [
        {
            "capture_elapsed_s": b["capture_elapsed_s"],
            "before_l": a["player"]["fuel_l"],
            "after_l": b["player"]["fuel_l"],
            "in_realtime": b["in_realtime"],
            "in_garage": b["player"]["in_garage"],
        }
        for a, b in zip(rows, rows[1:])
        if b["player"]["fuel_l"] - a["player"]["fuel_l"] > 0.1
    ]
    fuel_series = [
        {
            "race_elapsed_s": round(
                r["player"]["telemetry_elapsed_s"] - green["player"]["lap_start_s"], 3
            ),
            "fuel_l": r["player"]["fuel_l"],
            "completed_laps": r["player"]["completed_laps"],
            "phase": r["game_phase"],
            "remaining_time_s": r["session_time_remaining_s"],
            "finish_status": r["player"]["finish_status"],
        }
        for i, r in enumerate(active)
        if i % 25 == 0
    ]
    early_rows = sum(1 for _ in (EARLY / "samples.jsonl").open())
    result = {
        "sources": {
            str(p): {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in (
                DATABASE,
                CAPTURE / "samples.jsonl",
                CAPTURE / "manifest.json",
                HUD,
            )
        },
        "race_date_local": "2026-10-01",
        "timezone": "America/Toronto",
        "classification": "diagnostic_only_no_model_training",
        "capture_samples": len(rows),
        "capture_duration_s": manifest["elapsed_s"],
        "capture_stop": manifest["reason"],
        "maximum_sample_gap_s": max(
            b["capture_elapsed_s"] - a["capture_elapsed_s"]
            for a, b in zip(rows, rows[1:])
        ),
        "repeated_native_clocks": sum(
            r["same_native_clocks_as_previous"] for r in rows
        ),
        "phase_counts": dict(Counter(r["game_phase"] for r in rows)),
        "early_capture": {
            "rows": early_rows,
            "manifest": json.loads((EARLY / "manifest.json").read_text()),
            "used": False,
            "reason": "unfinalized earlier start; separate from completed race",
        },
        "db_tables": len(table_counts),
        "db_rows": sum(table_counts.values()),
        "native_finish_ts": native_finish,
        "final_completed_laps": boundaries[-1]["race_lap_completed"],
        "green_lap_start_s": green["player"]["lap_start_s"],
        "formation_fuel_l": float(
            litres[0] - np.interp(green["player"]["lap_start_s"], ts, litres)
        ),
        "fuel_at_finish_l": boundaries[-1]["fuel_l"],
        "race_fuel_l": sum(b["fuel_used_l"] for b in boundaries),
        "clock_expired_capture_s": zero["capture_elapsed_s"],
        "leader_finish_capture_s": leader_finish["capture_elapsed_s"],
        "player_finish_capture_s": finish["capture_elapsed_s"],
        "finish_after_leader_s": finish["capture_elapsed_s"]
        - leader_finish["capture_elapsed_s"],
        "finish_after_clock_zero_s": finish["capture_elapsed_s"]
        - zero["capture_elapsed_s"],
        "fuel_reconciliation": {
            "pairs": len(comparisons),
            "median_abs_difference_l": float(np.median(comparisons)),
            "max_abs_difference_l": max(comparisons),
        },
        "resets": resets,
        "boundaries": boundaries,
        "fuel_series": fuel_series,
        "hud_annotations": annotations,
        "validation": "Read-only source reconciliation; no ML leakage because no model fitting or performance claim. Future finish is used only as retrospective truth, never a causal horizon input.",
    }
    return result


def main():
    result = audit()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "audit.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("sources", "fuel_series", "hud_annotations")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
