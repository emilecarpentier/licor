import json

import pytest

from licor.reports import (
    add_cumulative_distance,
    load_geojson_track_points,
    lonlat_to_local_xy,
    scale_lap_distance,
)


def test_converts_lonlat_to_local_xy_and_distances():
    points = lonlat_to_local_xy(
        [
            [0.0, 0.0],
            [0.001, 0.0],
            [0.001, 0.001],
        ]
    )
    with_distances = add_cumulative_distance(points)

    assert with_distances["lap_distance_m"][0] == 0.0
    assert with_distances["lap_distance_m"][-1] > 200.0


def test_scales_lap_distance_to_target_length():
    points = add_cumulative_distance(
        lonlat_to_local_xy(
            [
                [0.0, 0.0],
                [0.001, 0.0],
            ]
        )
    )

    scaled = scale_lap_distance(points, target_length_m=7000.0)

    assert scaled["lap_distance_m"][-1] == pytest.approx(7000.0)


def test_loads_geojson_linestring_track_points(tmp_path):
    path = tmp_path / "track.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Synthetic"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [0.001, 0.0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    points = load_geojson_track_points(path, target_length_m=1000.0)

    assert points.columns == ["lon", "lat", "x_m", "y_m", "lap_distance_m"]
    assert points["lap_distance_m"].to_list() == [0.0, 1000.0]
