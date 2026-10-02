from copy import deepcopy
import json

import pytest

from licor.analysis.race_context import replay_race_context
from licor.analysis.fuel_budget_replay import FuelBoundary, FuelPlan, replay_fuel_budget
from scripts.replay_native_race_context import build


def samples():
    """Constant 10 s laps; timer expires at 55 s, both cars finish at 60 s."""
    return [
        {
            "capture_elapsed_s": t / 5,
            "scoring_elapsed_s": t / 5,
            "track": "synthetic",
            "session": 10,
            "status": "matched",
            "game_phase": 5,
            "in_realtime": True,
            "session_time_remaining_s": max(0, 55 - t / 5),
            "hud_total_laps": None,
            "hud_fuel_laps": None,
            "player": {
                "vehicle_id": 2,
                "completed_laps": t // 50,
                "fuel_l": 55 - t / 100,
                "finish_status": int(t == 300),
                "in_pits": False,
                "in_garage": False,
            },
            "leader": {
                "vehicle_id": 1,
                "completed_laps": t // 50,
                "finish_status": int(t == 300),
            },
        }
        for t in range(301)
    ]


def test_forecast_is_point_only_and_never_hud_or_fuel_authority():
    rows = replay_race_context(samples())
    boundaries = [r for r in rows if r["observed_player_boundary"]]
    assert [r["licor_nominal_remaining_laps"] for r in boundaries] == [
        None,
        4,
        3,
        2,
        1,
        0,
    ]
    assert all(r["hud_total_laps"] is None for r in rows)
    assert all(r["upper_remaining_laps"] is None for r in rows[:-1])
    assert all(not r["fuel_plan_authorized"] for r in rows)
    assert rows[-1]["state"] == "player_finished"
    assert rows[-1]["upper_remaining_laps"] == 0
    assert rows[100]["leader_switch"]["projected_total_leader_laps"] == 6
    assert rows[-1]["leader_switch"] is None


def test_unbounded_diagnostic_forecast_cannot_authorize_existing_fuel_budget():
    row = replay_race_context(samples())[100]
    event = FuelBoundary(
        timestamp_s=row["scoring_elapsed_s"],
        context_id=str(row["context_id"]),
        completed_laps=row["completed_laps"],
        fuel_l=row["fuel_l"],
        nominal_remaining_laps=row["licor_nominal_remaining_laps"],
        upper_remaining_laps=row["upper_remaining_laps"],
    )
    result = replay_fuel_budget(
        [event],
        [FuelPlan("synthetic_push", 0, 0, True)],
        baseline_push_l=3,
        reserve_l=0.2,
        initial_error_allowance_l=0.05,
        error_window_laps=3,
        horizon_release_confirmations=3,
    )[0]
    assert result["status"] == "abstain_missing_boundary_inputs"
    assert result["selected_plan_id"] is None


@pytest.mark.parametrize("cut", [1, 50, 100, 125, 200, 250, 290])
def test_prefix_invariance_no_future_data_leakage(cut):
    source = samples()
    original = deepcopy(source)
    assert replay_race_context(source[:cut]) == replay_race_context(source)[:cut]
    assert source == original


def test_clock_leader_and_session_over_do_not_finish_player():
    source = samples()
    source[280]["leader"]["finish_status"] = 1
    source[280]["game_phase"] = 8
    source[281]["game_phase"] = 8
    rows = replay_race_context(source)
    assert rows[275]["state"] == "clock_expired"
    assert rows[280]["state"] == "leader_finished"
    assert rows[281]["state"] == "session_over_unconfirmed_player"
    assert all(r["licor_nominal_remaining_laps"] != 0 for r in rows[:-1])


