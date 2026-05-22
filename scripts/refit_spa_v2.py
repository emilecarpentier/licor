from __future__ import annotations

from pathlib import Path

import polars as pl

from licor.analysis import (
    FullLapSanityConfig,
    LiveCuePlanConfig,
    RaceStrategyConfig,
    ZoneCurveConfig,
    ZoneModelConfig,
    ZoneOptimizerConfig,
    ZonePassConfig,
    ZoneSummaryConfig,
    build_fuel_saving_targets,
    build_live_cue_plan,
    build_spa_v2_quality_artifacts,
    build_spa_v2_readiness_artifacts,
    build_zone_curve_points,
    build_zone_marginal_efficiency,
    build_zone_piecewise_models,
    build_labeled_zone_passes,
    default_zone_plan_sensitivity_scenarios,
    evaluate_race_strategy_scenarios,
    load_driver_zone_review,
    load_strategy_prior_table,
    load_track_zone_table,
    optimize_zone_lico_plan,
    summarize_full_lap_sanity,
    summarize_labeled_dataset,
    summarize_zone_costs,
    summarize_zone_curve_bins,
    summarize_zone_plan_sensitivity,
)
from licor.reports import (
    build_spa_lmp2_lap_telemetry_report_artifact,
    create_zone_curve_report_figure,
    create_zone_model_report_figure,
    create_zone_plan_report_figure,
    write_zone_curve_report_html,
    write_zone_model_report_html,
    write_zone_plan_report_html,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_LABEL_FILE = PROJECT_ROOT / "config/datasets/spa_lmp2_v2_2026-05-21.json"
TRACK_ZONE_FILE = PROJECT_ROOT / "config/track_zones/spa_lmp2_zones.draft.json"
DRIVER_REVIEW_FILE = (
    PROJECT_ROOT / "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json"
)
STRATEGY_PRIOR_FILE = (
    PROJECT_ROOT / "config/strategy_priors/spa_lmp2_driver_priors_2026-05-14.json"
)
PIT_STOP_OBSERVATION_FILE = PROJECT_ROOT / "data/processed/spa_lmp2_pit_stop_observations.csv"
OUTPUT_DIR = PROJECT_ROOT / "data/processed"

TRACK_NAME = "Circuit de Spa-Francorchamps"
CAR_CLASS = "LMP2_ELMS"
RACE_CONTEXT_ID = "elms_100m_48_laps"
PRUDENT_PLAN_ID = "spa_lmp2_driver_priors_prudent_v2"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    build_spa_v2_readiness_artifacts(project_root=PROJECT_ROOT)
    build_spa_v2_quality_artifacts(project_root=PROJECT_ROOT)
    build_spa_lmp2_lap_telemetry_report_artifact(project_root=PROJECT_ROOT)

    zone_passes = build_labeled_zone_passes(
        dataset_label_file=DATASET_LABEL_FILE,
        track_zone_file=TRACK_ZONE_FILE,
        project_root=PROJECT_ROOT,
        driver_review_file=DRIVER_REVIEW_FILE,
        config=ZonePassConfig(),
    )
    driver_review = load_driver_zone_review(DRIVER_REVIEW_FILE)
    zone_summary = summarize_zone_costs(zone_passes, config=ZoneSummaryConfig())
    curve_points = build_zone_curve_points(zone_passes, config=ZoneCurveConfig())
    curve_bins = summarize_zone_curve_bins(curve_points, config=ZoneCurveConfig())
    zone_models = build_zone_piecewise_models(
        curve_bins,
        zone_annotations=driver_review.annotation_frame(),
        config=ZoneModelConfig(),
    )
    lap_summary = summarize_labeled_dataset(DATASET_LABEL_FILE, project_root=PROJECT_ROOT)
    lap_sanity = summarize_full_lap_sanity(
        lap_summary,
        curve_points,
        config=FullLapSanityConfig(),
    )

    strategy_config = _strategy_config(lap_summary, PIT_STOP_OBSERVATION_FILE)
    fuel_targets = build_fuel_saving_targets(config=strategy_config)
    target_fuel_saved_l = _current_stop_reduction_target(fuel_targets)
    strategy_scenarios = _strategy_scenarios(lap_summary, strategy_config)
    zone_priors = load_strategy_prior_table(STRATEGY_PRIOR_FILE).to_frame()

    model_ready_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        allowed_model_statuses=("model_ready",),
    )
    prudent_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        allowed_model_statuses=("model_ready", "diagnostic_only"),
    )
    exploratory_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        allowed_model_statuses=("model_ready", "diagnostic_only", "review_excluded"),
        require_usable_ratio=False,
        allow_review_excluded=True,
    )

    model_ready_plan = optimize_zone_lico_plan(zone_models, config=model_ready_config)
    prudent_plan = optimize_zone_lico_plan(
        zone_models,
        config=prudent_config,
        zone_priors=zone_priors,
    )
    exploratory_plan = optimize_zone_lico_plan(
        zone_models,
        config=exploratory_config,
        zone_priors=zone_priors,
    )
    marginal_efficiency = build_zone_marginal_efficiency(
        zone_models,
        zone_plan=prudent_plan,
    )
    sensitivity = summarize_zone_plan_sensitivity(
        zone_models,
        base_config=prudent_config,
        zone_priors=zone_priors,
        scenarios=default_zone_plan_sensitivity_scenarios(),
    )
    live_cue_plan = build_live_cue_plan(
        prudent_plan,
        _track_zone_frame(),
        config=LiveCuePlanConfig(
            plan_id=PRUDENT_PLAN_ID,
            track_name=TRACK_NAME,
            car_class=CAR_CLASS,
            race_context_id=RACE_CONTEXT_ID,
            cue_tolerance_m=5.0,
            track_length_m=_track_length_m(lap_summary),
            notes=(
                "Spa v2 prudent plan refit after integrated baseline and "
                "controlled-random runs."
            ),
        ),
    )

    _write_csv(zone_summary, OUTPUT_DIR / "spa_lmp2_zone_summary.csv")
    _write_csv(curve_points, OUTPUT_DIR / "spa_lmp2_zone_curve_points.csv")
    _write_csv(curve_bins, OUTPUT_DIR / "spa_lmp2_zone_curve_bins.csv")
    _write_csv(zone_models, OUTPUT_DIR / "spa_lmp2_zone_piecewise_models.csv")
    _write_csv(lap_sanity, OUTPUT_DIR / "spa_lmp2_lap_sanity.csv")
    _write_csv(strategy_scenarios, OUTPUT_DIR / "spa_lmp2_race_strategy_scenarios.csv")
    _write_csv(fuel_targets, OUTPUT_DIR / "spa_lmp2_fuel_saving_targets.csv")
    _write_csv(model_ready_plan, OUTPUT_DIR / "spa_lmp2_zone_lico_plan_model_ready.csv")
    _write_csv(
        prudent_plan,
        OUTPUT_DIR / "spa_lmp2_zone_lico_plan_driver_priors_prudent.csv",
    )
    _write_csv(
        exploratory_plan,
        OUTPUT_DIR / "spa_lmp2_zone_lico_plan_driver_priors_exploratory.csv",
    )
    _write_csv(marginal_efficiency, OUTPUT_DIR / "spa_lmp2_zone_marginal_efficiency.csv")
    _write_csv(sensitivity, OUTPUT_DIR / "spa_lmp2_zone_plan_sensitivity.csv")
    _write_csv(live_cue_plan, OUTPUT_DIR / "spa_lmp2_live_cue_plan_prudent.csv")

    zone_curve_report = create_zone_curve_report_figure(
        curve_points,
        curve_bins,
        title="Spa LMP2 zone curves (v2 refit)",
    )
    zone_model_report = create_zone_model_report_figure(
        zone_models,
        title="Spa LMP2 piecewise zone models (v2 refit)",
    )
    zone_plan_report = create_zone_plan_report_figure(
        zone_models,
        prudent_plan,
        title="Spa LMP2 prudent zone plan (v2 refit)",
    )
    write_zone_curve_report_html(zone_curve_report, OUTPUT_DIR / "spa_lmp2_zone_curve_report.html")
    write_zone_model_report_html(zone_model_report, OUTPUT_DIR / "spa_lmp2_zone_model_report.html")
    write_zone_plan_report_html(
        zone_plan_report,
        OUTPUT_DIR / "spa_lmp2_zone_lico_plan_driver_priors_prudent_report.html",
    )

    print("Refit complete.")
    print(f"Baseline fuel/lap: {strategy_config.baseline_fuel_per_lap_l:.6f} L")
    print(f"Baseline lap time: {strategy_config.baseline_lap_time_s:.6f} s")
    print(f"Target fuel saved/lap: {target_fuel_saved_l:.6f} L")
    print(
        prudent_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )


