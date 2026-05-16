from pathlib import Path

import polars as pl

from licor.reports import (
    create_zone_plan_report_figure,
    write_zone_plan_report_html,
)


def test_creates_zone_plan_report_with_model_curves_and_selected_markers():
    model = pl.DataFrame(
        [
            _model_row("spa_t05_t06", "T05-T06", 0.0, 0.0, 0.0, None),
            _model_row("spa_t05_t06", "T05-T06", 100.0, 0.05, 0.10, 0.5),
        ]
    )
    plan = pl.DataFrame(
        [
            _plan_row("spa_t05_t06", "T05-T06", 100.0, True, 0.05, 0.10),
        ]
    )

    figure = create_zone_plan_report_figure(model, plan, title="Synthetic plan")

    assert figure.layout.title.text == "Synthetic plan"
    assert len(figure.data) == 6
    assert "selected plan point" in {trace.name for trace in figure.data}


def test_creates_zone_plan_report_with_zero_lico_marker():
    model = pl.DataFrame(
        [
            _model_row("spa_t14", "T14", 0.0, 0.0, 0.0, None),
            _model_row("spa_t14", "T14", 40.0, 0.02, 0.20, 0.1),
        ]
    )
    plan = pl.DataFrame(
        [
            _plan_row("spa_t14", "T14", 0.0, False, 0.0, 0.0),
        ]
    )

    figure = create_zone_plan_report_figure(model, plan, title="Zero plan")

    assert "zero-LICO plan point" in {trace.name for trace in figure.data}


def test_writes_zone_plan_report_html(tmp_path: Path):
    figure = create_zone_plan_report_figure(pl.DataFrame(), pl.DataFrame(), title="Empty")

    path = write_zone_plan_report_html(figure, tmp_path / "plan.html")

    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<html>")


def _model_row(
    zone_id: str,
    display_label: str,
    distance_m: float,
    fuel_saved_l: float,
    time_lost_s: float,
    ratio_lps: float | None,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_distance_m": distance_m,
        "predicted_fuel_saved_l": fuel_saved_l,
        "predicted_time_lost_s": time_lost_s,
        "predicted_fuel_saved_per_second_lps": ratio_lps,
        "is_extrapolated": False,
        "model_status": "model_ready",
        "quality_flags": ["clean_signal"],
        "source_bin_count": 3,
        "nonzero_source_bin_count": 2,
        "observed_max_lico_distance_m": 100.0,
    }


def _plan_row(
    zone_id: str,
    display_label: str,
    distance_m: float,
    is_selected: bool,
    fuel_saved_l: float,
    time_lost_s: float,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "selected_lico_distance_m": distance_m,
        "is_selected_for_lico": is_selected,
        "predicted_fuel_saved_l": fuel_saved_l,
        "predicted_time_lost_s": time_lost_s,
        "optimization_time_lost_s": time_lost_s,
        "model_status": "model_ready",
        "quality_flags": "clean_signal",
        "feasibility_score": 5,
        "strategy_role": "preferred",
        "max_lico_distance_m": None,
        "strategy_prior_notes": "",
        "target_fuel_saved_per_lap_l": 0.05,
        "total_predicted_fuel_saved_l": fuel_saved_l,
        "total_predicted_time_lost_s": time_lost_s,
        "total_optimization_time_lost_s": time_lost_s,
        "fuel_surplus_l": 0.0,
        "plan_status": "target_met",
    }
