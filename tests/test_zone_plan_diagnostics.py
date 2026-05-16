import polars as pl
import pytest

from licor.analysis.zone_optimizer import ZoneOptimizerConfig
from licor.analysis.zone_plan_diagnostics import (
    ZonePlanSensitivityScenario,
    build_zone_marginal_efficiency,
    summarize_zone_plan_sensitivity,
)


def test_builds_marginal_efficiency_segments_and_marks_selected_segment():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.05, 0.10, 0.50),
            _model("a", "A", 100.0, 0.08, 0.40, 0.20),
        ]
    )
    plan = pl.DataFrame([_plan("a", "A", 100.0)])

    marginal = build_zone_marginal_efficiency(models, zone_plan=plan)

    assert marginal.height == 2
    first = marginal.filter(pl.col("to_lico_distance_m") == 50.0).row(0, named=True)
    assert first["incremental_fuel_saved_l"] == pytest.approx(0.05)
    assert first["incremental_time_lost_s"] == pytest.approx(0.10)
    assert first["marginal_fuel_saved_per_second_lps"] == pytest.approx(0.50)
    assert first["best_cumulative_ratio_distance_m"] == pytest.approx(50.0)
    assert not first["is_after_best_cumulative_ratio_distance"]

    second = marginal.filter(pl.col("to_lico_distance_m") == 100.0).row(0, named=True)
    assert second["marginal_fuel_saved_per_second_lps"] == pytest.approx(0.10)
    assert second["is_after_best_cumulative_ratio_distance"]
    assert second["contains_selected_plan_point"]


def test_suppresses_marginal_ratio_when_incremental_time_is_too_small():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 40.0, 0.02, 0.01, None),
        ]
    )

    marginal = build_zone_marginal_efficiency(models)

    row = marginal.row(0, named=True)
    assert row["marginal_fuel_saved_per_second_lps"] is None
    assert row["marginal_flags"] == "low_incremental_time_ratio_suppressed"


def test_summarizes_optimizer_sensitivity_with_best_ratio_cap():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.05, 0.10, 0.50),
            _model("a", "A", 100.0, 0.09, 0.40, 0.225),
            _model("b", "B", 0.0, 0.0, 0.0, None),
            _model("b", "B", 50.0, 0.04, 0.10, 0.40),
        ]
    )

    sensitivity = summarize_zone_plan_sensitivity(
        models,
        base_config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.10),
        scenarios=[
            ZonePlanSensitivityScenario(name="base"),
            ZonePlanSensitivityScenario(name="best_ratio_caps", best_ratio_cap=True),
        ],
    )

    base = sensitivity.filter(pl.col("scenario_name") == "base").row(0, named=True)
    capped = sensitivity.filter(pl.col("scenario_name") == "best_ratio_caps").row(0, named=True)

    assert base["plan_status"] == "target_met"
    assert base["selected_zone_distances"] == "a=100.000|b=50.000"
    assert capped["plan_status"] == "target_unreachable"
    assert capped["total_predicted_fuel_saved_l"] == pytest.approx(0.09)
    assert capped["fuel_surplus_l"] == pytest.approx(-0.01)
    assert capped["best_ratio_cap_applied"]


def test_summarizes_fuel_margin_scenario_target():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.08, 0.10, 0.80),
            _model("a", "A", 80.0, 0.10, 0.20, 0.50),
        ]
    )

    sensitivity = summarize_zone_plan_sensitivity(
        models,
        base_config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.08),
        scenarios=[
            ZonePlanSensitivityScenario(name="base"),
            ZonePlanSensitivityScenario(name="margin", target_fuel_margin_l=0.02),
        ],
    )

    margin = sensitivity.filter(pl.col("scenario_name") == "margin").row(0, named=True)
    assert margin["target_fuel_saved_per_lap_l"] == pytest.approx(0.10)
    assert margin["selected_zone_distances"] == "a=80.000"


def _model(
    zone_id: str,
    display_label: str,
    distance_m: float,
    fuel_saved_l: float,
    time_lost_s: float,
    ratio_lps: float | None,
    *,
    status: str = "model_ready",
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_distance_m": distance_m,
        "predicted_fuel_saved_l": fuel_saved_l,
        "predicted_time_lost_s": time_lost_s,
        "predicted_fuel_saved_per_second_lps": ratio_lps,
        "is_extrapolated": False,
        "model_status": status,
        "quality_flags": ["synthetic"],
        "source_bin_count": 3,
        "nonzero_source_bin_count": 2,
        "observed_max_lico_distance_m": 100.0,
    }


def _plan(zone_id: str, display_label: str, distance_m: float) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "selected_lico_distance_m": distance_m,
        "is_selected_for_lico": distance_m > 0.0,
        "predicted_fuel_saved_l": 0.08,
        "predicted_time_lost_s": 0.40,
        "optimization_time_lost_s": 0.40,
        "model_status": "model_ready",
        "quality_flags": "synthetic",
        "feasibility_score": None,
        "strategy_role": "",
        "max_lico_distance_m": None,
        "strategy_prior_notes": "",
        "target_fuel_saved_per_lap_l": 0.08,
        "total_predicted_fuel_saved_l": 0.08,
        "total_predicted_time_lost_s": 0.40,
        "total_optimization_time_lost_s": 0.40,
        "fuel_surplus_l": 0.0,
        "plan_status": "target_met",
    }
