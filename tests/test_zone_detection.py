import polars as pl
import pytest

from licor.analysis import (
    BrakeZoneDetectionConfig,
    LicoZoneDetectionConfig,
    detect_brake_segments,
    detect_braking_zones,
    detect_lift_and_coast_zones,
)


def test_keeps_separate_brake_presses_as_separate_zones():
    samples = _synthetic_lap_samples(
        brake_windows=[(2.0, 3.0), (4.0, 4.5), (8.0, 9.0)],
        lico_profile=[],
    )
    config = BrakeZoneDetectionConfig(
        brake_threshold_pct=5.0,
        min_brake_duration_s=0.5,
    )

    raw_segments = detect_brake_segments(samples, config=config)
    braking_zones = detect_braking_zones(samples, config=config)

    assert raw_segments.height == 3
    assert braking_zones.height == 3

    first_bus_stop_press = braking_zones.row(0, named=True)
    assert first_bus_stop_press["raw_segment_count"] == 1
    assert first_bus_stop_press["start_lap_distance_m"] == pytest.approx(200.0)
    assert first_bus_stop_press["end_lap_distance_m"] == pytest.approx(300.0)

    second_bus_stop_press = braking_zones.row(1, named=True)
    assert second_bus_stop_press["raw_segment_count"] == 1
    assert second_bus_stop_press["start_lap_distance_m"] == pytest.approx(400.0)


def test_merges_only_tiny_brake_chatter():
    samples = _synthetic_lap_samples(
        brake_windows=[(2.0, 3.0), (3.2, 3.8), (8.0, 9.0)],
        lico_profile=[],
        sample_interval_s=0.1,
    )
    config = BrakeZoneDetectionConfig(
        brake_threshold_pct=5.0,
        min_brake_duration_s=0.5,
        max_merge_gap_s=0.25,
        max_merge_gap_m=25.0,
    )

    braking_zones = detect_braking_zones(samples, config=config)

    assert braking_zones.height == 2
    merged_zone = braking_zones.row(0, named=True)
    assert merged_zone["raw_segment_count"] == 2
    assert merged_zone["start_lap_distance_m"] == pytest.approx(200.0)
    assert merged_zone["end_lap_distance_m"] == pytest.approx(380.0)


def test_detects_lift_and_coast_before_brake_zone():
    samples = _synthetic_lap_samples(
        brake_windows=[(10.0, 11.0), (14.0, 15.0)],
        lico_profile=[
            (8.0, 8.0, 95.0),
            (8.5, 9.5, 0.0),
        ],
    )
    braking_zones = detect_braking_zones(
        samples,
        config=BrakeZoneDetectionConfig(
            brake_threshold_pct=5.0,
            min_brake_duration_s=0.5,
            max_merge_gap_s=0.5,
            max_merge_gap_m=50.0,
        ),
    )

    lico_zones = detect_lift_and_coast_zones(
        samples,
        braking_zones,
        config=LicoZoneDetectionConfig(
            lift_start_throttle_pct=99.0,
            zero_input_throttle_pct=1.0,
            min_lift_duration_s=0.5,
            min_lift_distance_m=50.0,
            min_zero_input_duration_s=0.5,
            max_lookback_s=4.0,
            max_lookback_distance_m=300.0,
            max_lift_to_brake_gap_s=0.75,
        ),
    )

    assert lico_zones.height == 2

    detected = lico_zones.row(0, named=True)
    assert detected["has_lico"] is True
    assert detected["validity_label"] == "detected"
    assert detected["brake_start_m"] == pytest.approx(1000.0)
    assert detected["lico_start_m"] == pytest.approx(800.0)
    assert detected["lico_end_m"] == pytest.approx(950.0)
    assert detected["lico_start_distance_before_brake_m"] == pytest.approx(200.0)
    assert detected["lico_duration_s"] == pytest.approx(1.5)
    assert detected["lico_distance_m"] == pytest.approx(150.0)
    assert detected["minimum_throttle_pct_before_brake"] == pytest.approx(0.0)
    assert detected["average_throttle_pct_before_brake"] == pytest.approx(23.75)
    assert detected["throttle_release_rate_pct_per_s"] == pytest.approx(200.0)

    not_detected = lico_zones.row(1, named=True)
    assert not_detected["has_lico"] is False
    assert not_detected["validity_label"] == "not_detected"


def test_requires_zero_input_period_for_lico():
    samples = _synthetic_lap_samples(
        brake_windows=[(10.0, 11.0)],
        lico_profile=[(8.5, 9.5, 50.0)],
    )
    braking_zones = detect_braking_zones(
        samples,
        config=BrakeZoneDetectionConfig(
            brake_threshold_pct=5.0,
            min_brake_duration_s=0.5,
        ),
    )

    lico_zones = detect_lift_and_coast_zones(
        samples,
        braking_zones,
        config=LicoZoneDetectionConfig(
            lift_start_throttle_pct=99.0,
            zero_input_throttle_pct=1.0,
            min_lift_duration_s=0.5,
            min_lift_distance_m=50.0,
            min_zero_input_duration_s=0.5,
        ),
    )

    assert lico_zones.row(0, named=True)["has_lico"] is False


def _synthetic_lap_samples(
    *,
    brake_windows: list[tuple[float, float]],
    lico_profile: list[tuple[float, float, float]],
    sample_interval_s: float = 0.5,
) -> pl.DataFrame:
    rows = []
    sample_count = int(16.0 / sample_interval_s) + 1
    for index in range(sample_count):
        ts = round(index * sample_interval_s, 10)
        brake_pct = 70.0 if _in_any_window(ts, brake_windows) else 0.0
        throttle_pct = _throttle_at(ts, lico_profile)
        rows.append(
            {
                "lap_number": 1,
                "lap_start_ts": 0.0,
                "lap_end_ts": 16.0,
                "ts": ts,
                "lap_elapsed_s": ts,
                "lap_distance_m": ts * 100.0,
                "brake_pct": brake_pct,
                "throttle_pct": throttle_pct,
                "ground_speed_kph": 260.0 - ts * 3.0,
            }
        )
    return pl.DataFrame(rows)


def _in_any_window(value: float, windows: list[tuple[float, float]]) -> bool:
    return any(start <= value <= end for start, end in windows)


def _throttle_at(value: float, profile: list[tuple[float, float, float]]) -> float:
    for start, end, throttle_pct in profile:
        if start <= value <= end:
            return throttle_pct
    return 100.0
