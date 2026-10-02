"""Read-only native race diagnostics, deliberately separate from live cues."""

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path


def _name(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def extract_race_snapshot(layout) -> dict[str, object]:
    """Preserve native units and match telemetry/scoring by vehicle ID."""
    scoring = layout.data.scoring
    info = scoring.scoring_info
    telemetry = layout.data.telemetry
    row = {
        "track": _name(info.track_name),
        "session": int(info.session),
        "game_phase": int(info.game_phase),
        "in_realtime": bool(info.in_realtime),
        "scoring_elapsed_s": float(info.current_et),
        "session_end_s": float(info.end_et),
        "session_time_remaining_s": float(info.session_time_remaining),
        "max_laps_raw": int(info.max_laps),
        "hud_total_laps": None,
        "hud_fuel_laps": None,
        "player": None,
        "leader": None,
        "status": "player_unavailable",
    }
    count = int(info.num_vehicles)
    if not 0 <= count <= len(scoring.veh_scoring_info):
        row["status"] = "invalid_scoring_count"
        return row
    vehicles = list(scoring.veh_scoring_info[:count])
    leaders = [vehicle for vehicle in vehicles if vehicle.place == 1]
    if len(leaders) == 1:
        leader = leaders[0]
        row["leader"] = {
            "vehicle_id": int(leader.vehicle_id),
            "completed_laps": int(leader.total_laps),
            "lap_distance_m": float(leader.lap_dist),
            "last_lap_s": float(leader.last_lap_time),
            "finish_status": int(leader.finish_status),
        }
    idx = int(telemetry.player_vehicle_idx)
    active = int(telemetry.active_vehicles)
    if not telemetry.player_has_vehicle or not 0 <= idx < active <= len(
        telemetry.telem_info
    ):
        return row
    player = telemetry.telem_info[idx]
    matches = [
        vehicle for vehicle in vehicles if vehicle.vehicle_id == player.vehicle_id
    ]
    if len(matches) != 1 or not matches[0].is_player:
        row["status"] = "player_id_mismatch"
        return row
    vehicle = matches[0]
    row["player"] = {
        "vehicle_id": int(player.vehicle_id),
        "vehicle_name": _name(vehicle.vehicle_name),
        "vehicle_class": _name(vehicle.vehicle_class),
        "telemetry_elapsed_s": float(player.elapsed_time),
        "current_lap": int(player.lap_number),
        "completed_laps": int(vehicle.total_laps),
        "lap_distance_m": float(vehicle.lap_dist),
        "fuel_l": float(player.fuel),
        "last_lap_s": float(vehicle.last_lap_time),
        "lap_start_s": float(vehicle.lap_start_et),
        "finish_status": int(vehicle.finish_status),
        "place": int(vehicle.place),
        "laps_behind_leader": int(vehicle.laps_behind_leader),
        "time_behind_leader_s": float(vehicle.time_behind_leader),
        "in_pits": bool(vehicle.in_pits),
        "in_garage": bool(vehicle.in_garage_stall),
        "count_lap_flag": int(vehicle.count_lap_flag),
    }
    row["status"] = "matched"
    return row


def _finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    return value


def capture(
    reader,
    output_dir: Path,
    duration_s: float,
    *,
    clock=time.monotonic,
    sleep=time.sleep,
    wall_clock=time.time,
) -> dict[str, object]:
    """Poll at 5 Hz, flush each row, and finalize even after Ctrl+C/errors.

    Repeated native clocks are retained, not labeled fresh observations.
    No automatic finish inference: raw status flags require in-game validation.
    """
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("duration_s must be finite and positive")
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        "schema_version": 1,
        "mode": "read_only_no_cues",
        "duration_limit_s": duration_s,
        "samples": 0,
        "matched_samples": 0,
        "reason": "running",
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    start = clock()
    previous_key = None
    with (output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    try:
        with (output_dir / "samples.jsonl").open("x", encoding="utf-8") as stream:
            while clock() - start < duration_s:
                row = reader.read_race_snapshot()
                player = row.get("player") or {}
                key = (
                    row.get("track"),
                    row.get("session"),
                    row.get("scoring_elapsed_s"),
                    player.get("vehicle_id"),
                    player.get("telemetry_elapsed_s"),
                )
                row["same_native_clocks_as_previous"] = key == previous_key
                previous_key = key
                row["wall_time_utc"] = datetime.fromtimestamp(
                    wall_clock(), timezone.utc
                ).isoformat()
                row["capture_elapsed_s"] = clock() - start
                stream.write(json.dumps(_finite_json(row), allow_nan=False) + "\n")
                stream.flush()
                summary["samples"] += 1
                summary["matched_samples"] += row.get("status") == "matched"
                sleep(min(0.2, max(0, duration_s - (clock() - start))))
        summary["reason"] = "duration_limit"
    except KeyboardInterrupt:
        summary["reason"] = "interrupted_saved"
    except Exception as exc:
        summary["reason"] = "error"
        summary["error"] = str(exc)
        raise
    finally:
        summary["elapsed_s"] = clock() - start
        with (output_dir / "manifest.json").open("w", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="LMU native race capture: read-only, no beeps."
    )
    parser.add_argument("--duration-minutes", type=float, default=30)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[3]
        / "data/processed/experimental/native_race_capture",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration_minutes) or args.duration_minutes <= 0:
        parser.error("--duration-minutes must be finite and positive")
    from licor.live.lmu_shared_memory import LMUSharedMemoryReader

    destination = args.output_root / datetime.now(timezone.utc).strftime(
        "race_%Y%m%d_%H%M%S_%f"
    )
    print(f"Capture READ ONLY / NO BEEPS: {destination}", flush=True)
    print(
        "Stop: Ctrl+C saves files. Automatic stop at duration limit, NOT at finish flag.",
        flush=True,
    )
    try:
        reader = LMUSharedMemoryReader()
        try:
            summary = capture(reader, destination, args.duration_minutes * 60)
        finally:
            reader.close()
    except Exception as exc:
        print(
            f"Capture failed: {exc}. Start LMU with shared memory enabled; inspect saved files."
        )
        return 1
    print(json.dumps(summary, indent=2), flush=True)
    print(f"CAPTURE SAVED: {destination}", flush=True)
    return 0 if summary["matched_samples"] else 2
