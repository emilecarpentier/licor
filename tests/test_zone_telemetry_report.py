import polars as pl

from licor.analysis import TrackZoneDefinition
from licor.reports import (
    build_zone_telemetry_window,
    create_zone_telemetry_report_figure,
)


def test_builds_zone_telemetry_window_around_zone():
    samples = _samples()
    zone = _zone()

    window = build_zone_telemetry_window(
        samples,
        zone,
        before_start_m=50.0,
        after_end_m=25.0,
    )

    assert window["lap_distance_m"].min() == 50.0
    assert window["lap_distance_m"].max() == 325.0
    assert window.select("run_id", "lap_number").unique().height == 2


def test_creates_zone_telemetry_report_with_references_and_lico_markers():
    zone = _zone()
    window = build_zone_telemetry_window(_samples(), zone)
    zone_passes = pl.DataFrame(
        [
            _zone_pass("run_none", 1, "none", False, None),
            _zone_pass("run_low", 2, "low", True, 150.0),
        ]
    )

    figure = create_zone_telemetry_report_figure(
        window,
        zone_passes,
        zone,
        title="Synthetic T01 telemetry",
    )

    assert figure.layout.title.text == "Synthetic T01 telemetry"
    assert len(figure.data) == 7
    assert len(figure.layout.shapes) == 9
    assert {trace.name for trace in figure.data} == {
        "none lap",
        "low lap",
        "detected LICO start",
    }
    assert figure.data[-1].x == (150.0,)


def test_creates_empty_zone_telemetry_report():
    figure = create_zone_telemetry_report_figure(
        pl.DataFrame(),
        pl.DataFrame(),
        _zone(),
        title="Empty telemetry",
    )

    assert figure.layout.title.text == "Empty telemetry"
    assert len(figure.data) == 0


def _zone() -> TrackZoneDefinition:
    return TrackZoneDefinition(
        zone_id="synthetic_t01",
        turn_numbers=(1,),
        display_label="T01",
        start_distance_m=100.0,
        lico_window_start_m=100.0,
        brake_reference_m=220.0,
        end_distance_m=300.0,
        lico_eligible=True,
        optimization_role="candidate",
        validation_end_rule="manual_distance",
        review_status="driver_reviewed",
    )


def _samples() -> pl.DataFrame:
    rows = []
    for run_id, lap_number in (("run_none", 1), ("run_low", 2)):
        for index, distance_m in enumerate(range(0, 401, 25)):
            rows.append(
                {
                    "run_id": run_id,
                    "lap_number": lap_number,
                    "lap_start_ts": 0.0,
                    "lap_end_ts": 10.0,
                    "ts": float(index),
                    "lap_elapsed_s": float(index),
                    "lap_distance_m": float(distance_m),
                    "brake_pct": 60.0 if 220 <= distance_m <= 260 else 0.0,
                    "throttle_pct": 0.0 if run_id == "run_low" and 150 <= distance_m < 220 else 100.0,
                    "ground_speed_kph": 260.0 - distance_m / 10.0,
                    "fuel_level_l": 50.0 - distance_m / 2000.0,
                }
            )
    return pl.DataFrame(rows)


def _zone_pass(
    run_id: str,
    lap_number: int,
    intensity: str,
    has_lico: bool,
    lico_start_m: float | None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "lap_number": lap_number,
        "zone_id": "synthetic_t01",
        "display_label": "T01",
        "lico_intensity": intensity,
        "has_lico": has_lico,
        "lico_start_m": lico_start_m,
        "validity_label": "valid",
    }
