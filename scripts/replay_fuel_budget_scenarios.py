"""Reproducible synthetic boundary tests, not telemetry-derived race validation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from licor.analysis.fuel_budget_replay import FuelBoundary, FuelPlan, replay_fuel_budget

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/experimental/fuel_budget_shadow_scenarios_v1"


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    config = dict(
        baseline_push_l=3.0,
        reserve_l=0.2,
        initial_error_allowance_l=0.05,
        error_window_laps=3,
        horizon_release_confirmations=3,
    )
    plans = [
        FuelPlan("push", 0, 0, True),
        FuelPlan("low", 0.2, 0.1, True),
        FuelPlan("high", 0.4, 0.3, True),
    ]
    first = FuelBoundary(
        0, "synthetic_race", 0, 27.5, 10, 10, hud_total_laps=57.8, hud_fuel_laps=10.1
    )
    scenarios = {
        "one_more_lap": [
            first,
            replace(
                first,
                timestamp_s=100,
                completed_laps=1,
                fuel_l=24.85,
                nominal_remaining_laps=10,
                upper_remaining_laps=11,
            ),
        ],
        "under_saving": [
            first,
            replace(
                first,
                timestamp_s=100,
                completed_laps=1,
                fuel_l=24.4,
                nominal_remaining_laps=9,
                upper_remaining_laps=9,
                previous_lap_usable=True,
                executed_plan_id="high",
            ),
        ],
        "unusable_lap_not_learned": [
            first,
            replace(
                first,
                timestamp_s=100,
                completed_laps=1,
                fuel_l=24.4,
                nominal_remaining_laps=9,
                upper_remaining_laps=9,
                previous_lap_usable=False,
                executed_plan_id="high",
            ),
        ],
        "missing_input": [
            first,
            replace(first, timestamp_s=100, completed_laps=1, fuel_l=None),
        ],
        "refuel_new_context": [
            first,
            replace(
                first,
                timestamp_s=100,
                context_id="synthetic_after_refuel",
                completed_laps=1,
                fuel_l=40,
            ),
        ],
        "finish": [
            first,
            replace(
                first,
                timestamp_s=1000,
                completed_laps=10,
                fuel_l=0.3,
                nominal_remaining_laps=0,
                upper_remaining_laps=0,
                race_finished=True,
            ),
        ],
        "lower_horizon_confirmed": [
            replace(
                first,
                timestamp_s=100 * i,
                completed_laps=i,
                fuel_l=40 - 3 * i,
                nominal_remaining_laps=(10 if i == 0 else 9 - i),
                upper_remaining_laps=(10 if i == 0 else 9 - i),
            )
            for i in range(4)
        ],
    }
    results = {
        name: replay_fuel_budget(events, plans, **config)
        for name, events in scenarios.items()
    }
    assert results["one_more_lap"][-1]["status"] == "target_unreachable"
    assert (
        results["under_saving"][-1]["error_allowance_l"]
        > config["initial_error_allowance_l"]
    )
    assert (
        results["unusable_lap_not_learned"][-1]["error_allowance_l"]
        == config["initial_error_allowance_l"]
    )
    assert results["missing_input"][-1]["selected_plan_id"] is None
    assert results["finish"][-1]["selected_plan_id"] is None
    assert results["lower_horizon_confirmed"][-1]["retained_upper_remaining_laps"] == 6

    def record(path):
        with path.open("rb") as handle:
            return {
                "path": str(path.resolve()),
                "sha256": hashlib.file_digest(handle, "sha256").hexdigest(),
            }

    output.mkdir(parents=True)
    payload = {
        "status": "synthetic_software_scenarios_not_empirical_validation",
        "config": config,
        "plans": [asdict(p) for p in plans],
        "inputs": {
            name: [asdict(e) for e in events] for name, events in scenarios.items()
        },
        "results": results,
    }
    destination = output / "scenarios.json"
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": payload["status"],
        "scenario_count": len(scenarios),
        "boundary_count": sum(map(len, scenarios.values())),
        "sources": [
            record(p)
            for p in (
                Path(__file__),
                ROOT / "src/licor/analysis/fuel_budget_replay.py",
                ROOT / "src/licor/analysis/fuel_budget.py",
            )
        ],
        "artifacts": [record(destination)],
        "limitations": [
            "HUD numbers are unconverted diagnostics; integer horizons are explicit synthetic inputs.",
            "0.2 L reserve and 0.05 L/lap allowance are fixture values, not driver-approved race settings.",
            "Rolling maxima are not calibrated probability bounds. No live output, no real-race arrival claim.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    print(json.dumps(build(parser.parse_args().output_dir), indent=2))
