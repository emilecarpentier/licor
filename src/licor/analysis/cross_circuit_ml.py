from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl


OBSERVATION_KEY = ["dataset_id", "circuit_id", "run_id", "lap_number", "zone_id"]
_ACCELERATION_PROFILE_RATIOS = (0.0, 0.25, 0.5, 1.0, 1.5)


@dataclass(frozen=True)
class BrakingEventConfig:
    brake_threshold_pct: float = 5.0
    min_peak_brake_pct: float = 15.0
    min_event_duration_s: float = 0.18
    merge_gap_s: float = 0.12
    recovery_throttle_pct: float = 40.0
    min_recovery_duration_s: float = 0.30
    min_post_minimum_duration_s: float = 0.20
    post_zone_capture_margin_m: float = 250.0
    acceleration_window_s: float = 1.00
    acceleration_guard_s: float = 0.20
    min_acceleration_window_s: float = 0.60
    min_sensor_speed_correlation: float = 0.80


def extract_physical_braking_events(
    zone_passes: pl.DataFrame,
    lap_samples: pl.DataFrame,
    *,
    track_length_m: float,
    config: BrakingEventConfig | None = None,
) -> pl.DataFrame:
    """Extract the main sustained braking event and its first relevant speed minimum.

    Manual LICO-window and brake-reference fields are deliberately ignored. Zone
    bounds only provide a broad capture interval around the physical event.
    """

    event_config = config or BrakingEventConfig()
    required_pass = {"run_id", "lap_number", "zone_id", "zone_start_m", "zone_end_m"}
    required_sample = {
        "run_id",
        "lap_number",
        "ts",
        "lap_distance_m",
        "ground_speed_kph",
        "throttle_pct",
        "brake_pct",
    }
    _require_columns(zone_passes, required_pass, "zone passes")
    _require_columns(lap_samples, required_sample, "lap samples")

    sample_groups = {
        (str(keys[0]), int(keys[1])): frame.sort("ts")
        for keys, frame in lap_samples.group_by(
            ["run_id", "lap_number"], maintain_order=True
        )
    }
    rows = []
    for zone_pass in zone_passes.iter_rows(named=True):
        key = (str(zone_pass["run_id"]), int(zone_pass["lap_number"]))
        samples = sample_groups.get(key)
        if samples is None:
            rows.append(_empty_event_row(zone_pass, "missing_lap_samples"))
            continue
        capture_start_m = float(zone_pass["zone_start_m"])
        capture_span_m = _forward_distance(
            capture_start_m,
            (float(zone_pass["zone_end_m"]) + event_config.post_zone_capture_margin_m)
            % track_length_m,
            track_length_m,
        )
        captured = samples.filter(
            pl.col("lap_distance_m").map_elements(
                lambda distance_m: (
                    _forward_distance(
                        capture_start_m, float(distance_m), track_length_m
                    )
                    <= capture_span_m
                ),
                return_dtype=pl.Boolean,
            )
        ).sort("ts")
        rows.append(
            _physical_braking_event_row(
                zone_pass,
                captured,
                lap_samples=samples,
                track_length_m=track_length_m,
                config=event_config,
            )
        )
    return pl.DataFrame(rows, schema=_BRAKING_EVENT_SCHEMA, strict=False).select(
        _BRAKING_EVENT_COLUMNS
    )


def build_cross_circuit_observations(
    dynamics: pl.DataFrame,
    zone_passes: pl.DataFrame,
    braking_events: pl.DataFrame,
    run_metadata: pl.DataFrame,
    *,
    dataset_id: str,
    circuit_id: str,
    track_length_m: float,
    zone_definition_version: str,
    extractor_version: str,
) -> pl.DataFrame:
    """Build raw observations without any globally fitted baseline columns."""

    keys = ["run_id", "lap_number", "zone_id"]
    _require_columns(dynamics, set(keys), "experimental dynamics")
    _require_columns(zone_passes, set(keys), "zone passes")
    _require_columns(braking_events, set(keys), "braking events")
    _require_columns(run_metadata, {"run_id"}, "run metadata")

    raw_dynamics_columns = [
        column
        for column in dynamics.columns
        if not column.startswith("baseline_")
        and not column.endswith("_vs_baseline_l")
        and not column.endswith("_vs_baseline_s")
        and "_delta_vs_baseline_" not in column
    ]
    pass_columns = [
        "turn_numbers",
        "lico_window_start_m",
        "brake_reference_m",
        "lico_start_m",
        "lico_end_m",
        "lico_distance_m",
        "lico_duration_s",
        "throttle_release_rate_pct_per_s",
        "minimum_throttle_pct_before_brake",
        "average_throttle_pct_before_brake",
        "driver_review_exclusion_reason",
        "driver_review_exclusion_notes",
        "driver_review_signal_tags",
        "driver_review_pass_tags",
    ]
    available_pass_columns = [
        column for column in pass_columns if column in zone_passes.columns
    ]
    metadata_columns = [column for column in run_metadata.columns if column != "run_id"]

    legacy_renames = {
        "lico_distance_before_brake_m": "legacy_lift_lead_vs_manual_brake_reference_m",
        "brake_start_m": "legacy_first_brake_sample_m",
        "brake_start_speed_kph": "legacy_first_brake_sample_speed_kph",
        "apex_distance_m": "legacy_window_min_speed_point_m",
        "apex_speed_kph": "legacy_window_min_speed_point_kph",
        "time_brake_to_apex_s": "legacy_time_first_brake_to_window_min_speed_s",
        "time_apex_to_end_s": "legacy_time_window_min_speed_to_zone_end_s",
    }
    observations = (
        dynamics.select(raw_dynamics_columns)
        .rename(
            {
                source: target
                for source, target in legacy_renames.items()
                if source in raw_dynamics_columns
            }
        )
        .join(
            zone_passes.select([*keys, *available_pass_columns]).unique(keys),
            on=keys,
            how="left",
        )
        .join(braking_events, on=keys, how="left")
        .join(
            run_metadata.select(["run_id", *metadata_columns]), on="run_id", how="left"
        )
        .with_columns(
            pl.lit(dataset_id).alias("dataset_id"),
            pl.lit(circuit_id).alias("circuit_id"),
            pl.lit(track_length_m).alias("track_length_m"),
            pl.lit(zone_definition_version).alias("zone_definition_version"),
            pl.lit(extractor_version).alias("extractor_version"),
            pl.lit(None, dtype=pl.Float64).alias("planned_lift_start_m"),
            pl.lit(None, dtype=pl.Float64).alias("pre_action_snapshot_ts"),
            pl.lit(None, dtype=pl.Float64).alias("decision_cutoff_ts"),
            pl.lit(False).alias("pre_action_cutoff_verified"),
        )
    )

    exclusion = (
        pl.col("driver_review_exclusion_reason").fill_null("")
        if "driver_review_exclusion_reason" in observations.columns
        else pl.lit("")
    )
    observations = observations.with_columns(
        ((pl.col("validity_label") == "valid") & (exclusion == "")).alias(
            "model_eligible"
        ),
        (
            (~pl.col("has_lico"))
            & (
                (pl.col("collection_design") == "baseline")
                | pl.col("run_type").str.to_lowercase().str.contains("push")
            )
        ).alias("is_push_reference_candidate"),
    )
    observations = observations.with_columns(
        pl.concat_str(
            [pl.col(column).cast(pl.String) for column in OBSERVATION_KEY],
            separator="|",
        ).alias("observation_id")
    )
    _assert_unique(observations, OBSERVATION_KEY, "cross-circuit observations")
    return observations.select(
        [
            "observation_id",
            *OBSERVATION_KEY,
            *[
                column
                for column in observations.columns
                if column not in {"observation_id", *OBSERVATION_KEY}
            ],
        ]
    ).sort(["circuit_id", "run_id", "lap_number", "zone_id"])


