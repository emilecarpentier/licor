import polars as pl
import pytest

from licor.analysis.fixed_distance import crossing_time, distance_anchors


def test_repeated_distance_does_not_compress_the_update_interval():
    samples = pl.DataFrame(
        {
            "ts": [0.0, 0.02, 0.04, 0.06, 0.08, 0.1, 0.12, 0.14, 0.16, 0.18, 0.2],
            "lap_distance_m": [100.0] * 10 + [120.0],
        }
    )
    assert crossing_time(distance_anchors(samples), 110.0) == pytest.approx(0.1)


def test_lap_reset_is_trimmed_and_unbracketed_distances_rejected():
    samples = pl.DataFrame(
        {"ts": [0.0, 0.1, 0.2, 0.3], "lap_distance_m": [5384.0, 4.0, 10.0, 20.0]}
    )
    anchors = distance_anchors(samples)
    assert crossing_time(anchors, 15.0) == pytest.approx(0.25)
    with pytest.raises(ValueError, match="does not bracket"):
        crossing_time(anchors, 0.0)
