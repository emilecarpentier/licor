import importlib.util
import json
import math
from pathlib import Path

import polars as pl
import pytest


SPEC = importlib.util.spec_from_file_location(
    "bahrain_lico_validation_pack",
    Path(__file__).resolve().parents[1]
    / "scripts/build_bahrain_lico_validation_pack.py",
)
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def _runtime_plan() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "schema_version": [1, 1],
            "plan_id": ["bahrain_validation", "bahrain_validation"],
            "zone_id": ["bahrain_t01", "bahrain_t04"],
            "display_label": ["T1", "T4"],
            "cue_distance_m": [450.0, 1260.0],
            "planned_lift_start_m": [475.0, 1285.0],
            "cue_tolerance_m": [5.0, 5.0],
            "notes": ["", ""],
        }
    )


def test_fixed_seven_lap_schedule_and_real_runtime_gate(tmp_path):
    schedule = pack.lap_schedule()

    assert [row["scored_index"] for row in schedule] == list(range(1, 8))
    assert [row["role"] for row in schedule] == [
        "push",
        "lico",
        "lico",
        "push",
        "lico",
        "lico",
        "push",
    ]
    assert [row["cue_enabled"] for row in schedule] == [
        False,
        True,
        True,
        False,
        True,
        True,
        False,
    ]

    plan_path = tmp_path / "plan.csv"
    _runtime_plan().write_csv(plan_path)
    result = pack.preflight_schedule(plan_path)

    assert result == {
        "scored_laps": 7,
        "cue_count": 4 * 2,
        "logged_crossings": 8 * 2,
    }


def test_builds_verifies_and_freezes_zero_shot_lineage(tmp_path):
    pack_dir = tmp_path / "pack"

    result = pack.build_pack(pack_dir)
    verified = pack.verify_pack(pack_dir)

    assert result["hashes_verified"]
    assert verified["hashes_verified"]
    assert result["silent_synthetic_preflight"] == [
        {
            "scored_laps": 7,
            "cue_count": 4 * pl.read_csv(pack_dir / "plan.csv").height,
            "logged_crossings": 8 * pl.read_csv(pack_dir / "plan.csv").height,
        }
    ]

    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    assert manifest["local_lico_outcomes_observed"] is False
    assert manifest["adaptive_mode"] == "offline_after_run_only"
    assert manifest["artifacts"]["plan.csv"] == pack.sha256_file(pack_dir / "plan.csv")
    assert manifest["artifacts"]["predictions.csv"] == pack.sha256_file(
        pack_dir / "predictions.csv"
    )

    plan = pl.read_csv(pack_dir / "plan.csv")
    predictions = pl.read_csv(pack_dir / "predictions.csv").filter(
        pl.col("is_selected_for_lico")
    )
    assert set(plan["zone_id"].to_list()) == set(predictions["zone_id"].to_list())

    joined = plan.join(predictions, on="zone_id", suffix="_prediction")
    assert joined.height == plan.height == predictions.height
    for row in joined.iter_rows(named=True):
        assert math.isclose(
            row["selected_lico_distance_m"],
            row["selected_lico_distance_m_prediction"],
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        assert math.isclose(
            row["expected_fuel_saved_l"],
            row["predicted_fuel_saved_l"],
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        assert math.isclose(
            row["expected_time_lost_s"],
            row["predicted_time_lost_s"],
            rel_tol=1e-9,
            abs_tol=1e-9,
        )


def test_verify_rejects_modified_frozen_artifact(tmp_path):
    pack_dir = tmp_path / "pack"
    pack.build_pack(pack_dir)
    with (pack_dir / "plan.csv").open("a", encoding="utf-8") as file:
        file.write("\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        pack.verify_pack(pack_dir)


def test_build_refuses_to_replace_frozen_pack(tmp_path):
    pack_dir = tmp_path / "pack"
    pack.build_pack(pack_dir)

    with pytest.raises(FileExistsError, match="refusing to replace"):
        pack.build_pack(pack_dir)


def test_launchers_force_audible_beeps_and_bypass_execution_policy():
    powershell = pack._powershell_launcher(pack.DEFAULT_PACK_DIR)
    command = pack._cmd_launcher()

    assert "[switch]$ConfirmTelemetryRecording" in powershell
    assert "Telemetry confirmation missing" in powershell
    assert "scripts/run_lmu_live_cues.py --show-current-lap" in powershell
    assert "--emit-system-beep" in powershell
    assert "$EmitSystemBeep" not in powershell
    assert "Linked LMU telemetry" in powershell
    assert "-ExecutionPolicy Bypass" in command
    assert '"%~dp0start_lico_validation.ps1" %*' in command
