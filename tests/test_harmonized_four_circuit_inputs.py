import importlib.util
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "harmonized_inputs",
    Path(__file__).resolve().parents[1]
    / "scripts/build_harmonized_four_circuit_inputs.py",
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def fixtures():
    rows = pl.DataFrame(
        [
            {
                "observation_id": "a",
                "circuit_id": "sebring",
                "zone_id": "t1",
                "action": 0.4,
                "planned_action": 0.3,
                "acceleration": 9.0,
                "fuel_saved_l": 0.03,
                "time_lost_s": 0.1,
            },
            {
                "observation_id": "b",
                "circuit_id": "bahrain",
                "zone_id": "t2",
                "action": 0.5,
                "planned_action": None,
                "acceleration": 8.0,
                "fuel_saved_l": 0.04,
                "time_lost_s": 0.2,
            },
        ]
    )
    events = pl.DataFrame(
        [
            {
                "run_id": builder.PUSH_RUN,
                "lap_number": lap,
                "zone_id": "t1",
                "braking_event_quality": "ready",
                **{
                    c: ratio + lap
                    for c, ratio in zip(builder.PROFILE_COLUMNS, builder.RATIOS)
                },
            }
            for lap in (8, 9, 10)
        ]
    )
    return rows, events


def test_harmonization_preserves_identities_targets_and_historical_values():
    rows, events = fixtures()
    result, profiles = builder.harmonize(rows, events)
    preserved = [c for c in rows.columns if c != "acceleration"]
    assert result.select(preserved).equals(rows.select(preserved))
    assert result["acceleration"].to_list() == pytest.approx([9.4, 8.0])
    assert result["acceleration_previous"].to_list() == [9.0, 8.0]
    assert result["acceleration_planned_harmonized"][0] == pytest.approx(9.3)
    assert result["acceleration_planned_harmonized"][1] is None
    assert profiles["support"].to_list() == [3] * 5


@pytest.mark.parametrize(
    "mode", ["missing", "unsupported", "nonfinite", "duplicate", "wrong_lap"]
)
def test_bad_push_profiles_rejected(mode):
    rows, events = fixtures()
    if mode == "missing":
        events = events.with_columns(pl.lit("other").alias("zone_id"))
    elif mode == "unsupported":
        events = events.head(2)
    elif mode == "nonfinite":
        events = events.with_columns(
            pl.lit(float("nan")).alias(builder.PROFILE_COLUMNS[0])
        )
    elif mode == "duplicate":
        events = pl.concat([events, events.head(1)])
    else:
        events = events.with_columns(pl.lit(1).alias("lap_number"))
    with pytest.raises(ValueError):
        builder.harmonize(rows, events)


@pytest.mark.parametrize(
    "column,value",
    [
        ("action", 1.6),
        ("action", float("nan")),
        ("planned_action", -1.0),
        ("acceleration", float("inf")),
    ],
)
def test_invalid_lookup_is_not_clipped(column, value):
    rows, events = fixtures()
    with pytest.raises(ValueError):
        builder.harmonize(rows.with_columns(pl.lit(value).alias(column)), events)


def test_duplicate_observation_rejected():
    rows, events = fixtures()
    with pytest.raises(ValueError, match="duplicate response"):
        builder.harmonize(pl.concat([rows, rows.head(1)]), events)


def test_frozen_hash_guard():
    path = Path(__file__)
    builder.verify_hash(path, builder.record(path)["sha256"])
    with pytest.raises(ValueError, match="frozen hash mismatch"):
        builder.verify_hash(path, "0" * 64)