def load_feature_contract(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def feature_registry_frame(contract: dict[str, Any]) -> pl.DataFrame:
    rows = list(contract.get("columns", []))
    for group in contract.get("column_groups", []):
        definitions = group.get("definitions", {})
        for column in group.get("columns", []):
            rows.append(
                {
                    "column": column,
                    "role": group["role"],
                    "availability": group["availability"],
                    "model_tasks": group["model_tasks"],
                    "definition": definitions.get(column, group["default_definition"]),
                }
            )
    if not rows:
        raise ValueError("feature contract must define at least one column")
    registry = pl.DataFrame(rows)
    required = {"column", "role", "availability", "model_tasks", "definition"}
    _require_columns(registry, required, "feature contract")
    if registry["column"].n_unique() != registry.height:
        raise ValueError("feature contract contains duplicate column names")
    return registry


def validate_feature_contract(
    observations: pl.DataFrame,
    contract: dict[str, Any],
) -> None:
    registry = feature_registry_frame(contract)
    documented = set(registry["column"].to_list())
    missing = sorted(set(observations.columns) - documented)
    if missing:
        raise ValueError(
            f"observation columns missing from feature contract: {', '.join(missing)}"
        )


def load_split_manifest(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def build_split_assignments(
    observations: pl.DataFrame,
    manifest: dict[str, Any],
) -> pl.DataFrame:
    """Expand explicit run-level fold roles to observation-level assignments."""

    _require_columns(
        observations,
        {"observation_id", "run_id", "circuit_id", "has_lico", "model_eligible"},
        "observations",
    )
    known_runs = set(observations["run_id"].unique().to_list())
    locked_external = set(manifest.get("locked_external_holdout_run_ids", []))
    globally_excluded = set(manifest.get("globally_excluded_run_ids", []))
    unexpected = known_runs & locked_external
    if unexpected:
        raise ValueError(
            "locked external holdout leaked into observations: "
            + ", ".join(sorted(unexpected))
        )

    rows = []
    for fold in manifest.get("folds", []):
        fold_id = str(fold["fold_id"])
        role_by_run: dict[str, str] = {}
        for role in ("train", "calibration", "validation", "test", "excluded"):
            for run_id in fold.get(f"{role}_run_ids", []):
                if run_id in role_by_run:
                    raise ValueError(
                        f"run {run_id} has multiple roles in fold {fold_id}"
                    )
                role_by_run[str(run_id)] = role
        unknown = sorted(set(role_by_run) - known_runs - locked_external)
        if unknown:
            raise ValueError(
                f"fold {fold_id} references unknown runs: {', '.join(unknown)}"
            )
        run_circuits = {
            str(run_id): str(circuit_id)
            for run_id, circuit_id in observations.select("run_id", "circuit_id")
            .unique()
            .iter_rows()
        }
        scoped_circuits = {
            run_circuits[run_id] for run_id in role_by_run if run_id in run_circuits
        }
        required_runs = {
            run_id
            for run_id, circuit_id in run_circuits.items()
            if circuit_id in scoped_circuits and run_id not in globally_excluded
        }
        missing_roles = sorted(required_runs - set(role_by_run))
        if missing_roles:
            raise ValueError(
                f"fold {fold_id} does not assign all in-scope runs: {', '.join(missing_roles)}"
            )

        assigned = observations.with_columns(
            pl.col("run_id")
            .replace_strict(role_by_run, default="excluded")
            .alias("split_role")
        ).with_columns(
            pl.lit(fold_id).alias("fold_id"),
            pl.lit(str(fold["evaluation_regime"])).alias("evaluation_regime"),
            (
                (pl.col("split_role") == "test")
                & pl.col("has_lico")
                & pl.col("model_eligible")
            ).alias("score_eligible"),
            (
                pl.col("split_role").is_in(["train", "calibration"])
                & pl.col("is_push_reference_candidate")
                & pl.col("model_eligible")
            ).alias("push_reference_eligible"),
        )
        _validate_fold_isolation(assigned, fold)
        rows.append(
            assigned.select(
                "fold_id",
                "evaluation_regime",
                "observation_id",
                "circuit_id",
                "run_id",
                "lap_number",
                "zone_id",
                "split_role",
                "score_eligible",
                "push_reference_eligible",
            )
        )
    if not rows:
        raise ValueError("split manifest must define at least one fold")
    return pl.concat(rows).sort(
        ["fold_id", "circuit_id", "run_id", "lap_number", "zone_id"]
    )


def fit_fold_push_references(
    observations: pl.DataFrame,
    assignments: pl.DataFrame,
    *,
    fold_id: str,
    minimum_support: int = 3,
    maximum_deceleration_cv: float = 0.15,
) -> pl.DataFrame:
    """Fit per-zone push references using only train/calibration assignments."""

    fold = assignments.filter(pl.col("fold_id") == fold_id)
    if fold.is_empty():
        raise ValueError(f"unknown fold_id: {fold_id}")
    eligible_ids = fold.filter(pl.col("push_reference_eligible"))["observation_id"]
    reference_rows = observations.join(
        pl.DataFrame({"observation_id": eligible_ids}), on="observation_id", how="semi"
    ).filter(pl.col("braking_event_quality") == "ready")
    if reference_rows.is_empty():
        return _empty_push_reference_frame()

    return (
        reference_rows.group_by(["circuit_id", "zone_id"])
        .agg(
            pl.len().alias("push_reference_count"),
            pl.col("main_brake_onset_m").median().alias("push_brake_onset_reference_m"),
            pl.col("push_deceleration_distance_observed_m")
            .median()
            .alias("push_deceleration_distance_reference_m"),
            pl.col("push_deceleration_distance_observed_m")
            .std()
            .alias("push_deceleration_distance_std_m"),
            pl.col("zone_start_speed_kph")
            .median()
            .alias("push_approach_speed_reference_kph"),
            pl.col("main_brake_onset_speed_kph")
            .median()
            .alias("push_brake_onset_speed_reference_kph"),
            pl.col("fuel_used_l").median().alias("push_fuel_used_reference_l"),
            pl.col("elapsed_time_s").median().alias("push_elapsed_time_reference_s"),
            pl.col("min_speed_point_kph")
            .median()
            .alias("push_min_speed_reference_kph"),
            pl.col("exit_speed_kph").median().alias("push_exit_speed_reference_kph"),
            pl.col("approach_acceleration_ratio_0_0_mps2")
            .median()
            .alias("push_acceleration_ratio_0_0_reference_mps2"),
            pl.col("approach_acceleration_ratio_0_25_mps2")
            .median()
            .alias("push_acceleration_ratio_0_25_reference_mps2"),
            pl.col("approach_acceleration_ratio_0_5_mps2")
            .median()
            .alias("push_acceleration_ratio_0_5_reference_mps2"),
            pl.col("approach_acceleration_ratio_1_0_mps2")
            .median()
            .alias("push_acceleration_ratio_1_0_reference_mps2"),
            pl.col("approach_acceleration_ratio_1_5_mps2")
            .median()
            .alias("push_acceleration_ratio_1_5_reference_mps2"),
            pl.col("approach_acceleration_ratio_0_0_mps2")
            .count()
            .alias("push_acceleration_ratio_0_0_support"),
            pl.col("approach_acceleration_ratio_0_25_mps2")
            .count()
            .alias("push_acceleration_ratio_0_25_support"),
            pl.col("approach_acceleration_ratio_0_5_mps2")
            .count()
            .alias("push_acceleration_ratio_0_5_support"),
            pl.col("approach_acceleration_ratio_1_0_mps2")
            .count()
            .alias("push_acceleration_ratio_1_0_support"),
            pl.col("approach_acceleration_ratio_1_5_mps2")
            .count()
            .alias("push_acceleration_ratio_1_5_support"),
        )
        .with_columns(
            pl.lit(fold_id).alias("fold_id"),
            (
                pl.col("push_deceleration_distance_std_m")
                / pl.col("push_deceleration_distance_reference_m")
            ).alias("push_deceleration_distance_cv"),
        )
        .with_columns(
            pl.when(pl.col("push_reference_count") < minimum_support)
            .then(pl.lit("insufficient_push_support"))
            .when(pl.col("push_deceleration_distance_reference_m") <= 0.0)
            .then(pl.lit("nonpositive_push_denominator"))
            .when(pl.col("push_deceleration_distance_cv") > maximum_deceleration_cv)
            .then(pl.lit("unstable_push_denominator"))
            .otherwise(pl.lit("ready"))
            .alias("push_reference_status"),
            pl.when(
                (pl.col("push_acceleration_ratio_0_0_support") >= minimum_support)
                & (pl.col("push_acceleration_ratio_0_25_support") >= minimum_support)
                & (pl.col("push_acceleration_ratio_0_5_support") >= minimum_support)
                & (pl.col("push_acceleration_ratio_1_0_support") >= minimum_support)
                & (pl.col("push_acceleration_ratio_1_5_support") >= minimum_support)
            )
            .then(pl.lit("ready"))
            .otherwise(pl.lit("insufficient_push_acceleration_support"))
            .alias("push_acceleration_profile_status"),
        )
        .select(_PUSH_REFERENCE_COLUMNS)
        .sort(["circuit_id", "zone_id"])
    )


def attach_fold_push_references(
    observations: pl.DataFrame,
    assignments: pl.DataFrame,
    references: pl.DataFrame,
    *,
    fold_id: str,
) -> pl.DataFrame:
    """Attach fold-fitted references and derive physical action ratios/targets."""

    fold = assignments.filter(pl.col("fold_id") == fold_id)
    joined = (
        observations.join(
            fold.select(
                "observation_id",
                "evaluation_regime",
                "split_role",
                "score_eligible",
            ),
            on="observation_id",
            how="inner",
        )
        .join(references.drop("fold_id"), on=["circuit_id", "zone_id"], how="left")
        .with_columns(
            pl.struct("lico_start_m", "push_brake_onset_reference_m", "track_length_m")
            .map_elements(
                lambda row: _lead_distance_or_none(
                    row["lico_start_m"],
                    row["push_brake_onset_reference_m"],
                    row["track_length_m"],
                ),
                return_dtype=pl.Float64,
            )
            .alias("executed_lift_lead_vs_push_brake_m"),
            pl.struct(
                "planned_lift_start_m", "push_brake_onset_reference_m", "track_length_m"
            )
            .map_elements(
                lambda row: _lead_distance_or_none(
                    row["planned_lift_start_m"],
                    row["push_brake_onset_reference_m"],
                    row["track_length_m"],
                ),
                return_dtype=pl.Float64,
            )
            .alias("planned_lift_lead_vs_push_brake_m"),
        )
        .with_columns(
            pl.when(
                (pl.col("push_reference_status") == "ready")
                & pl.col("executed_lift_lead_vs_push_brake_m").is_not_null()
            )
            .then(
                pl.col("executed_lift_lead_vs_push_brake_m")
                / pl.col("push_deceleration_distance_reference_m")
            )
            .otherwise(None)
            .alias("executed_lift_lead_to_push_deceleration_ratio"),
            pl.when(
                (pl.col("push_reference_status") == "ready")
                & pl.col("planned_lift_lead_vs_push_brake_m").is_not_null()
            )
            .then(
                pl.col("planned_lift_lead_vs_push_brake_m")
                / pl.col("push_deceleration_distance_reference_m")
            )
            .otherwise(None)
            .alias("planned_lift_lead_to_push_deceleration_ratio"),
            (pl.col("push_fuel_used_reference_l") - pl.col("fuel_used_l")).alias(
                "target_fuel_saved_vs_fold_push_l"
            ),
            (pl.col("elapsed_time_s") - pl.col("push_elapsed_time_reference_s")).alias(
                "target_time_lost_vs_fold_push_s"
            ),
            (
                pl.col("main_brake_onset_m") - pl.col("push_brake_onset_reference_m")
            ).alias("observed_brake_onset_delta_vs_fold_push_m"),
            (
                pl.col("min_speed_point_kph") - pl.col("push_min_speed_reference_kph")
            ).alias("observed_min_speed_delta_vs_fold_push_kph"),
            (pl.col("exit_speed_kph") - pl.col("push_exit_speed_reference_kph")).alias(
                "observed_exit_speed_delta_vs_fold_push_kph"
            ),
            pl.lit(fold_id).alias("fold_id"),
        )
        .with_columns(
            pl.struct(
                "executed_lift_lead_to_push_deceleration_ratio",
                "push_acceleration_ratio_0_0_reference_mps2",
                "push_acceleration_ratio_0_25_reference_mps2",
                "push_acceleration_ratio_0_5_reference_mps2",
                "push_acceleration_ratio_1_0_reference_mps2",
                "push_acceleration_ratio_1_5_reference_mps2",
                "push_acceleration_profile_status",
            )
            .map_elements(_interpolate_push_acceleration, return_dtype=pl.Float64)
            .alias("push_acceleration_at_executed_lift_mps2"),
            pl.col("executed_lift_lead_to_push_deceleration_ratio")
            .map_elements(_acceleration_lookup_status, return_dtype=pl.String)
            .alias("executed_acceleration_lookup_status"),
            pl.struct(
                "planned_lift_lead_to_push_deceleration_ratio",
                "push_acceleration_ratio_0_0_reference_mps2",
                "push_acceleration_ratio_0_25_reference_mps2",
                "push_acceleration_ratio_0_5_reference_mps2",
                "push_acceleration_ratio_1_0_reference_mps2",
                "push_acceleration_ratio_1_5_reference_mps2",
                "push_acceleration_profile_status",
            )
            .map_elements(_interpolate_push_acceleration, return_dtype=pl.Float64)
            .alias("push_acceleration_at_planned_lift_mps2"),
            pl.col("planned_lift_lead_to_push_deceleration_ratio")
            .map_elements(_acceleration_lookup_status, return_dtype=pl.String)
            .alias("planned_acceleration_lookup_status"),
        )
        .with_columns(
            (
                pl.col("executed_lift_lead_to_push_deceleration_ratio")
                * pl.col("push_acceleration_at_executed_lift_mps2").clip(
                    lower_bound=0.0
                )
            ).alias("executed_acceleration_weighted_action"),
            (
                pl.col("planned_lift_lead_to_push_deceleration_ratio")
                * pl.col("push_acceleration_at_planned_lift_mps2").clip(lower_bound=0.0)
            ).alias("planned_acceleration_weighted_action"),
        )
    )
    return joined.sort(["split_role", "circuit_id", "run_id", "lap_number", "zone_id"])


def _interpolate_push_acceleration(row: dict[str, Any]) -> float | None:
    if row.get("push_acceleration_profile_status") != "ready":
        return None
    ratio_key = next(
        (key for key in row if key.endswith("lift_lead_to_push_deceleration_ratio")),
        None,
    )
    if ratio_key is None or row.get(ratio_key) is None:
        return None
    ratio = float(row[ratio_key])
    points = [
        (0.0, row.get("push_acceleration_ratio_0_0_reference_mps2")),
        (0.25, row.get("push_acceleration_ratio_0_25_reference_mps2")),
        (0.5, row.get("push_acceleration_ratio_0_5_reference_mps2")),
        (1.0, row.get("push_acceleration_ratio_1_0_reference_mps2")),
        (1.5, row.get("push_acceleration_ratio_1_5_reference_mps2")),
    ]
    if any(value is None for _, value in points):
        return None
    ratio = min(1.5, max(0.0, ratio))
    for (left_ratio, left_value), (right_ratio, right_value) in zip(points, points[1:]):
        if ratio <= right_ratio:
            weight = (ratio - left_ratio) / (right_ratio - left_ratio)
            return float(left_value) + weight * (float(right_value) - float(left_value))
    return float(points[-1][1])


def _acceleration_lookup_status(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    if ratio < 0.0:
        return "clipped_low"
    if ratio > 1.5:
        return "clipped_high"
    return "in_range"


def evaluate_monotone_action_only_baseline(
    fold_views: pl.DataFrame,
    *,
    require_acceleration_profile: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Evaluate a zero-intercept monotone response baseline on declared folds.

    Executed action is used only for this retrospective response-surface stress
    test. A prospective prediction must provide the planned-action ratio.
    """

    required = {
        "fold_id",
        "evaluation_regime",
        "observation_id",
        "run_id",
        "split_role",
        "score_eligible",
        "model_eligible",
        "executed_lift_lead_to_push_deceleration_ratio",
        "target_fuel_saved_vs_fold_push_l",
        "target_time_lost_vs_fold_push_s",
    }
    if require_acceleration_profile:
        required.update(
            {
                "push_acceleration_at_executed_lift_mps2",
                "executed_acceleration_lookup_status",
            }
        )
    _require_columns(fold_views, required, "fold feature views")
    model_name = (
        "pooled_monotone_action_only_acceleration_subset_v1"
        if require_acceleration_profile
        else "pooled_monotone_action_only_v1"
    )
    prediction_rows = []
    metric_rows = []
    targets = (
        ("fuel_saved_l", "target_fuel_saved_vs_fold_push_l"),
        ("time_lost_s", "target_time_lost_vs_fold_push_s"),
    )
    for fold_id in fold_views["fold_id"].unique(maintain_order=True).to_list():
        fold = fold_views.filter(pl.col("fold_id") == fold_id)
        regime = str(fold["evaluation_regime"][0])
        acceleration_available = (
            (
                pl.col("push_acceleration_at_executed_lift_mps2").is_not_null()
                & (pl.col("executed_acceleration_lookup_status") == "in_range")
            )
            if require_acceleration_profile
            else pl.lit(True)
        )
        train = fold.filter(
            (pl.col("split_role") == "train")
            & pl.col("model_eligible")
            & pl.col("executed_lift_lead_to_push_deceleration_ratio").is_not_null()
            & acceleration_available
        )
        test = fold.filter(
            pl.col("score_eligible")
            & pl.col("executed_lift_lead_to_push_deceleration_ratio").is_not_null()
            & acceleration_available
        )
        for target_name, target_column in targets:
            clean_train = train.filter(pl.col(target_column).is_not_null())
            clean_test = test.filter(pl.col(target_column).is_not_null())
            slope = _nonnegative_zero_intercept_slope(
                clean_train["executed_lift_lead_to_push_deceleration_ratio"].to_list(),
                clean_train[target_column].to_list(),
            )
            if slope is None or clean_test.is_empty():
                metric_rows.append(
                    _empty_diagnostic_metric_row(
                        fold_id=str(fold_id),
                        regime=regime,
                        target_name=target_name,
                        train_count=clean_train.height,
                        test_count=clean_test.height,
                        slope=slope,
                        interaction_slope=None,
                        model_name=model_name,
                    )
                )
                continue
            fold_prediction_rows = []
            for row in clean_test.iter_rows(named=True):
                action = float(row["executed_lift_lead_to_push_deceleration_ratio"])
                actual = float(row[target_column])
                predicted = slope * action
                fold_prediction_rows.append(
                    {
                        "fold_id": str(fold_id),
                        "evaluation_regime": regime,
                        "model_name": model_name,
                        "target_name": target_name,
                        "observation_id": str(row["observation_id"]),
                        "run_id": str(row["run_id"]),
                        "action_ratio": action,
                        "push_acceleration_at_lift_mps2": None,
                        "acceleration_weighted_action": None,
                        "actual": actual,
                        "predicted": predicted,
                        "zero_baseline_prediction": 0.0,
                        "error": predicted - actual,
                    }
                )
            prediction_rows.extend(fold_prediction_rows)
            metric_rows.append(
                _diagnostic_metric_row(
                    fold_id=str(fold_id),
                    regime=regime,
                    target_name=target_name,
                    train_count=clean_train.height,
                    slope=slope,
                    interaction_slope=None,
                    prediction_rows=fold_prediction_rows,
                    model_name=model_name,
                )
            )
    predictions = pl.DataFrame(
        prediction_rows, schema=_DIAGNOSTIC_PREDICTION_SCHEMA, strict=False
    )
    metrics = pl.DataFrame(metric_rows, schema=_DIAGNOSTIC_METRIC_SCHEMA, strict=False)
    return predictions, metrics


def evaluate_monotone_action_acceleration_baseline(
    fold_views: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Evaluate action plus action×push-acceleration with non-negative slopes.

    The acceleration profile is fitted only from fold-eligible push laps and is
    interpolated at the proposed/executed physical lift ratio. Executed action is
    retained here solely for retrospective response-surface evaluation.
    """

    required = {
        "fold_id",
        "evaluation_regime",
        "observation_id",
        "run_id",
        "split_role",
        "score_eligible",
        "model_eligible",
        "executed_lift_lead_to_push_deceleration_ratio",
        "push_acceleration_at_executed_lift_mps2",
        "executed_acceleration_weighted_action",
        "executed_acceleration_lookup_status",
        "target_fuel_saved_vs_fold_push_l",
        "target_time_lost_vs_fold_push_s",
    }
    _require_columns(fold_views, required, "fold feature views")
    prediction_rows = []
    metric_rows = []
    targets = (
        ("fuel_saved_l", "target_fuel_saved_vs_fold_push_l"),
        ("time_lost_s", "target_time_lost_vs_fold_push_s"),
    )
    for fold_id in fold_views["fold_id"].unique(maintain_order=True).to_list():
        fold = fold_views.filter(pl.col("fold_id") == fold_id)
        regime = str(fold["evaluation_regime"][0])
        available = (
            pl.col("executed_lift_lead_to_push_deceleration_ratio").is_not_null()
            & pl.col("push_acceleration_at_executed_lift_mps2").is_not_null()
            & pl.col("executed_acceleration_weighted_action").is_not_null()
            & (pl.col("executed_acceleration_lookup_status") == "in_range")
        )
        train = fold.filter(
            (pl.col("split_role") == "train") & pl.col("model_eligible") & available
        )
        test = fold.filter(pl.col("score_eligible") & available)
        for target_name, target_column in targets:
            clean_train = train.filter(pl.col(target_column).is_not_null())
            clean_test = test.filter(pl.col(target_column).is_not_null())
            slopes = _nonnegative_two_feature_slopes(
                clean_train["executed_lift_lead_to_push_deceleration_ratio"].to_list(),
                clean_train["executed_acceleration_weighted_action"].to_list(),
                clean_train[target_column].to_list(),
            )
            if slopes is None or clean_test.is_empty():
                metric_rows.append(
                    _empty_diagnostic_metric_row(
                        fold_id=str(fold_id),
                        regime=regime,
                        target_name=target_name,
                        train_count=clean_train.height,
                        test_count=clean_test.height,
                        slope=None if slopes is None else slopes[0],
                        interaction_slope=None if slopes is None else slopes[1],
                        model_name="pooled_monotone_action_acceleration_v1",
                    )
                )
                continue
            action_slope, interaction_slope = slopes
            fold_prediction_rows = []
            for row in clean_test.iter_rows(named=True):
                action = float(row["executed_lift_lead_to_push_deceleration_ratio"])
                acceleration = float(row["push_acceleration_at_executed_lift_mps2"])
                interaction = float(row["executed_acceleration_weighted_action"])
                actual = float(row[target_column])
                predicted = action_slope * action + interaction_slope * interaction
                fold_prediction_rows.append(
                    {
                        "fold_id": str(fold_id),
                        "evaluation_regime": regime,
                        "model_name": "pooled_monotone_action_acceleration_v1",
                        "target_name": target_name,
                        "observation_id": str(row["observation_id"]),
                        "run_id": str(row["run_id"]),
                        "action_ratio": action,
                        "push_acceleration_at_lift_mps2": acceleration,
                        "acceleration_weighted_action": interaction,
                        "actual": actual,
                        "predicted": predicted,
                        "zero_baseline_prediction": 0.0,
                        "error": predicted - actual,
                    }
                )
            prediction_rows.extend(fold_prediction_rows)
            metric_rows.append(
                _diagnostic_metric_row(
                    fold_id=str(fold_id),
                    regime=regime,
                    target_name=target_name,
                    train_count=clean_train.height,
                    slope=action_slope,
                    interaction_slope=interaction_slope,
                    prediction_rows=fold_prediction_rows,
                    model_name="pooled_monotone_action_acceleration_v1",
                )
            )
    predictions = pl.DataFrame(
        prediction_rows, schema=_DIAGNOSTIC_PREDICTION_SCHEMA, strict=False
    )
    metrics = pl.DataFrame(metric_rows, schema=_DIAGNOSTIC_METRIC_SCHEMA, strict=False)
    return predictions, metrics


def _physical_braking_event_row(
    zone_pass: dict[str, Any],
    samples: pl.DataFrame,
    *,
    lap_samples: pl.DataFrame,
    track_length_m: float,
    config: BrakingEventConfig,
) -> dict[str, Any]:
    if samples.height < 2:
        return _empty_event_row(zone_pass, "insufficient_samples")
    rows = samples.sort("ts").iter_rows(named=True)
    sample_rows = list(rows)
    segments = _brake_segments(sample_rows, config)
    if not segments:
        return _empty_event_row(zone_pass, "no_sustained_braking")
    main = max(segments, key=lambda segment: segment["area_pct_s"])
    onset_index = int(main["start_index"])
    recovery_span = _recovery_span(sample_rows, int(main["end_index"]), config)
    if recovery_span is None:
        return _empty_event_row(zone_pass, "missing_stable_acceleration_recovery")
    recovery_start_index, recovery_end_index = recovery_span
    search_end = recovery_start_index
    search_rows = sample_rows[onset_index : search_end + 1]
    if not search_rows:
        return _empty_event_row(zone_pass, "missing_min_speed_search")
    minimum_speed = min(float(row["ground_speed_kph"]) for row in search_rows)
    minimum = next(
        row for row in search_rows if float(row["ground_speed_kph"]) == minimum_speed
    )
    if (
        float(sample_rows[recovery_end_index]["ts"]) - float(minimum["ts"])
        < config.min_post_minimum_duration_s
    ):
        return _empty_event_row(zone_pass, "insufficient_post_minimum_support")
    onset = sample_rows[onset_index]
    deceleration_distance = _forward_distance(
        float(onset["lap_distance_m"]),
        float(minimum["lap_distance_m"]),
        track_length_m,
    )
    quality = (
        "ready" if deceleration_distance > 0.0 else "nonpositive_deceleration_distance"
    )
    lap_rows = list(lap_samples.sort("ts").iter_rows(named=True))
    sensor_speed_correlation = _sensor_speed_acceleration_correlation(lap_rows)
    sensor_valid = (
        sensor_speed_correlation is not None
        and sensor_speed_correlation >= config.min_sensor_speed_correlation
    )
    acceleration_measurement_source = (
        "mapped_g_force_lat_sensor"
        if sensor_valid
        else "ground_speed_regression_fallback"
    )
    acceleration_profile = {
        ratio: _acceleration_at_lead(
            lap_rows,
            brake_onset_ts=float(onset["ts"]),
            brake_onset_m=float(onset["lap_distance_m"]),
            lead_m=ratio * deceleration_distance,
            track_length_m=track_length_m,
            config=config,
            sensor_valid=sensor_valid,
        )
        for ratio in _ACCELERATION_PROFILE_RATIOS
    }
    lico_start_m = zone_pass.get("lico_start_m")
    observed_pre_lift = (
        _acceleration_at_point(
            lap_rows,
            point_m=float(lico_start_m),
            latest_ts=float(onset["ts"]),
            track_length_m=track_length_m,
            config=config,
            sensor_valid=sensor_valid,
        )
        if lico_start_m is not None
        else None
    )
    return {
        "run_id": str(zone_pass["run_id"]),
        "lap_number": int(zone_pass["lap_number"]),
        "zone_id": str(zone_pass["zone_id"]),
        "main_brake_onset_m": float(onset["lap_distance_m"]),
        "main_brake_onset_ts": float(onset["ts"]),
        "main_brake_onset_speed_kph": float(onset["ground_speed_kph"]),
        "main_brake_event_duration_s": float(main["duration_s"]),
        "main_brake_event_area_pct_s": float(main["area_pct_s"]),
        "min_speed_point_m": float(minimum["lap_distance_m"]),
        "min_speed_point_ts": float(minimum["ts"]),
        "min_speed_point_kph": minimum_speed,
        "push_deceleration_distance_observed_m": deceleration_distance,
        "approach_acceleration_ratio_0_0_mps2": acceleration_profile[0.0],
        "approach_acceleration_ratio_0_25_mps2": acceleration_profile[0.25],
        "approach_acceleration_ratio_0_5_mps2": acceleration_profile[0.5],
        "approach_acceleration_ratio_1_0_mps2": acceleration_profile[1.0],
        "approach_acceleration_ratio_1_5_mps2": acceleration_profile[1.5],
        "observed_pre_lift_acceleration_mps2": observed_pre_lift,
        "acceleration_sensor_speed_correlation": sensor_speed_correlation,
        "acceleration_measurement_source": acceleration_measurement_source,
        "braking_event_quality": quality,
    }


def _acceleration_at_lead(
    rows: list[dict[str, Any]],
    *,
    brake_onset_ts: float,
    brake_onset_m: float,
    lead_m: float,
    track_length_m: float,
    config: BrakingEventConfig,
    sensor_valid: bool,
) -> float | None:
    candidates = [
        row
        for row in rows
        if float(row["ts"]) < brake_onset_ts
        and _forward_distance(
            float(row["lap_distance_m"]), brake_onset_m, track_length_m
        )
        <= max(lead_m + 100.0, 150.0)
    ]
    if not candidates:
        return None
    point = min(
        candidates,
        key=lambda row: abs(
            _forward_distance(
                float(row["lap_distance_m"]), brake_onset_m, track_length_m
            )
            - lead_m
        ),
    )
    return _acceleration_before_ts(
        rows,
        point_ts=float(point["ts"]),
        config=config,
        sensor_valid=sensor_valid,
    )


def _acceleration_at_point(
    rows: list[dict[str, Any]],
    *,
    point_m: float,
    latest_ts: float,
    track_length_m: float,
    config: BrakingEventConfig,
    sensor_valid: bool,
) -> float | None:
    candidates = [row for row in rows if float(row["ts"]) <= latest_ts]
    if not candidates:
        return None
    point = min(
        candidates,
        key=lambda row: min(
            _forward_distance(float(row["lap_distance_m"]), point_m, track_length_m),
            _forward_distance(point_m, float(row["lap_distance_m"]), track_length_m),
        ),
    )
    return _acceleration_before_ts(
        rows,
        point_ts=float(point["ts"]),
        config=config,
        sensor_valid=sensor_valid,
    )


def _acceleration_before_ts(
    rows: list[dict[str, Any]],
    *,
    point_ts: float,
    config: BrakingEventConfig,
    sensor_valid: bool,
) -> float | None:
    end_ts = point_ts - config.acceleration_guard_s
    start_ts = end_ts - config.acceleration_window_s
    window = [
        row
        for row in rows
        if start_ts <= float(row["ts"]) <= end_ts
        and row.get("ground_speed_kph") is not None
    ]
    if len(window) < 2:
        return None
    span_s = float(window[-1]["ts"]) - float(window[0]["ts"])
    if span_s < config.min_acceleration_window_s:
        return None
    if sensor_valid:
        sensor_values = [
            float(row["longitudinal_accel_sensor_mps2"])
            for row in window
            if row.get("longitudinal_accel_sensor_mps2") is not None
            and math.isfinite(float(row["longitudinal_accel_sensor_mps2"]))
        ]
        if len(sensor_values) >= 4:
            return _median(sensor_values)
    times = [float(row["ts"]) for row in window]
    speeds_mps = [float(row["ground_speed_kph"]) / 3.6 for row in window]
    mean_time = sum(times) / len(times)
    mean_speed = sum(speeds_mps) / len(speeds_mps)
    denominator = sum((value - mean_time) ** 2 for value in times)
    if denominator <= 0.0:
        return None
    slope = (
        sum(
            (time - mean_time) * (speed - mean_speed)
            for time, speed in zip(times, speeds_mps)
        )
        / denominator
    )
    return slope if math.isfinite(slope) else None


def _sensor_speed_acceleration_correlation(
    rows: list[dict[str, Any]],
) -> float | None:
    pairs = []
    for previous, current in zip(rows, rows[1:]):
        sensor = current.get("longitudinal_accel_sensor_mps2")
        previous_speed = previous.get("ground_speed_kph")
        current_speed = current.get("ground_speed_kph")
        delta_s = float(current["ts"]) - float(previous["ts"])
        if (
            sensor is None
            or previous_speed is None
            or current_speed is None
            or delta_s <= 0.0
        ):
            continue
        speed_acceleration = (
            (float(current_speed) - float(previous_speed)) / 3.6 / delta_s
        )
        if math.isfinite(float(sensor)) and math.isfinite(speed_acceleration):
            pairs.append((float(sensor), speed_acceleration))
    if len(pairs) < 20:
        return None
    sensor_values = [pair[0] for pair in pairs]
    speed_values = [pair[1] for pair in pairs]
    sensor_mean = sum(sensor_values) / len(sensor_values)
    speed_mean = sum(speed_values) / len(speed_values)
    numerator = sum(
        (sensor - sensor_mean) * (speed - speed_mean) for sensor, speed in pairs
    )
    sensor_ss = sum((value - sensor_mean) ** 2 for value in sensor_values)
    speed_ss = sum((value - speed_mean) ** 2 for value in speed_values)
    denominator = math.sqrt(sensor_ss * speed_ss)
    if denominator <= 0.0:
        return None
    return numerator / denominator


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _nonnegative_zero_intercept_slope(
    actions: list[float], targets: list[float]
) -> float | None:
    pairs = [
        (float(action), float(target))
        for action, target in zip(actions, targets)
        if math.isfinite(float(action)) and math.isfinite(float(target))
    ]
    denominator = sum(action * action for action, _ in pairs)
    if denominator <= 0.0:
        return None
    numerator = sum(action * target for action, target in pairs)
    return max(0.0, numerator / denominator)


def _nonnegative_two_feature_slopes(
    first: list[float], second: list[float], targets: list[float]
) -> tuple[float, float] | None:
    rows = [
        (float(x1), float(x2), float(target))
        for x1, x2, target in zip(first, second, targets)
        if math.isfinite(float(x1))
        and math.isfinite(float(x2))
        and math.isfinite(float(target))
    ]
    if not rows:
        return None
    xx11 = sum(x1 * x1 for x1, _, _ in rows)
    xx22 = sum(x2 * x2 for _, x2, _ in rows)
    xx12 = sum(x1 * x2 for x1, x2, _ in rows)
    xy1 = sum(x1 * target for x1, _, target in rows)
    xy2 = sum(x2 * target for _, x2, target in rows)
    candidates = [(0.0, 0.0)]
    if xx11 > 0.0:
        candidates.append((max(0.0, xy1 / xx11), 0.0))
    if xx22 > 0.0:
        candidates.append((0.0, max(0.0, xy2 / xx22)))
    determinant = xx11 * xx22 - xx12 * xx12
    if determinant > 1e-12:
        first_slope = (xy1 * xx22 - xy2 * xx12) / determinant
        second_slope = (xy2 * xx11 - xy1 * xx12) / determinant
        if first_slope >= 0.0 and second_slope >= 0.0:
            candidates.append((first_slope, second_slope))
    return min(
        candidates,
        key=lambda slopes: sum(
            (slopes[0] * x1 + slopes[1] * x2 - target) ** 2 for x1, x2, target in rows
        ),
    )


def _diagnostic_metric_row(
    *,
    fold_id: str,
    regime: str,
    target_name: str,
    train_count: int,
    slope: float,
    interaction_slope: float | None,
    prediction_rows: list[dict[str, Any]],
    model_name: str = "pooled_monotone_action_only_v1",
) -> dict[str, Any]:
    errors = [float(row["error"]) for row in prediction_rows]
    actuals = [float(row["actual"]) for row in prediction_rows]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    zero_mae = sum(abs(actual) for actual in actuals) / len(actuals)
    zero_rmse = math.sqrt(sum(actual * actual for actual in actuals) / len(actuals))
    run_errors: dict[str, list[float]] = {}
    run_actuals: dict[str, list[float]] = {}
    for row in prediction_rows:
        run_id = str(row["run_id"])
        run_errors.setdefault(run_id, []).append(float(row["error"]))
        run_actuals.setdefault(run_id, []).append(float(row["actual"]))
    run_maes = [
        sum(abs(error) for error in values) / len(values)
        for values in run_errors.values()
    ]
    run_zero_maes = [
        sum(abs(actual) for actual in values) / len(values)
        for values in run_actuals.values()
    ]
    return {
        "fold_id": fold_id,
        "evaluation_regime": regime,
        "model_name": model_name,
        "target_name": target_name,
        "train_count": train_count,
        "test_count": len(prediction_rows),
        "test_run_count": len(run_errors),
        "fitted_slope": slope,
        "fitted_interaction_slope": interaction_slope,
        "mae": mae,
        "rmse": rmse,
        "mean_error": sum(errors) / len(errors),
        "zero_baseline_mae": zero_mae,
        "zero_baseline_rmse": zero_rmse,
        "mae_improvement_vs_zero": zero_mae - mae,
        "run_macro_mae": sum(run_maes) / len(run_maes),
        "run_macro_zero_baseline_mae": sum(run_zero_maes) / len(run_zero_maes),
        "run_macro_mae_improvement_vs_zero": (
            sum(run_zero_maes) / len(run_zero_maes) - sum(run_maes) / len(run_maes)
        ),
        "status": "diagnostic_only",
    }


def _empty_diagnostic_metric_row(
    *,
    fold_id: str,
    regime: str,
    target_name: str,
    train_count: int,
    test_count: int,
    slope: float | None,
    interaction_slope: float | None,
    model_name: str = "pooled_monotone_action_only_v1",
) -> dict[str, Any]:
    return {
        "fold_id": fold_id,
        "evaluation_regime": regime,
        "model_name": model_name,
        "target_name": target_name,
        "train_count": train_count,
        "test_count": test_count,
        "test_run_count": 0,
        "fitted_slope": slope,
        "fitted_interaction_slope": interaction_slope,
        "mae": None,
        "rmse": None,
        "mean_error": None,
        "zero_baseline_mae": None,
        "zero_baseline_rmse": None,
        "mae_improvement_vs_zero": None,
        "run_macro_mae": None,
        "run_macro_zero_baseline_mae": None,
        "run_macro_mae_improvement_vs_zero": None,
        "status": "insufficient_data",
    }


def _brake_segments(
    rows: list[dict[str, Any]], config: BrakingEventConfig
) -> list[dict[str, float | int]]:
    raw: list[tuple[int, int]] = []
    start = None
    for index, row in enumerate(rows):
        active = float(row["brake_pct"]) >= config.brake_threshold_pct
        if active and start is None:
            start = index
        elif not active and start is not None:
            raw.append((start, index - 1))
            start = None
    if start is not None:
        raw.append((start, len(rows) - 1))

    merged: list[tuple[int, int]] = []
    for left, right in raw:
        if (
            merged
            and float(rows[left]["ts"]) - float(rows[merged[-1][1]]["ts"])
            <= config.merge_gap_s
        ):
            merged[-1] = (merged[-1][0], right)
        else:
            merged.append((left, right))

    events = []
    for left, right in merged:
        duration = float(rows[right]["ts"]) - float(rows[left]["ts"])
        peak = max(float(row["brake_pct"]) for row in rows[left : right + 1])
        if duration < config.min_event_duration_s or peak < config.min_peak_brake_pct:
            continue
        area = 0.0
        for current, following in zip(
            rows[left : right + 1], rows[left + 1 : right + 1]
        ):
            delta_s = max(0.0, float(following["ts"]) - float(current["ts"]))
            area += delta_s * float(current["brake_pct"]) / 100.0
        events.append(
            {
                "start_index": left,
                "end_index": right,
                "duration_s": duration,
                "area_pct_s": area,
            }
        )
    return events


def _recovery_span(
    rows: list[dict[str, Any]], start_index: int, config: BrakingEventConfig
) -> tuple[int, int] | None:
    for left in range(start_index + 1, len(rows)):
        if (
            float(rows[left]["brake_pct"]) >= config.brake_threshold_pct
            or float(rows[left]["throttle_pct"]) < config.recovery_throttle_pct
        ):
            continue
        right = left
        while right + 1 < len(rows):
            candidate = rows[right + 1]
            if (
                float(candidate["brake_pct"]) >= config.brake_threshold_pct
                or float(candidate["throttle_pct"]) < config.recovery_throttle_pct
            ):
                break
            right += 1
        if (
            float(rows[right]["ts"]) - float(rows[left]["ts"])
            >= config.min_recovery_duration_s
        ):
            return left, right
    return None


def _empty_event_row(zone_pass: dict[str, Any], quality: str) -> dict[str, Any]:
    return {
        "run_id": str(zone_pass["run_id"]),
        "lap_number": int(zone_pass["lap_number"]),
        "zone_id": str(zone_pass["zone_id"]),
        "main_brake_onset_m": None,
        "main_brake_onset_ts": None,
        "main_brake_onset_speed_kph": None,
        "main_brake_event_duration_s": None,
        "main_brake_event_area_pct_s": None,
        "min_speed_point_m": None,
        "min_speed_point_ts": None,
        "min_speed_point_kph": None,
        "push_deceleration_distance_observed_m": None,
        "approach_acceleration_ratio_0_0_mps2": None,
        "approach_acceleration_ratio_0_25_mps2": None,
        "approach_acceleration_ratio_0_5_mps2": None,
        "approach_acceleration_ratio_1_0_mps2": None,
        "approach_acceleration_ratio_1_5_mps2": None,
        "observed_pre_lift_acceleration_mps2": None,
        "acceleration_sensor_speed_correlation": None,
        "acceleration_measurement_source": None,
        "braking_event_quality": quality,
    }


def _forward_distance(start_m: float, end_m: float, track_length_m: float) -> float:
    distance = end_m - start_m
    if distance < 0.0:
        distance += track_length_m
    return distance


def _lead_distance_or_none(
    start_m: object, end_m: object, track_length_m: object
) -> float | None:
    if start_m is None or end_m is None or track_length_m is None:
        return None
    values = (float(start_m), float(end_m), float(track_length_m))
    if any(math.isnan(value) for value in values) or values[2] <= 0.0:
        return None
    start, end, track_length = values
    direct = end - start
    if direct >= 0.0:
        return direct
    if abs(direct) > track_length / 2.0:
        return direct + track_length
    return None


def _validate_fold_isolation(assignments: pl.DataFrame, fold: dict[str, Any]) -> None:
    fold_id = str(fold["fold_id"])
    run_roles = assignments.select("run_id", "circuit_id", "split_role").unique()
    duplicate_roles = run_roles.group_by("run_id").len().filter(pl.col("len") > 1)
    if not duplicate_roles.is_empty():
        raise ValueError(f"fold {fold_id} assigns one run to multiple roles")
    if "source_raw_sha256" in assignments.columns:
        hash_roles = assignments.select("source_raw_sha256", "split_role").unique()
        leaked_hashes = (
            hash_roles.filter(
                pl.col("split_role").is_in(["train", "calibration", "test"])
            )
            .group_by("source_raw_sha256")
            .agg(pl.col("split_role").n_unique().alias("role_count"))
            .filter(pl.col("role_count") > 1)
        )
        if not leaked_hashes.is_empty():
            raise ValueError(
                f"fold {fold_id} assigns one raw telemetry hash to multiple roles"
            )
    if fold["evaluation_regime"] != "cross_circuit_zero_lico_shot_calibrated":
        return
    train_circuits = set(
        run_roles.filter(pl.col("split_role") == "train")["circuit_id"].to_list()
    )
    test_circuits = set(
        run_roles.filter(pl.col("split_role") == "test")["circuit_id"].to_list()
    )
    if train_circuits & test_circuits:
        raise ValueError(f"fold {fold_id} leaks a test circuit into training")
    calibration_circuits = set(
        run_roles.filter(pl.col("split_role") == "calibration")["circuit_id"].to_list()
    )
    if test_circuits != calibration_circuits:
        raise ValueError(f"fold {fold_id} must calibrate only on the held-out circuit")


def _assert_unique(frame: pl.DataFrame, columns: list[str], label: str) -> None:
    duplicates = frame.group_by(columns).len().filter(pl.col("len") > 1)
    if not duplicates.is_empty():
        raise ValueError(f"{label} contain duplicate keys")


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} are missing required columns: {', '.join(missing)}")


_BRAKING_EVENT_COLUMNS = [
    "run_id",
    "lap_number",
    "zone_id",
    "main_brake_onset_m",
    "main_brake_onset_ts",
    "main_brake_onset_speed_kph",
    "main_brake_event_duration_s",
    "main_brake_event_area_pct_s",
    "min_speed_point_m",
    "min_speed_point_ts",
    "min_speed_point_kph",
    "push_deceleration_distance_observed_m",
    "approach_acceleration_ratio_0_0_mps2",
    "approach_acceleration_ratio_0_25_mps2",
    "approach_acceleration_ratio_0_5_mps2",
    "approach_acceleration_ratio_1_0_mps2",
    "approach_acceleration_ratio_1_5_mps2",
    "observed_pre_lift_acceleration_mps2",
    "acceleration_sensor_speed_correlation",
    "acceleration_measurement_source",
    "braking_event_quality",
]

_BRAKING_EVENT_SCHEMA = {
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "main_brake_onset_m": pl.Float64,
    "main_brake_onset_ts": pl.Float64,
    "main_brake_onset_speed_kph": pl.Float64,
    "main_brake_event_duration_s": pl.Float64,
    "main_brake_event_area_pct_s": pl.Float64,
    "min_speed_point_m": pl.Float64,
    "min_speed_point_ts": pl.Float64,
    "min_speed_point_kph": pl.Float64,
    "push_deceleration_distance_observed_m": pl.Float64,
    "approach_acceleration_ratio_0_0_mps2": pl.Float64,
    "approach_acceleration_ratio_0_25_mps2": pl.Float64,
    "approach_acceleration_ratio_0_5_mps2": pl.Float64,
    "approach_acceleration_ratio_1_0_mps2": pl.Float64,
    "approach_acceleration_ratio_1_5_mps2": pl.Float64,
    "observed_pre_lift_acceleration_mps2": pl.Float64,
    "acceleration_sensor_speed_correlation": pl.Float64,
    "acceleration_measurement_source": pl.String,
    "braking_event_quality": pl.String,
}

_PUSH_REFERENCE_COLUMNS = [
    "fold_id",
    "circuit_id",
    "zone_id",
    "push_reference_count",
    "push_brake_onset_reference_m",
    "push_deceleration_distance_reference_m",
    "push_deceleration_distance_std_m",
    "push_deceleration_distance_cv",
    "push_approach_speed_reference_kph",
    "push_brake_onset_speed_reference_kph",
    "push_fuel_used_reference_l",
    "push_elapsed_time_reference_s",
    "push_min_speed_reference_kph",
    "push_exit_speed_reference_kph",
    "push_acceleration_ratio_0_0_reference_mps2",
    "push_acceleration_ratio_0_25_reference_mps2",
    "push_acceleration_ratio_0_5_reference_mps2",
    "push_acceleration_ratio_1_0_reference_mps2",
    "push_acceleration_ratio_1_5_reference_mps2",
    "push_acceleration_ratio_0_0_support",
    "push_acceleration_ratio_0_25_support",
    "push_acceleration_ratio_0_5_support",
    "push_acceleration_ratio_1_0_support",
    "push_acceleration_ratio_1_5_support",
    "push_acceleration_profile_status",
    "push_reference_status",
]

_DIAGNOSTIC_PREDICTION_SCHEMA = {
    "fold_id": pl.String,
    "evaluation_regime": pl.String,
    "model_name": pl.String,
    "target_name": pl.String,
    "observation_id": pl.String,
    "run_id": pl.String,
    "action_ratio": pl.Float64,
    "push_acceleration_at_lift_mps2": pl.Float64,
    "acceleration_weighted_action": pl.Float64,
    "actual": pl.Float64,
    "predicted": pl.Float64,
    "zero_baseline_prediction": pl.Float64,
    "error": pl.Float64,
}

_DIAGNOSTIC_METRIC_SCHEMA = {
    "fold_id": pl.String,
    "evaluation_regime": pl.String,
    "model_name": pl.String,
    "target_name": pl.String,
    "train_count": pl.Int64,
    "test_count": pl.Int64,
    "test_run_count": pl.Int64,
    "fitted_slope": pl.Float64,
    "fitted_interaction_slope": pl.Float64,
    "mae": pl.Float64,
    "rmse": pl.Float64,
    "mean_error": pl.Float64,
    "zero_baseline_mae": pl.Float64,
    "zero_baseline_rmse": pl.Float64,
    "mae_improvement_vs_zero": pl.Float64,
    "run_macro_mae": pl.Float64,
    "run_macro_zero_baseline_mae": pl.Float64,
    "run_macro_mae_improvement_vs_zero": pl.Float64,
    "status": pl.String,
}


def _empty_push_reference_frame() -> pl.DataFrame:
    schema = {
        "fold_id": pl.String,
        "circuit_id": pl.String,
        "zone_id": pl.String,
        "push_reference_count": pl.UInt32,
        **{
            column: pl.Float64
            for column in _PUSH_REFERENCE_COLUMNS[4:]
            if column
            not in {
                "push_acceleration_ratio_0_5_support",
                "push_acceleration_ratio_0_0_support",
                "push_acceleration_ratio_0_25_support",
                "push_acceleration_ratio_1_0_support",
                "push_acceleration_ratio_1_5_support",
                "push_acceleration_profile_status",
                "push_reference_status",
            }
        },
        "push_acceleration_ratio_0_0_support": pl.UInt32,
        "push_acceleration_ratio_0_25_support": pl.UInt32,
        "push_acceleration_ratio_0_5_support": pl.UInt32,
        "push_acceleration_ratio_1_0_support": pl.UInt32,
        "push_acceleration_ratio_1_5_support": pl.UInt32,
        "push_acceleration_profile_status": pl.String,
        "push_reference_status": pl.String,
    }
    return pl.DataFrame(schema=schema).select(_PUSH_REFERENCE_COLUMNS)
