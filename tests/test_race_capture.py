import json

import pytest

from licor.live.lmu_shared_memory import SharedMemoryLayout
from licor.live.race_capture import capture, extract_race_snapshot, main


def layout():
    result = SharedMemoryLayout()
    telemetry = result.data.telemetry
    telemetry.player_has_vehicle = True
    telemetry.active_vehicles = 2
    telemetry.player_vehicle_idx = 0
    telemetry.telem_info[0].vehicle_id = 42
    telemetry.telem_info[0].fuel = 55
    telemetry.telem_info[0].lap_number = 12
    scoring = result.data.scoring
    scoring.scoring_info.num_vehicles = 2
    scoring.veh_scoring_info[0].vehicle_id = 7
    scoring.veh_scoring_info[0].place = 1
    scoring.veh_scoring_info[0].finish_status = 1
    scoring.veh_scoring_info[1].vehicle_id = 42
    scoring.veh_scoring_info[1].is_player = True
    scoring.veh_scoring_info[1].total_laps = 11
    return result


def test_player_matched_by_id_not_array_index():
    row = extract_race_snapshot(layout())
    assert row["player"]["vehicle_id"] == 42
    assert row["player"]["fuel_l"] == 55
    assert row["player"]["completed_laps"] == 11
    assert row["player"]["current_lap"] == 12
    assert row["player"]["finish_status"] == 0
    assert row["leader"]["finish_status"] == 1
    assert row["hud_total_laps"] is None
    assert row["hud_fuel_laps"] is None


@pytest.mark.parametrize(
    "fault", ["duplicate", "missing", "not_player", "count", "index"]
)
def test_invalid_identity_abstains(fault):
    value = layout()
    if fault == "duplicate":
        value.data.scoring.veh_scoring_info[0].vehicle_id = 42
    elif fault == "missing":
        value.data.scoring.veh_scoring_info[1].vehicle_id = 43
    elif fault == "not_player":
        value.data.scoring.veh_scoring_info[1].is_player = False
    elif fault == "count":
        value.data.scoring.scoring_info.num_vehicles = 105
    else:
        value.data.telemetry.player_vehicle_idx = 2
    assert extract_race_snapshot(value)["player"] is None


class Reader:
    def __init__(self, fail=None):
        self.calls = 0
        self.fail = fail

    def read_race_snapshot(self):
        self.calls += 1
        if self.calls == 3 and self.fail:
            raise self.fail
        row = extract_race_snapshot(layout())
        row["player"]["fuel_l"] = float("nan")
        return row


def run_capture(tmp_path, reader):
    ticks = [0.0]

    def sleep(seconds):
        ticks[0] += seconds

    return capture(reader, tmp_path / "capture", 1, clock=lambda: ticks[0], sleep=sleep)


def test_capture_bounded_persists_raw_diagnostics(tmp_path):
    result = run_capture(tmp_path, Reader())
    assert result["reason"] == "duration_limit"
    rows = [
        json.loads(line)
        for line in (tmp_path / "capture/samples.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 5
    assert rows[1]["same_native_clocks_as_previous"]
    assert rows[0]["player"]["fuel_l"] is None
    with pytest.raises(FileExistsError):
        run_capture(tmp_path, Reader())


def test_ctrl_c_finalizes_partial_capture(tmp_path):
    assert (
        run_capture(tmp_path, Reader(KeyboardInterrupt()))["reason"]
        == "interrupted_saved"
    )
    manifest = json.loads((tmp_path / "capture/manifest.json").read_text())
    assert manifest["samples"] == 2


def test_error_finalizes_partial_capture(tmp_path):
    with pytest.raises(OSError):
        run_capture(tmp_path, Reader(OSError("disconnected")))
    manifest = json.loads((tmp_path / "capture/manifest.json").read_text())
    assert manifest["reason"] == "error"
    assert manifest["samples"] == 2


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf"])
def test_invalid_cli_duration(duration):
    with pytest.raises(SystemExit) as error:
        main([f"--duration-minutes={duration}"])
    assert error.value.code == 2
