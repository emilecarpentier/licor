import polars as pl
import pytest

from licor.analysis import (
    TrackZoneDefinition,
    TrackZoneTable,
    ZonePassConfig,
    extract_zone_passes,
)


def test_extracts_push_and_lico_zone_pass_metrics():
    samples = pl.concat(
        [
            _synthetic_lap_samples(lap_number=1, has_lico=False),
            _synthetic_lap_samples(lap_number=2, has_lico=True),
        ]
    )
    table = _zone_table()

    passes = extract_zone_passes(
        samples,
        table,
        config=ZonePassConfig(max_boundary_gap_m=10.0),
    )

    assert passes.height == 2
    assert passes.select("lap_number", "zone_id", "validity_label").rows() == [
        (1, "synthetic_t01", "valid"),
        (2, "synthetic_t01", "valid"),
    ]

    push = passes.filter(pl.col("lap_number") == 1).row(0, named=True)
    assert push["has_lico"] is False
    assert push["fuel_used_l"] == pytest.approx(0.2)
    assert push["elapsed_time_s"] == pytest.approx(6.0)
    assert push["brake_start_m"] == pytest.approx(250.0)
    assert push["brake_start_speed_kph"] == pytest.approx(230.0)
    assert push["min_speed_kph"] == pytest.approx(200.0)
    assert push["exit_speed_kph"] == pytest.approx(200.0)

    lico = passes.filter(pl.col("lap_number") == 2).row(0, named=True)
    assert lico["has_lico"] is True
    assert lico["lico_start_m"] == pytest.approx(170.0)
    assert lico["lico_end_m"] == pytest.approx(240.0)
    assert lico["lico_start_distance_before_brake_m"] == pytest.approx(80.0)
    assert lico["lico_duration_s"] == pytest.approx(1.4)
    assert lico["lico_distance_m"] == pytest.approx(70.0)
    assert lico["minimum_throttle_pct_before_brake"] == pytest.approx(0.0)
    assert lico["average_throttle_pct_before_brake"] == pytest.approx(29.0)
    assert lico["throttle_release_rate_pct_per_s"] == pytest.approx(500.0)


def test_skips_incomplete_and_non_candidate_zones_by_default():
    table = TrackZoneTable(
        track_name="Synthetic Spa",
        car_class="LMP2_TEST",
        zones=[
            _candidate_zone(),
            TrackZoneDefinition(
                zone_id="synthetic_t19",
                turn_numbers=(19,),
                display_label="T19",
                start_distance_m=500.0,
                lico_window_start_m=None,
                brake_reference_m=540.0,
                end_distance_m=620.0,
                lico_eligible=False,
                optimization_role="validation_only",
                validation_end_rule="manual_distance",
                review_status="driver_reviewed",
            ),
            TrackZoneDefinition(
                zone_id="incomplete",
                turn_numbers=(20,),
                display_label="T20",
                start_distance_m=None,
                brake_reference_m=None,
                end_distance_m=None,
                lico_eligible=False,
                optimization_role="validation_only",
                review_status="needs_driver_review",
            ),
        ],
    )

    passes = extract_zone_passes(_synthetic_lap_samples(lap_number=1, has_lico=False), table)

    assert passes.height == 1
    assert passes["zone_id"].to_list() == ["synthetic_t01"]


def test_marks_zone_pass_with_missing_boundary_coverage():
    samples = _synthetic_lap_samples(lap_number=1, has_lico=False).filter(
        pl.col("lap_distance_m") <= 370.0
    )

    passes = extract_zone_passes(
        samples,
        _zone_table(),
        config=ZonePassConfig(max_boundary_gap_m=10.0),
    )

    assert passes.height == 1
    assert passes.row(0, named=True)["validity_label"] == "incomplete_zone_coverage"


def _zone_table() -> TrackZoneTable:
    return TrackZoneTable(
        track_name="Synthetic Spa",
        car_class="LMP2_TEST",
        zones=[_candidate_zone()],
    )


def _candidate_zone() -> TrackZoneDefinition:
    return TrackZoneDefinition(
        zone_id="synthetic_t01",
        turn_numbers=(1,),
        display_label="T01",
        start_distance_m=100.0,
        lico_window_start_m=150.0,
        brake_reference_m=250.0,
        end_distance_m=400.0,
        lico_eligible=True,
        optimization_role="candidate",
        validation_end_rule="manual_distance",
        review_status="driver_reviewed",
    )


def _synthetic_lap_samples(*, lap_number: int, has_lico: bool) -> pl.DataFrame:
    rows = []
    lap_start_ts = (lap_number - 1) * 100.0
    for index, distance_m in enumerate(range(0, 501, 10)):
        lap_elapsed_s = index * 0.2
        rows.append(
            {
                "lap_number": lap_number,
                "lap_start_ts": lap_start_ts,
                "lap_end_ts": lap_start_ts + 10.0,
                "ts": lap_start_ts + lap_elapsed_s,
                "lap_elapsed_s": lap_elapsed_s,
                "lap_distance_m": float(distance_m),
                "brake_pct": 70.0 if 250.0 <= distance_m <= 310.0 else 0.0,
                "throttle_pct": _throttle_at(distance_m, has_lico),
                "ground_speed_kph": 260.0 - (distance_m - 100.0) / 5.0,
                "fuel_level_l": 80.0 - lap_number - distance_m / 1500.0,
            }
        )
    return pl.DataFrame(rows)


def _throttle_at(distance_m: int, has_lico: bool) -> float:
    if not has_lico:
        return 100.0
    if distance_m == 170:
        return 90.0
    if 180 <= distance_m <= 240:
        return 0.0
    return 100.0
