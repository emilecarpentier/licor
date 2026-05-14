import polars as pl

from licor.reports import (
    build_track_validation_points,
    create_zone_validation_figure,
    interpolate_track_position,
    zone_markers_from_proposals,
)


def test_builds_xy_track_points_when_coordinates_are_available():
    samples = pl.DataFrame(
        {
            "lap_distance_m": [0.0, 100.0, 200.0],
            "world_x_m": [0.0, 1.0, 2.0],
            "world_y_m": [0.0, 1.0, 0.0],
        }
    )

    points, projection = build_track_validation_points(
        samples,
        x_column="world_x_m",
        y_column="world_y_m",
    )

    assert projection == "xy"
    assert points.select("lap_distance_m", "x_m", "y_m").rows() == [
        (0.0, 0.0, 0.0),
        (100.0, 1.0, 1.0),
        (200.0, 2.0, 0.0),
    ]


def test_builds_distance_strip_without_coordinates():
    samples = pl.DataFrame(
        {
            "lap_distance_m": [0.0, 100.0, 200.0],
            "path_lateral_m": [0.0, -1.0, 1.0],
        }
    )

    points, projection = build_track_validation_points(samples)

    assert projection == "distance_strip"
    assert points.select("x_m", "y_m").rows() == [
        (0.0, 0.0),
        (100.0, -1.0),
        (200.0, 1.0),
    ]


def test_interpolates_markers_and_creates_plotly_figure():
    track_points = pl.DataFrame(
        {
            "lap_distance_m": [0.0, 100.0, 200.0],
            "x_m": [0.0, 10.0, 20.0],
            "y_m": [0.0, 0.0, 10.0],
        }
    )
    proposals = pl.DataFrame(
        [
            {
                "zone_id": "synthetic_t01",
                "display_label": "T01",
                "proposed_lico_window_start_m": 50.0,
                "proposed_brake_reference_m": 150.0,
                "push_brake_reference_median_m": 160.0,
            }
        ]
    )

    assert interpolate_track_position(track_points, 150.0) == {"x_m": 15.0, "y_m": 5.0}

    markers = zone_markers_from_proposals(track_points, proposals)
    figure = create_zone_validation_figure(
        track_points,
        markers,
        projection="xy",
        title="Synthetic validation",
    )

    assert markers.select("marker_type", "x_m", "y_m").rows() == [
        ("zone_start", 5.0, 0.0),
        ("brake_reference", 15.0, 5.0),
        ("none_median_brake", 16.0, 6.0),
    ]
    assert len(figure.data) == 4
    assert figure.layout.title.text == "Synthetic validation"


def test_applies_map_distance_offset_with_wraparound():
    track_points = pl.DataFrame(
        {
            "lap_distance_m": [0.0, 100.0, 200.0],
            "x_m": [0.0, 10.0, 20.0],
            "y_m": [0.0, 0.0, 0.0],
        }
    )
    proposals = pl.DataFrame(
        [
            {
                "zone_id": "synthetic_t01",
                "display_label": "T01",
                "proposed_brake_reference_m": 190.0,
            }
        ]
    )

    markers = zone_markers_from_proposals(
        track_points,
        proposals,
        map_distance_offset_m=30.0,
    )

    row = markers.row(0, named=True)
    assert row["lap_distance_m"] == 190.0
    assert row["map_distance_m"] == 20.0
    assert row["x_m"] == 2.0
