import polars as pl
import pytest

from licor.analysis import ZoneOptimizerConfig, optimize_zone_lico_plan


def test_selects_minimum_time_combination_that_meets_target():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.06, 0.05, 1.2),
            _model("a", "A", 100.0, 0.12, 0.30, 0.4),
            _model("b", "B", 0.0, 0.0, 0.0, None),
            _model("b", "B", 40.0, 0.06, 0.07, 0.86),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.11),
    )

    assert set(plan["plan_status"].to_list()) == {"target_met"}
    selected = plan.filter(pl.col("is_selected_for_lico")).sort("zone_id")
    assert selected["zone_id"].to_list() == ["a", "b"]
    assert selected["total_predicted_fuel_saved_l"].to_list()[0] == pytest.approx(0.12)
    assert selected["total_optimization_time_lost_s"].to_list()[0] == pytest.approx(0.12)


def test_filters_nonzero_candidates_without_usable_ratio_by_default():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.06, 0.04, None),
            _model("a", "A", 100.0, 0.08, 0.10, 0.8),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.05),
    )

    selected = plan.filter(pl.col("is_selected_for_lico")).row(0, named=True)
    assert selected["selected_lico_distance_m"] == pytest.approx(100.0)
    assert selected["predicted_fuel_saved_l"] == pytest.approx(0.08)


def test_reports_unreachable_target_with_best_available_fuel():
    models = pl.DataFrame(
        [
            _model("a", "A", 0.0, 0.0, 0.0, None),
            _model("a", "A", 50.0, 0.06, 0.05, 1.2),
            _model("b", "B", 0.0, 0.0, 0.0, None),
            _model("b", "B", 40.0, 0.05, 0.07, 0.71),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.20),
    )

    assert set(plan["plan_status"].to_list()) == {"target_unreachable"}
    assert plan["total_predicted_fuel_saved_l"].to_list()[0] == pytest.approx(0.11)
    assert plan["fuel_surplus_l"].to_list()[0] == pytest.approx(-0.09)


def test_excludes_diagnostic_only_zones_by_default():
    models = pl.DataFrame(
        [
            _model("ready", "Ready", 0.0, 0.0, 0.0, None, status="model_ready"),
            _model("ready", "Ready", 50.0, 0.05, 0.10, 0.5, status="model_ready"),
            _model("diag", "Diagnostic", 0.0, 0.0, 0.0, None, status="diagnostic_only"),
            _model("diag", "Diagnostic", 50.0, 0.50, 0.10, 5.0, status="diagnostic_only"),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.40),
    )

    assert plan["zone_id"].to_list() == ["ready"]
    assert set(plan["plan_status"].to_list()) == {"target_unreachable"}


def test_strategy_prior_allows_diagnostic_without_changing_time_prediction():
    models = pl.DataFrame(
        [
            _model("ready", "Ready", 0.0, 0.0, 0.0, None, status="model_ready"),
            _model("ready", "Ready", 50.0, 0.05, 0.10, 0.5, status="model_ready"),
            _model("diag", "Diagnostic", 0.0, 0.0, 0.0, None, status="diagnostic_only"),
            _model("diag", "Diagnostic", 50.0, 0.06, 0.08, 0.75, status="diagnostic_only"),
        ]
    )
    priors = pl.DataFrame(
        [
            _prior("ready", 5, "preferred", False),
            _prior("diag", 4, "usable", True),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(
            target_fuel_saved_per_lap_l=0.06,
            allowed_model_statuses=("model_ready", "diagnostic_only"),
        ),
        zone_priors=priors,
    )

    selected = plan.filter(pl.col("zone_id") == "diag").row(0, named=True)
    assert selected["predicted_time_lost_s"] == pytest.approx(0.08)
    assert selected["optimization_time_lost_s"] == pytest.approx(0.08)
    assert selected["feasibility_score"] == 4
    assert selected["strategy_role"] == "usable"


def test_prior_rating_zero_excludes_even_favorable_candidate():
    models = pl.DataFrame(
        [
            _model("bad", "Bad", 0.0, 0.0, 0.0, None, status="model_ready"),
            _model("bad", "Bad", 50.0, 0.50, 0.10, 5.0, status="model_ready"),
            _model("ready", "Ready", 0.0, 0.0, 0.0, None, status="model_ready"),
            _model("ready", "Ready", 50.0, 0.05, 0.10, 0.5, status="model_ready"),
        ]
    )
    priors = pl.DataFrame(
        [
            _prior("bad", 0, "excluded", False),
            _prior("ready", 5, "preferred", False),
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.30),
        zone_priors=priors,
    )

    assert plan["zone_id"].to_list() == ["ready"]
    assert set(plan["plan_status"].to_list()) == {"target_unreachable"}


def test_strategy_prior_caps_lico_distance():
    models = pl.DataFrame(
        [
            _model("limited", "Limited", 0.0, 0.0, 0.0, None),
            _model("limited", "Limited", 40.0, 0.04, 0.08, 0.5),
            _model("limited", "Limited", 90.0, 0.10, 0.15, 0.67),
        ]
    )
    priors = pl.DataFrame(
        [
            {
                **_prior("limited", 2, "limited", False),
                "max_lico_distance_m": 50.0,
            },
        ]
    )

    plan = optimize_zone_lico_plan(
        models,
        config=ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.08),
        zone_priors=priors,
    )

    selected = plan.filter(pl.col("is_selected_for_lico")).row(0, named=True)
    assert selected["selected_lico_distance_m"] == pytest.approx(40.0)
    assert selected["plan_status"] == "target_unreachable"


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


def _prior(
    zone_id: str,
    feasibility_score: int,
    strategy_role: str,
    allow_diagnostic_model: bool,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": zone_id,
        "feasibility_score": feasibility_score,
        "strategy_role": strategy_role,
        "allow_diagnostic_model": allow_diagnostic_model,
        "max_lico_distance_m": None,
        "notes": "",
    }