def _strategy_config(
    lap_summary: pl.DataFrame,
    pit_stop_observation_file: Path,
) -> RaceStrategyConfig:
    baseline = _current_baseline_laps(lap_summary)
    if baseline.is_empty():
        raise ValueError("no valid baseline laps available for Spa v2 refit")

    pit_observations = pl.read_csv(pit_stop_observation_file)
    pit_row = pit_observations.filter(pl.col("validity_label") == "valid").row(0, named=True)
    return RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=float(baseline["fuel_used_l"].mean()),
        baseline_lap_time_s=float(baseline["lap_time_s"].mean()),
        pit_lane_commitment_time_s=float(pit_row["pit_lane_commitment_time_s"]),
        refill_rate_lps=float(pit_row["observed_refill_rate_lps"]),
        mandatory_stop_count=0,
        count_final_lap_after_clock=True,
        race_laps_override=48,
    )


def _current_baseline_laps(lap_summary: pl.DataFrame) -> pl.DataFrame:
    valid = lap_summary.filter(pl.col("is_valid_lap"))
    baseline_design = valid.filter(pl.col("collection_design") == "baseline")
    if not baseline_design.is_empty():
        return baseline_design
    return valid.filter(pl.col("collection_label") == "none")


def _current_stop_reduction_target(fuel_targets: pl.DataFrame) -> float:
    candidates = fuel_targets.filter(pl.col("is_less_than_baseline_stop_count"))
    if candidates.is_empty():
        return 0.0
    preferred = candidates.sort("target_stop_count", descending=True).row(0, named=True)
    return float(preferred["required_fuel_saving_per_lap_l"])