@pytest.mark.parametrize(
    "state,changes,player_changes",
    [
        ("formation", {"game_phase": 3}, {}),
        ("paused", {"in_realtime": False}, {}),
        ("caution", {"game_phase": 6}, {}),
        ("stopped", {"game_phase": 7}, {}),
        ("pit", {}, {"in_pits": True}),
        ("garage", {}, {"in_garage": True, "fuel_l": 55}),
        ("retired", {}, {"finish_status": 2}),
        ("retired", {}, {"finish_status": 3}),
        ("not_race", {"session": 8}, {}),
        ("unavailable", {"status": "player_id_mismatch"}, {}),
        ("unavailable", {"scoring_elapsed_s": None}, {}),
        ("unavailable", {}, {"vehicle_id": None}),
    ],
)
def test_non_racing_states_clear_history(state, changes, player_changes):
    source = samples()
    source[199].update(changes)
    source[199]["player"].update(player_changes)
    rows = replay_race_context(source)
    assert rows[199]["state"] == state
    assert rows[200]["context_id"] > rows[198]["context_id"]
    assert rows[200]["licor_nominal_remaining_laps"] is None
    assert rows[200]["player_past_lap_s"] is None


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("fuel_l", 60, "fuel_increase"),
        ("vehicle_id", 99, "identity_changed"),
        ("completed_laps", 0, "native_clock_or_lap_rollback"),
        ("completed_laps", 10, "skipped_player_lap"),
    ],
)
def test_discontinuity_clears_history(field, value, reason):
    source = samples()
    source[200]["player"][field] = value
    row = replay_race_context(source)[200]
    assert row["context_reset_reason"] == reason
    assert row["licor_nominal_remaining_laps"] is None


def test_recording_gap_and_native_clock_rollback():
    source = samples()
    row = replay_race_context(source[:199] + source[205:])[199]
    assert row["context_reset_reason"] == "recording_gap"
    source[200]["scoring_elapsed_s"] = 0
    assert (
        replay_race_context(source)[200]["context_reset_reason"]
        == "native_clock_or_lap_rollback"
    )


def test_leader_change_clears_only_leader_history():
    source = samples()
    for row in source[199:]:
        row["leader"]["vehicle_id"] = 99
    row = replay_race_context(source)[200]
    assert row["player_past_lap_s"] == 10
    assert row["leader_past_lap_s"] is None
    assert row["licor_nominal_remaining_laps"] is None


def test_raw_hud_is_preserved_without_conversion():
    source = samples()
    source[200]["hud_total_laps"] = 5.9
    source[200]["hud_fuel_laps"] = 10.1
    row = replay_race_context(source)[200]
    assert row["hud_total_laps"] == 5.9
    assert row["hud_fuel_laps"] == 10.1
    assert row["licor_nominal_remaining_laps"] == 2


def test_frozen_scoring_clock_invalidates_history_until_native_progress():
    source = samples()
    for row in source[190:201]:
        row["scoring_elapsed_s"] = source[189]["scoring_elapsed_s"]
    rows = replay_race_context(source)
    assert rows[200]["state"] == "stale_scoring"
    assert rows[200]["licor_nominal_remaining_laps"] is None
    assert rows[201]["context_reset_reason"] == "active_context_start"
    assert rows[201]["player_past_lap_s"] is None


def test_overdue_leader_crossing_abstains_instead_of_projecting_missed_laps():
    source = samples()
    for row in source[101:]:
        row["leader"]["completed_laps"] = 2
    rows = replay_race_context(source)
    assert rows[200]["horizon_status"] == "abstain_overdue_leader_crossing"
    assert rows[250]["licor_nominal_remaining_laps"] is None


def test_counter_advance_with_no_native_time_progress_is_not_a_boundary():
    source = samples()
    source[200]["scoring_elapsed_s"] = source[199]["scoring_elapsed_s"]
    row = replay_race_context(source)[200]
    assert row["context_reset_reason"] == "counter_advance_without_clock_progress"
    assert not row["observed_player_boundary"]
    assert row["licor_nominal_remaining_laps"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0, True])
def test_invalid_capture_time_rejected(value):
    source = samples()
    source[1]["capture_elapsed_s"] = value
    with pytest.raises(ValueError, match="strictly increasing"):
        replay_race_context(source)


def test_script_preserves_input_and_refuses_output_overwrite(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in samples()), encoding="utf-8")
    before = path.read_bytes()
    output = tmp_path / "replay"
    result = build(path, output)
    assert path.read_bytes() == before
    assert result["samples"] == 301
    assert result["hud_total_laps_present"] == 0
    assert json.loads((output / "manifest.json").read_text()) == result
    with pytest.raises(FileExistsError):
        build(path, output)
