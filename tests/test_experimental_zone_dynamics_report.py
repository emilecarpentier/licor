from pathlib import Path

import polars as pl
import pytest

from licor.reports.experimental_zone_dynamics_report import (
    create_experimental_zone_dynamics_report_figure,
    write_experimental_zone_dynamics_report_html,
)


def test_creates_experimental_zone_dynamics_report_with_zone_facets_and_series():
    samples = pl.DataFrame(
        [
            _row("spa_t01", "T01", "none", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1),
            _row("spa_t01", "T01", "low", 70.0, 12.0, -2.5, -4.0, -1.5, 0.12, 3),
            _row("spa_t05_t06", "T05-T06", "none", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2),
            _row("spa_t05_t06", "T05-T06", "high", 125.0, 18.0, -4.0, -6.5, -3.0, 0.35, 5),
        ]
    )

    figure = create_experimental_zone_dynamics_report_figure(
        samples,
        title="Synthetic experimental dynamics",
    )

    assert figure.layout.title.text == "Synthetic experimental dynamics"
    assert len(figure.data) == 24
    assert len(figure.layout.annotations) == 12
    assert figure.layout.height == 560
    assert figure.layout.annotations[0].text == "T01 brake start delta"
    assert figure.layout.annotations[5].text == "T01 apex vs brake"
    assert figure.layout.xaxis.title.text == "LICO distance before brake (m)"
    assert figure.layout.xaxis6.title.text == "brake start delta vs baseline (m)"
    assert figure.layout.yaxis.title.text == "brake start delta vs baseline (m)"
    assert figure.layout.yaxis6.title.text == "apex speed delta vs baseline (km/h)"
    assert {trace.name for trace in figure.data} == {"none", "low", "high"}


def test_uses_min_speed_delta_alias_when_apex_column_is_absent():
    samples = pl.DataFrame(
        [
            _row(
                "spa_t01",
                "T01",
                "low",
                60.0,
                10.0,
                -1.8,
                -4.5,
                -1.2,
                0.09,
                3,
                apex_column="min_speed_delta_vs_baseline_kph",
            ),
            _row(
                "spa_t01",
                "T01",
                "low",
                90.0,
                16.0,
                -2.7,
                -3.0,
                -0.8,
                0.14,
                4,
                apex_column="min_speed_delta_vs_baseline_kph",
            ),
        ]
    )

    figure = create_experimental_zone_dynamics_report_figure(
        samples,
        title="Alias experimental dynamics",
    )

    assert len(figure.data) == 6
    assert list(figure.data[2].y) == [-4.5, -3.0]
    assert list(figure.data[5].y) == [-4.5, -3.0]
    assert figure.layout.annotations[2].text == "T01 apex speed delta"


def test_rejects_missing_required_dynamic_columns():
    with pytest.raises(
        ValueError,
        match="experimental zone dynamics samples missing required columns",
    ):
        create_experimental_zone_dynamics_report_figure(
            pl.DataFrame([{"zone_id": "spa_t01", "mean_lico_distance_m": 50.0}]),
            title="Bad samples",
        )


def test_writes_experimental_zone_dynamics_report_html(tmp_path: Path):
    figure = create_experimental_zone_dynamics_report_figure(
        pl.DataFrame(),
        title="Empty experimental dynamics",
    )

    path = write_experimental_zone_dynamics_report_html(
        figure,
        tmp_path / "experimental_zone_dynamics.html",
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<html>")


def _row(
    zone_id: str,
    display_label: str,
    intensity: str,
    lico_distance_m: float,
    brake_start_delta_m: float,
    brake_start_speed_delta_kph: float,
    apex_speed_delta_kph: float,
    exit_speed_delta_kph: float,
    time_lost_s: float,
    pass_count: int,
    *,
    apex_column: str = "apex_speed_delta_vs_baseline_kph",
) -> dict[str, object]:
    row = {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_intensity": intensity,
        "mean_lico_distance_m": lico_distance_m,
        "brake_start_delta_vs_baseline_m": brake_start_delta_m,
        "brake_start_speed_delta_vs_baseline_kph": brake_start_speed_delta_kph,
        "exit_speed_delta_vs_baseline_kph": exit_speed_delta_kph,
        "time_lost_vs_baseline_s": time_lost_s,
        "pass_count": pass_count,
        "quality_flags": ["synthetic_signal"],
    }
    row[apex_column] = apex_speed_delta_kph
    return row