def _strategy_scenarios(
    lap_summary: pl.DataFrame,
    strategy_config: RaceStrategyConfig,
) -> pl.DataFrame:
    valid = lap_summary.filter(pl.col("is_valid_lap"))
    baseline = _current_baseline_laps(lap_summary)
    baseline_fuel = float(baseline["fuel_used_l"].mean())
    baseline_time = float(baseline["lap_time_s"].mean())

    rows = [
        {
            "scenario_id": "full_push",
            "fuel_per_lap_l": baseline_fuel,
            "lap_time_s": baseline_time,
            "fuel_saved_per_lap_l": 0.0,
            "time_lost_per_lap_s": 0.0,
        }
    ]
    for label in ("low", "medium", "high"):
        frame = valid.filter(pl.col("collection_label") == label)
        if frame.is_empty():
            continue
        mean_fuel = float(frame["fuel_used_l"].mean())
        mean_time = float(frame["lap_time_s"].mean())
        rows.append(
            {
                "scenario_id": label,
                "fuel_per_lap_l": mean_fuel,
                "lap_time_s": mean_time,
                "fuel_saved_per_lap_l": baseline_fuel - mean_fuel,
                "time_lost_per_lap_s": mean_time - baseline_time,
            }
        )

    return evaluate_race_strategy_scenarios(
        pl.DataFrame(rows),
        config=strategy_config,
    )


def _track_zone_frame() -> pl.DataFrame:
    track_zones = load_track_zone_table(TRACK_ZONE_FILE)
    return pl.DataFrame([zone.model_dump() for zone in track_zones.zones])


def _track_length_m(lap_summary: pl.DataFrame) -> float | None:
    valid = lap_summary.filter(pl.col("is_valid_lap"))
    if valid.is_empty():
        return None
    return float(valid["max_lap_distance_m"].median())


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
