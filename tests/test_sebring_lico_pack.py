import importlib.util
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "sebring_lico_pack",
    Path(__file__).resolve().parents[1]
    / "scripts/build_sebring_lico_validation_pack.py",
)
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def _design_inputs():
    refs = pl.DataFrame(
        [
            {
                "zone_id": zone,
                "display_label": zone,
                "brake_reference_m": pack.OUTCOMES[zone][0] + 180,
                "deceleration_reference_m": 180.0,
                "deceleration_cv": 0.05,
                "arrival_speed_kph": 250.0,
            }
            for zone in pack.DOSES
        ]
    )
    grid = pl.DataFrame(
        [
            {
                "zone_id": zone,
                "lap_number": lap,
                "lead_m": lead,
                "driver_throttle_min_pct": 100.0,
                "brake_at_point_max_pct": 0.0,
                "acceleration_mps2": 2.0,
                "speed_kph": 250.0,
            }
            for zone in pack.DOSES
            for lap in pack.LAPS
            for lead in range(0, 501, 5)
        ]
    )
    model = {
        target: {
            "slope": 0.1,
            "shadow_action_slope": 0.1,
            "shadow_acceleration_slope": 0.01,
        }
        for target in ("fuel", "time")
    }
    return refs, grid, model


def test_staggered_doses_and_nonoverlapping_scoring_windows():
    predictions, table, capture = pack.design(*_design_inputs())
    assert predictions.height == 14
    for zone, distances in pack.DOSES.items():
        assert sorted(
            predictions.filter(pl.col("zone_id") == zone)["selected_lico_distance_m"]
        ) == list(distances)
    assert (
        predictions.filter((pl.col("role") == "A") & (pl.col("zone_id") == "sbr_t03"))[
            "dose"
        ][0]
        == "higher"
    )
    assert all(
        a["end_distance_m"] <= b["start_distance_m"]
        for a, b in zip(table["zones"], table["zones"][1:])
    )
    assert all(not row["future_large_lifts_authorized"] for row in capture)


def test_acceleration_guard_rejects_large_weighted_action():
    refs, grid, model = _design_inputs()
    grid = grid.with_columns(pl.lit(20.0).alias("acceleration_mps2"))
    with pytest.raises(ValueError, match="action guard failed"):
        pack.design(refs, grid, model)


def test_missing_candidate_acceleration_rejects():
    refs, grid, model = _design_inputs()
    grid = grid.with_columns(
        pl.when(pl.col("lap_number") == 8)
        .then(None)
        .otherwise(pl.col("acceleration_mps2"))
        .alias("acceleration_mps2")
    )
    with pytest.raises(ValueError, match="action guard failed"):
        pack.design(refs, grid, model)


def test_frozen_pack_not_overwritten(tmp_path):
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        pack.build_pack(tmp_path)


def test_end_to_end_synthetic_schedule(tmp_path):
    refs, grid, model = _design_inputs()
    predictions, _, _ = pack.design(refs, grid, model)
    plans = [
        pack.build_live_cue_plan(
            predictions.filter(pl.col("role") == role),
            refs,
            config=pack.LiveCuePlanConfig(
                plan_id=pack.plan_id(role),
                track_length_m=pack.TRACK_LENGTH,
                cue_latency_compensation_s=0.35,
            ),
        )
        for role in ("A", "B")
    ]
    path = tmp_path / "plan.csv"
    pl.concat(plans).write_csv(path)
    assert pack.preflight(path)["cue_count"] == 28
