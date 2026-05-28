from __future__ import annotations

from pathlib import Path

import polars as pl

from licor.reports.experimental_zone_dynamics_driver_review_report import (
    render_experimental_zone_dynamics_driver_review_html,
    write_experimental_zone_dynamics_driver_review_report_html,
)


def _sample_zone_dynamics() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t01", "spa_t01"],
            "display_label": ["T01", "T01", "T01"],
            "run_id": ["run_a", "run_b", "run_c"],
            "lap_number": [1, 2, 3],
            "lico_intensity": ["low", "medium", "high"],
            "lico_distance_before_brake_m": [40.0, 60.0, 80.0],
            "fuel_saved_vs_baseline_l": [0.01, 0.02, 0.03],
            "time_lost_vs_baseline_s": [0.02, 0.03, 0.05],
            "brake_start_delta_vs_baseline_m": [2.0, 4.0, 6.0],
            "apex_speed_delta_vs_baseline_kph": [0.1, 0.3, 0.5],
            "exit_speed_delta_vs_baseline_kph": [0.0, 0.1, 0.2],
        }
    )


def _sample_driver_review() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_id": ["spa_t01"],
            "display_label": ["T01"],
            "pass_count": [3],
            "min_lico_distance_before_brake_m": [40.0],
            "max_lico_distance_before_brake_m": [80.0],
            "mean_fuel_saved_vs_baseline_l": [0.02],
            "mean_time_lost_vs_baseline_s": [0.033],
            "mean_brake_start_delta_vs_baseline_m": [4.0],
            "mean_apex_speed_delta_vs_baseline_kph": [0.3],
            "mean_exit_speed_delta_vs_baseline_kph": [0.1],
            "mean_carcass_temp_zone_start_delta_vs_baseline_c": [-2.5],
            "current_model_status": ["diagnostic_only"],
            "current_quality_flags": ["time_signal_unclear"],
            "r2_improvement": [0.18],
            "primary_review_label": ["entry_compensation_successful"],
            "secondary_review_label": ["dynamics_matter_materially"],
            "driver_summary": ["T01: more LICO clearly lowers arrival speed and moves braking later."],
            "pilot_takeaway": ["Coherent zone: judge it mostly by where apex and exit stay stable."],
        }
    )


def test_render_driver_review_html_contains_zone_summary() -> None:
    html = render_experimental_zone_dynamics_driver_review_html(
        _sample_zone_dynamics(),
        _sample_driver_review(),
    )

    assert "T01" in html
    assert "entry compensation successful" in html
    assert "Pilot takeaway" in html


def test_write_driver_review_html(tmp_path: Path) -> None:
    output_path = write_experimental_zone_dynamics_driver_review_report_html(
        _sample_zone_dynamics(),
        _sample_driver_review(),
        tmp_path / "driver_review.html",
    )

    html = output_path.read_text(encoding="utf-8")
    assert output_path.exists()
    assert "dynamics_matter_materially" not in html
    assert "dynamics matter materially" in html
