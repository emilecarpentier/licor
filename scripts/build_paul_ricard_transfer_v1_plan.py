from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl

from licor.analysis.race_strategy import (
    RaceStrategyConfig,
    build_fuel_saving_targets,
    compare_push_and_lico_strategy,
    estimated_race_laps,
)
from licor.analysis.strategy_priors import load_strategy_prior_table
from licor.analysis.zone_curves import ZoneCurveConfig, build_zone_curve_points, summarize_zone_curve_bins
from licor.analysis.zone_models import ZoneModelConfig, build_zone_piecewise_models
from licor.analysis.zone_optimizer import ZoneOptimizerConfig, optimize_zone_lico_plan
from licor.analysis.zone_plan_diagnostics import (
    build_zone_marginal_efficiency,
    summarize_zone_plan_sensitivity,
)
from licor.reports.zone_plan_report import (
    create_zone_plan_report_figure,
    write_zone_plan_report_html,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/processed/experimental/paul_ricard_transfer_v1"
ZONE_PASSES_FILE = OUTPUT_DIR / "paul_ricard_all_reviewed_zone_passes_modeling.csv"
BASELINE_SUMMARY_FILE = OUTPUT_DIR / "paul_ricard_baseline_push_lap_summary.csv"
STRATEGY_PRIOR_FILE = PROJECT_ROOT / "config/track_zones/paul_ricard_lmp2_strategy_priors.bootstrap.json"
PIT_STOP_OBSERVATION_FILE = PROJECT_ROOT / "data/processed/spa_lmp2_pit_stop_observations.csv"

TRACK_NAME = "Circuit Paul Ricard"
CAR_CLASS = "LMP2_ELMS"
STARTER_TARGET_FUEL_SAVED_PER_LAP_L = 0.05
TARGET_SWEEP_L = (0.03, 0.05, 0.06, 0.08, 0.10, 0.12)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    zone_passes = pl.read_csv(ZONE_PASSES_FILE, null_values=[""])
    baseline_summary = pl.read_csv(BASELINE_SUMMARY_FILE, null_values=[""])
    strategy_priors = load_strategy_prior_table(STRATEGY_PRIOR_FILE).to_frame()

    curve_points = build_zone_curve_points(zone_passes, config=ZoneCurveConfig())
    curve_bins = summarize_zone_curve_bins(curve_points, config=ZoneCurveConfig())
    zone_models = build_zone_piecewise_models(curve_bins, config=ZoneModelConfig())

    estimated_strategy_config = _estimated_strategy_config(baseline_summary)
    stress_strategy_config = replace(
        estimated_strategy_config,
        race_laps_override=estimated_race_laps(
            estimated_strategy_config.race_duration_min,
            estimated_strategy_config.baseline_lap_time_s,
            count_final_lap_after_clock=estimated_strategy_config.count_final_lap_after_clock,
        )
        + 1,
    )

    estimated_fuel_targets = _with_context(
        build_fuel_saving_targets(config=estimated_strategy_config),
        strategy_context_id="estimated_100m",
    )
    stress_fuel_targets = _with_context(
        build_fuel_saving_targets(config=stress_strategy_config),
        strategy_context_id="stress_plus_one_lap",
    )
    fuel_targets = pl.concat([estimated_fuel_targets, stress_fuel_targets], how="vertical")

    starter_target_fuel_saved_l = STARTER_TARGET_FUEL_SAVED_PER_LAP_L
    starter_plan_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=starter_target_fuel_saved_l,
        allowed_model_statuses=("model_ready",),
    )
    starter_plan = optimize_zone_lico_plan(
        zone_models,
        config=starter_plan_config,
        zone_priors=strategy_priors,
    )
    if starter_plan.is_empty():
        raise ValueError("Paul Ricard starter plan produced no optimizer candidates")

    marginal_efficiency = build_zone_marginal_efficiency(
        zone_models,
        zone_plan=starter_plan,
    )
    sensitivity = summarize_zone_plan_sensitivity(
        zone_models,
        base_config=starter_plan_config,
        zone_priors=strategy_priors,
    )
    target_sweep = _target_sweep(
        zone_models,
        zone_priors=strategy_priors,
        targets=TARGET_SWEEP_L,
    )
    strategy_assumptions = _strategy_assumptions_frame(
        baseline_summary,
        estimated_strategy_config,
        stress_strategy_config,
        starter_target_fuel_saved_l=starter_target_fuel_saved_l,
        stress_required_fuel_saved_l=_current_stop_reduction_target(stress_fuel_targets),
    )
    strategy_comparison = _strategy_comparison(
        starter_plan,
        estimated_strategy_config=estimated_strategy_config,
        stress_strategy_config=stress_strategy_config,
    )

    _write_csv(zone_models, OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_piecewise_models.csv")
    _write_csv(starter_plan, OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_lico_plan_starter.csv")
    _write_csv(
        marginal_efficiency,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_marginal_efficiency_starter.csv",
    )
    _write_csv(
        sensitivity,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_plan_sensitivity_starter.csv",
    )
    _write_csv(
        target_sweep,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_plan_target_sweep.csv",
    )
    _write_csv(
        strategy_assumptions,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_strategy_assumptions.csv",
    )
    _write_csv(
        fuel_targets,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_fuel_saving_targets.csv",
    )
    _write_csv(
        strategy_comparison,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_strategy_comparison.csv",
    )

    plan_report = create_zone_plan_report_figure(
        zone_models,
        starter_plan,
        title=(
            "Paul Ricard LMP2 bootstrap static zone plan "
            f"(starter target {starter_target_fuel_saved_l:.3f} L/lap)"
        ),
    )
    write_zone_plan_report_html(
        plan_report,
        OUTPUT_DIR / "paul_ricard_lmp2_bootstrap_zone_lico_plan_starter_report.html",
    )

    first = starter_plan.row(0, named=True)
    print("Paul Ricard bootstrap static plan built.")
    print(
        f"Starter target fuel saved per lap: {starter_target_fuel_saved_l:.6f} L"
    )
    print(
        f"Plan total fuel saved per lap: {float(first['total_predicted_fuel_saved_l']):.6f} L"
    )
    print(
        f"Plan total time lost per lap: {float(first['total_predicted_time_lost_s']):.6f} s"
    )
    print(
        starter_plan.select(
            "zone_id",
            "display_label",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )


def _estimated_strategy_config(baseline_summary: pl.DataFrame) -> RaceStrategyConfig:
    clean_baseline = baseline_summary.filter(
        pl.col("recommended_review_action") == "candidate_clean"
    )
    if clean_baseline.is_empty():
        raise ValueError("no clean baseline laps available for Paul Ricard bootstrap plan")

    pit_observations = pl.read_csv(PIT_STOP_OBSERVATION_FILE)
    pit_row = pit_observations.filter(pl.col("validity_label") == "valid").row(0, named=True)
    return RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=float(clean_baseline["fuel_used_l"].mean()),
        baseline_lap_time_s=float(clean_baseline["lap_time_s"].mean()),
        pit_lane_commitment_time_s=float(pit_row["pit_lane_commitment_time_s"]),
        refill_rate_lps=float(pit_row["observed_refill_rate_lps"]),
        mandatory_stop_count=0,
        count_final_lap_after_clock=True,
    )


def _current_stop_reduction_target(fuel_targets: pl.DataFrame) -> float:
    candidates = fuel_targets.filter(pl.col("is_less_than_baseline_stop_count"))
    if candidates.is_empty():
        return 0.0
    preferred = candidates.sort("target_stop_count", descending=True).row(0, named=True)
    return float(preferred["required_fuel_saving_per_lap_l"])


def _target_sweep(
    zone_models: pl.DataFrame,
    *,
    zone_priors: pl.DataFrame,
    targets: tuple[float, ...],
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for target_fuel_saved_l in targets:
        plan = optimize_zone_lico_plan(
            zone_models,
            config=ZoneOptimizerConfig(
                target_fuel_saved_per_lap_l=target_fuel_saved_l,
                allowed_model_statuses=("model_ready",),
            ),
            zone_priors=zone_priors,
        )
        if plan.is_empty():
            rows.append(
                {
                    "target_fuel_saved_per_lap_l": target_fuel_saved_l,
                    "plan_status": "no_candidates",
                    "total_predicted_fuel_saved_l": None,
                    "total_predicted_time_lost_s": None,
                    "fuel_surplus_l": None,
                    "selected_zone_count": 0,
                    "selected_zone_ids": "",
                    "selected_zone_distances": "",
                }
            )
            continue

        first = plan.row(0, named=True)
        selected = plan.filter(pl.col("is_selected_for_lico"))
        rows.append(
            {
                "target_fuel_saved_per_lap_l": target_fuel_saved_l,
                "plan_status": str(first["plan_status"]),
                "total_predicted_fuel_saved_l": float(first["total_predicted_fuel_saved_l"]),
                "total_predicted_time_lost_s": float(first["total_predicted_time_lost_s"]),
                "fuel_surplus_l": float(first["fuel_surplus_l"]),
                "selected_zone_count": selected.height,
                "selected_zone_ids": _selected_zone_ids(selected),
                "selected_zone_distances": _selected_zone_distances(selected),
            }
        )

    return pl.DataFrame(rows)


def _strategy_assumptions_frame(
    baseline_summary: pl.DataFrame,
    estimated_strategy_config: RaceStrategyConfig,
    stress_strategy_config: RaceStrategyConfig,
    *,
    starter_target_fuel_saved_l: float,
    stress_required_fuel_saved_l: float,
) -> pl.DataFrame:
    clean_baseline = baseline_summary.filter(
        pl.col("recommended_review_action") == "candidate_clean"
    )
    estimated_laps = estimated_race_laps(
        estimated_strategy_config.race_duration_min,
        estimated_strategy_config.baseline_lap_time_s,
        count_final_lap_after_clock=estimated_strategy_config.count_final_lap_after_clock,
    )
    stress_laps = int(stress_strategy_config.race_laps_override or estimated_laps + 1)
    return pl.DataFrame(
        [
            {
                "track_name": TRACK_NAME,
                "car_class": CAR_CLASS,
                "baseline_clean_lap_count": clean_baseline.height,
                "baseline_mean_fuel_per_lap_l": estimated_strategy_config.baseline_fuel_per_lap_l,
                "baseline_mean_lap_time_s": estimated_strategy_config.baseline_lap_time_s,
                "race_duration_min": estimated_strategy_config.race_duration_min,
                "estimated_race_laps": estimated_laps,
                "stress_race_laps": stress_laps,
                "starter_target_fuel_saved_per_lap_l": starter_target_fuel_saved_l,
                "stress_required_fuel_saved_per_lap_l": stress_required_fuel_saved_l,
                "pit_lane_commitment_time_source": "spa_placeholder_until_paul_ricard_pit_sample",
                "notes": (
                    "Estimated 100-minute Paul Ricard baseline already sits on a one-stop edge "
                    "at 54 laps. The first static plan therefore stays on a gentle 0.05 L/lap "
                    "starter target, while the more aggressive 55-lap stress requirement is "
                    "reported separately for later planning."
                ),
            }
        ]
    )


def _strategy_comparison(
    starter_plan: pl.DataFrame,
    *,
    estimated_strategy_config: RaceStrategyConfig,
    stress_strategy_config: RaceStrategyConfig,
) -> pl.DataFrame:
    first = starter_plan.row(0, named=True)
    fuel_saved_per_lap_l = float(first["total_predicted_fuel_saved_l"])
    time_lost_per_lap_s = float(first["total_predicted_time_lost_s"])
    estimated = _with_context(
        compare_push_and_lico_strategy(
            fuel_saved_per_lap_l=fuel_saved_per_lap_l,
            time_lost_per_lap_s=time_lost_per_lap_s,
            config=estimated_strategy_config,
        ),
        strategy_context_id="estimated_100m",
    )
    stress = _with_context(
        compare_push_and_lico_strategy(
            fuel_saved_per_lap_l=fuel_saved_per_lap_l,
            time_lost_per_lap_s=time_lost_per_lap_s,
            config=stress_strategy_config,
        ),
        strategy_context_id="stress_plus_one_lap",
    )
    return pl.concat([estimated, stress], how="vertical")


def _with_context(frame: pl.DataFrame, *, strategy_context_id: str) -> pl.DataFrame:
    return frame.with_columns(pl.lit(strategy_context_id).alias("strategy_context_id")).select(
        "strategy_context_id",
        *frame.columns,
    )


def _selected_zone_ids(selected: pl.DataFrame) -> str:
    if selected.is_empty():
        return ""
    return "|".join(selected.sort("zone_id")["zone_id"].to_list())


def _selected_zone_distances(selected: pl.DataFrame) -> str:
    if selected.is_empty():
        return ""
    return "|".join(
        f"{row['zone_id']}={float(row['selected_lico_distance_m']):.3f}"
        for row in selected.sort("zone_id").iter_rows(named=True)
    )


def _write_csv(frame: pl.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _csv_safe_frame(frame).write_csv(path)
    return path


def _csv_safe_frame(frame: pl.DataFrame) -> pl.DataFrame:
    list_columns = [
        column
        for column, dtype in frame.schema.items()
        if isinstance(dtype, pl.List)
    ]
    if not list_columns:
        return frame
    return frame.with_columns(
        [
            pl.col(column)
            .list.eval(pl.element().cast(pl.String))
            .list.join("|")
            .alias(column)
            for column in list_columns
        ]
    )


if __name__ == "__main__":
    main()
