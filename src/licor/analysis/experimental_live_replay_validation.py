from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from licor.analysis.live_cue_runner import (
    LiveCueRunnerConfig,
    simulate_live_cue_events,
    summarize_live_cue_event_accuracy,
)


@dataclass(frozen=True)
class ExperimentalLiveReplayValidationConfig:
    planning_modes: tuple[str, ...] = ("adaptive",)
    track_name: str = ""
    car_class: str = ""
    race_context_id: str = ""
    audio_cue_kind: str = "beep"
    cue_tolerance_m: float = 5.0
    max_initial_late_distance_m: float = 30.0
    track_length_m: float | None = None
    cue_latency_compensation_s: float = 0.0
    cue_latency_reference_speed_kph: float | None = None
    cue_latency_compensation_distance_m: float | None = None
    plan_id_prefix: str = "experimental_adaptive_replay"


def build_experimental_live_replay_plan(
    live_transition_preview: pl.DataFrame,
    track_zones: pl.DataFrame,
    *,
    config: ExperimentalLiveReplayValidationConfig | None = None,
) -> pl.DataFrame:
    """Convert adaptive next-lap handoff rows into live-runner-ready cue plans."""

    replay_config = config or ExperimentalLiveReplayValidationConfig()
    if live_transition_preview.is_empty():
        return pl.DataFrame(schema=_LIVE_REPLAY_PLAN_SCHEMA)

    _require_columns(
        live_transition_preview,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "current_lap_number",
            "next_lap_number",
            "current_notes",
            "next_lap_target_fuel_saved_l",
            "next_lap_expected_fuel_saved_l",
            "next_lap_expected_time_lost_s",
            "next_lap_driver_fuel_execution_scale",
            "next_lap_driver_time_execution_scale",
            "next_lap_driver_zone_execution_scale_count",
            "next_zone_id",
            "next_display_label",
            "next_selected_lico_distance_m",
            "next_expected_fuel_saved_by_zone_l",
            "next_expected_time_lost_by_zone_s",
            "next_source_model_status",
            "next_recommended_range_start_m",
            "next_recommended_range_end_m",
            "next_applied_driver_fuel_execution_scale",
            "next_applied_driver_time_execution_scale",
            "next_applied_zone_execution_support_rows",
            "next_applied_zone_specific_execution_scale",
        },
        "live transition preview",
    )
    _require_columns(
        track_zones,
        {"zone_id", "brake_reference_m"},
        "track zones",
    )

    selected = live_transition_preview.filter(
        pl.col("planning_mode").is_in(replay_config.planning_modes)
        & pl.col("next_zone_id").is_not_null()
    )
    if selected.is_empty():
        return pl.DataFrame(schema=_LIVE_REPLAY_PLAN_SCHEMA)

    joined = selected.join(
        track_zones.select("zone_id", "brake_reference_m"),
        left_on="next_zone_id",
        right_on="zone_id",
        how="left",
    )
    if joined.filter(pl.col("brake_reference_m").is_null()).height:
        missing = "|".join(
            sorted(
                str(value)
                for value in joined.filter(pl.col("brake_reference_m").is_null())[
                    "next_zone_id"
                ].to_list()
            )
        )
        raise ValueError(f"missing brake_reference_m for replay zones: {missing}")

    rows: list[dict[str, object]] = []
    for row in joined.iter_rows(named=True):
        run_id = _run_id_from_scenario_id(str(row["scenario_id"]))
        plan_id = (
            f"{replay_config.plan_id_prefix}|{row['variant_name']}|{row['planning_mode']}"
            f"|{row['scenario_id']}|lap_{int(row['current_lap_number'])}_to_{int(row['next_lap_number'])}"
        )
        selected_distance_m = float(row["next_selected_lico_distance_m"])
        brake_reference_m = float(row["brake_reference_m"])
        planned_lift_start_m = _planned_lift_start_m(
            brake_reference_m,
            selected_distance_m,
            track_length_m=replay_config.track_length_m,
        )
        cue_latency_reference_speed_kph = _cue_latency_reference_speed_kph(
            row,
            config=replay_config,
        )
        cue_latency_compensation_distance_m = _cue_latency_compensation_distance_m(
            row,
            config=replay_config,
            reference_speed_kph=cue_latency_reference_speed_kph,
        )
        rows.append(
            {
                "schema_version": 1,
                "plan_id": plan_id,
                "track_name": replay_config.track_name,
                "car_class": replay_config.car_class,
                "race_context_id": replay_config.race_context_id,
                "zone_id": str(row["next_zone_id"]),
                "display_label": str(row["next_display_label"]),
                "brake_reference_m": brake_reference_m,
                "selected_lico_distance_m": selected_distance_m,
                "planned_lift_start_m": planned_lift_start_m,
                "cue_distance_m": _cue_distance_m(
                    planned_lift_start_m,
                    cue_latency_compensation_distance_m=cue_latency_compensation_distance_m,
                    track_length_m=replay_config.track_length_m,
                ),
                "cue_tolerance_m": replay_config.cue_tolerance_m,
                "track_length_m": replay_config.track_length_m,
                "cue_latency_compensation_s": replay_config.cue_latency_compensation_s,
                "cue_latency_reference_speed_kph": cue_latency_reference_speed_kph,
                "cue_latency_compensation_distance_m": cue_latency_compensation_distance_m,
                "minimum_confidence_label": str(row["next_source_model_status"] or ""),
                "expected_fuel_saved_l": float(row["next_expected_fuel_saved_by_zone_l"]),
                "expected_time_lost_s": float(row["next_expected_time_lost_by_zone_s"]),
                "plan_status": "adaptive_replay_validation",
                "source_model_status": str(row["next_source_model_status"] or ""),
                "source_quality_flags": "",
                "strategy_role": "adaptive_replay_validation",
                "notes": str(row["current_notes"] or ""),
                "scenario_id": str(row["scenario_id"]),
                "variant_name": str(row["variant_name"]),
                "planning_mode": str(row["planning_mode"]),
                "run_id": run_id,
                "current_lap_number": int(row["current_lap_number"]),
                "next_lap_number": int(row["next_lap_number"]),
                "next_lap_target_fuel_saved_l": float(row["next_lap_target_fuel_saved_l"]),
                "next_lap_expected_fuel_saved_l": float(row["next_lap_expected_fuel_saved_l"]),
                "next_lap_expected_time_lost_s": float(row["next_lap_expected_time_lost_s"]),
                "next_lap_driver_fuel_execution_scale": float(
                    row["next_lap_driver_fuel_execution_scale"]
                ),
                "next_lap_driver_time_execution_scale": float(
                    row["next_lap_driver_time_execution_scale"]
                ),
                "next_lap_driver_zone_execution_scale_count": int(
                    row["next_lap_driver_zone_execution_scale_count"]
                ),
                "next_recommended_range_start_m": _optional_float(
                    row.get("next_recommended_range_start_m")
                ),
                "next_recommended_range_end_m": _optional_float(
                    row.get("next_recommended_range_end_m")
                ),
                "next_applied_driver_fuel_execution_scale": float(
                    row["next_applied_driver_fuel_execution_scale"]
                ),
                "next_applied_driver_time_execution_scale": float(
                    row["next_applied_driver_time_execution_scale"]
                ),
                "next_applied_zone_execution_support_rows": int(
                    row["next_applied_zone_execution_support_rows"]
                ),
                "next_applied_zone_specific_execution_scale": bool(
                    row["next_applied_zone_specific_execution_scale"]
                ),
            }
        )

    return pl.DataFrame(rows, schema=_LIVE_REPLAY_PLAN_SCHEMA, strict=False).select(
        _LIVE_REPLAY_PLAN_COLUMNS
    )


def replay_experimental_live_replay_plan(
    live_replay_plan: pl.DataFrame,
    lap_samples: pl.DataFrame,
    observed_zone_outcomes: pl.DataFrame,
    *,
    config: ExperimentalLiveReplayValidationConfig | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Replay adaptive next-lap plans on observed telemetry and summarize results."""

    replay_config = config or ExperimentalLiveReplayValidationConfig()
    if live_replay_plan.is_empty():
        empty_events = pl.DataFrame(schema=_REPLAY_EVENT_LOG_SCHEMA)
        empty_accuracy = pl.DataFrame(schema=_REPLAY_ACCURACY_SCHEMA)
        empty_rows = pl.DataFrame(schema=_REPLAY_VALIDATION_ROW_SCHEMA)
        empty_handoffs = pl.DataFrame(schema=_REPLAY_HANDOFF_SUMMARY_SCHEMA)
        empty_zones = pl.DataFrame(schema=_REPLAY_ZONE_SUMMARY_SCHEMA)
        return empty_events, empty_accuracy, empty_rows, empty_handoffs, empty_zones

    _require_columns(
        live_replay_plan,
        {
            "plan_id",
            "zone_id",
            "display_label",
            "cue_distance_m",
            "planned_lift_start_m",
            "cue_tolerance_m",
            "track_length_m",
            "scenario_id",
            "variant_name",
            "planning_mode",
            "run_id",
            "current_lap_number",
            "next_lap_number",
        },
        "live replay plan",
    )
    _require_columns(
        lap_samples,
        {"run_id", "file_name", "lap_number", "ts", "lap_elapsed_s", "lap_distance_m"},
        "lap samples",
    )
    _require_columns(
        observed_zone_outcomes,
        {
            "run_id",
            "lap_number",
            "zone_id",
            "lico_start_m",
            "lico_start_distance_before_brake_m",
            "brake_start_m",
            "fuel_saved_vs_baseline_l",
            "time_lost_vs_baseline_s",
            "validity_label",
            "notes",
        },
        "observed zone outcomes",
    )

    event_frames: list[pl.DataFrame] = []
    telemetry_status_rows: list[dict[str, object]] = []
    for keys, plan_slice in _handoff_plan_slices(live_replay_plan):
        telemetry_slice = _telemetry_slice(
            lap_samples,
            run_id=keys["run_id"],
            lap_number=keys["next_lap_number"],
        )
        if telemetry_slice.is_empty():
            telemetry_status_rows.append(
                {
                    "plan_id": str(keys["plan_id"]),
                    "telemetry_available": False,
                }
            )
            continue
        telemetry_status_rows.append(
            {
                "plan_id": str(keys["plan_id"]),
                "telemetry_available": True,
            }
        )
        file_name = _first_nonempty_string(
            telemetry_slice.get_column("file_name").to_list(),
            default="",
        )
        events = simulate_live_cue_events(
            plan_slice.select(_LIVE_REPLAY_RUNNER_COLUMNS),
            telemetry_slice,
            config=LiveCueRunnerConfig(
                run_id=str(keys["run_id"]),
                file_name=file_name,
                audio_cue_kind=replay_config.audio_cue_kind,
                track_length_m=_optional_float(keys["track_length_m"]),
                default_cue_tolerance_m=replay_config.cue_tolerance_m,
                max_initial_late_distance_m=replay_config.max_initial_late_distance_m,
            ),
        )
        if events.is_empty():
            continue
        event_frames.append(
            events.with_columns(
                pl.lit(str(keys["scenario_id"])).alias("scenario_id"),
                pl.lit(str(keys["variant_name"])).alias("variant_name"),
                pl.lit(str(keys["planning_mode"])).alias("planning_mode"),
                pl.lit(str(keys["run_id"])).alias("run_id"),
                pl.lit(int(keys["current_lap_number"])).alias("current_lap_number"),
                pl.lit(int(keys["next_lap_number"])).alias("next_lap_number"),
            )
        )

    replay_events = (
        pl.concat(event_frames, how="vertical_relaxed")
        if event_frames
        else pl.DataFrame(schema=_REPLAY_EVENT_LOG_SCHEMA)
    )
    telemetry_status = (
        pl.DataFrame(telemetry_status_rows, schema=_REPLAY_TELEMETRY_STATUS_SCHEMA)
        if telemetry_status_rows
        else pl.DataFrame(schema=_REPLAY_TELEMETRY_STATUS_SCHEMA)
    )
    replay_accuracy = _replay_accuracy(replay_events, live_replay_plan)
    validation_rows = _replay_validation_rows(
        live_replay_plan,
        replay_events,
        replay_accuracy,
        observed_zone_outcomes,
        telemetry_status,
    )
    handoff_summary = _replay_handoff_summary(validation_rows)
    zone_summary = _replay_zone_summary(validation_rows)
    return replay_events, replay_accuracy, validation_rows, handoff_summary, zone_summary


def _replay_accuracy(
    replay_events: pl.DataFrame,
    live_replay_plan: pl.DataFrame,
) -> pl.DataFrame:
    if replay_events.is_empty():
        return pl.DataFrame(schema=_REPLAY_ACCURACY_SCHEMA)

    accuracy = summarize_live_cue_event_accuracy(replay_events)
    plan_metadata = (
        live_replay_plan.select(
            [
                "plan_id",
                "zone_id",
                "display_label",
                "scenario_id",
                "variant_name",
                "planning_mode",
                "run_id",
                "current_lap_number",
                "next_lap_number",
            ]
        )
        .unique()
        .sort(["plan_id", "zone_id"])
    )
    return (
        accuracy.join(
            plan_metadata,
            on=["plan_id", "zone_id", "display_label"],
            how="left",
        )
        .select(_REPLAY_ACCURACY_COLUMNS)
        .sort(["variant_name", "scenario_id", "current_lap_number", "zone_id"])
    )


def _replay_validation_rows(
    live_replay_plan: pl.DataFrame,
    replay_events: pl.DataFrame,
    replay_accuracy: pl.DataFrame,
    observed_zone_outcomes: pl.DataFrame,
    telemetry_status: pl.DataFrame,
) -> pl.DataFrame:
    event_rows = replay_events.select(
        [
            "plan_id",
            "zone_id",
            "lap_number",
            "trigger_status",
            "actual_cue_distance_m",
            "cue_error_m",
            "sample_ts",
            "sample_elapsed_s",
        ]
    ).rename({"lap_number": "actual_trigger_lap_number"})
    outcome_rows = observed_zone_outcomes.select(
        [
            "run_id",
            "lap_number",
            "zone_id",
            "lico_start_m",
            "lico_start_distance_before_brake_m",
            "brake_start_m",
            "fuel_saved_vs_baseline_l",
            "time_lost_vs_baseline_s",
            "validity_label",
            "notes",
        ]
    ).rename(
        {
            "lap_number": "actual_lap_number",
            "lico_start_m": "actual_lift_start_m",
            "lico_start_distance_before_brake_m": "actual_lift_distance_before_brake_m",
            "brake_start_m": "actual_brake_start_m",
            "fuel_saved_vs_baseline_l": "actual_fuel_saved_l",
            "time_lost_vs_baseline_s": "actual_time_lost_s",
            "validity_label": "actual_execution_quality",
            "notes": "actual_notes",
        }
    )

    rows = (
        live_replay_plan.join(
            event_rows,
            on=["plan_id", "zone_id"],
            how="left",
        )
        .join(telemetry_status, on="plan_id", how="left")
        .join(
            replay_accuracy.select(
                [
                    "plan_id",
                    "zone_id",
                    "cue_count",
                    "on_time_rate",
                    "mean_cue_error_m",
                    "median_abs_cue_error_m",
                    "max_abs_cue_error_m",
                ]
            ),
            on=["plan_id", "zone_id"],
            how="left",
        )
        .join(
            outcome_rows,
            left_on=["run_id", "next_lap_number", "zone_id"],
            right_on=["run_id", "actual_lap_number", "zone_id"],
            how="left",
        )
        .with_columns(
            pl.col("telemetry_available").fill_null(False).alias("telemetry_available"),
            pl.col("actual_lift_start_m").is_not_null().alias("actual_zone_executed"),
        )
        .with_columns(
            pl.when(pl.col("telemetry_available"))
            .then(pl.col("trigger_status").is_not_null())
            .otherwise(None)
            .alias("cue_fired"),
            pl.when(pl.col("telemetry_available"))
            .then(pl.col("trigger_status") == "fired_on_time")
            .otherwise(None)
            .alias("cue_fired_on_time"),
            pl.when(pl.col("actual_zone_executed"))
            .then(
                pl.col("actual_lift_distance_before_brake_m")
                - pl.col("selected_lico_distance_m")
            )
            .otherwise(None)
            .alias("actual_distance_before_brake_error_m"),
            pl.when(pl.col("actual_zone_executed"))
            .then(pl.col("actual_fuel_saved_l"))
            .otherwise(None)
            .alias("__masked_actual_fuel_saved_l"),
            pl.when(pl.col("actual_zone_executed"))
            .then(pl.col("actual_time_lost_s"))
            .otherwise(None)
            .alias("__masked_actual_time_lost_s"),
        )
        .with_columns(
            pl.col("__masked_actual_fuel_saved_l").alias("actual_fuel_saved_l"),
            pl.col("__masked_actual_time_lost_s").alias("actual_time_lost_s"),
            (
                pl.col("__masked_actual_fuel_saved_l") - pl.col("expected_fuel_saved_l")
            ).alias("fuel_saved_error_l"),
            (
                pl.col("__masked_actual_time_lost_s") - pl.col("expected_time_lost_s")
            ).alias("time_lost_error_s"),
        )
        .drop("__masked_actual_fuel_saved_l", "__masked_actual_time_lost_s")
    )
    return rows.select(_REPLAY_VALIDATION_ROW_COLUMNS).sort(
        ["variant_name", "scenario_id", "current_lap_number", "zone_id"]
    )


def _replay_handoff_summary(validation_rows: pl.DataFrame) -> pl.DataFrame:
    if validation_rows.is_empty():
        return pl.DataFrame(schema=_REPLAY_HANDOFF_SUMMARY_SCHEMA)
    return (
        validation_rows.group_by(
            [
                "variant_name",
                "planning_mode",
                "scenario_id",
                "run_id",
                "current_lap_number",
                "next_lap_number",
            ]
        )
        .agg(
            pl.col("zone_id").len().alias("planned_zone_count"),
            pl.col("zone_id").sort().implode().list.join("|").alias("planned_zone_ids"),
            pl.col("telemetry_available").all().alias("telemetry_available"),
            pl.col("cue_fired").cast(pl.Float64).mean().alias("cue_fire_rate"),
            pl.col("cue_fired_on_time").cast(pl.Float64).mean().alias("cue_on_time_rate"),
            pl.col("cue_error_m").mean().alias("mean_cue_error_m"),
            pl.col("cue_error_m").abs().median().alias("median_abs_cue_error_m"),
            pl.col("cue_error_m").abs().max().alias("max_abs_cue_error_m"),
            pl.col("actual_zone_executed")
            .cast(pl.Float64)
            .mean()
            .alias("zone_execution_rate"),
            pl.col("actual_zone_executed").cast(pl.Int64).sum().alias("executed_zone_count"),
            pl.col("expected_fuel_saved_l").sum().alias("expected_fuel_saved_total_l"),
            pl.col("actual_fuel_saved_l").sum().alias("actual_fuel_saved_total_l"),
            pl.col("fuel_saved_error_l").sum().alias("fuel_saved_total_error_l"),
            pl.col("expected_time_lost_s").sum().alias("expected_time_lost_total_s"),
            pl.col("actual_time_lost_s").sum().alias("actual_time_lost_total_s"),
            pl.col("time_lost_error_s").sum().alias("time_lost_total_error_s"),
            pl.col("next_lap_target_fuel_saved_l")
            .first()
            .alias("next_lap_target_fuel_saved_l"),
            pl.col("next_lap_expected_fuel_saved_l")
            .first()
            .alias("next_lap_expected_fuel_saved_l"),
            pl.col("next_lap_expected_time_lost_s")
            .first()
            .alias("next_lap_expected_time_lost_s"),
            pl.col("next_lap_driver_fuel_execution_scale")
            .first()
            .alias("next_lap_driver_fuel_execution_scale"),
            pl.col("next_lap_driver_time_execution_scale")
            .first()
            .alias("next_lap_driver_time_execution_scale"),
            pl.col("next_lap_driver_zone_execution_scale_count")
            .first()
            .alias("next_lap_driver_zone_execution_scale_count"),
        )
        .sort(["variant_name", "scenario_id", "current_lap_number"])
        .select(_REPLAY_HANDOFF_SUMMARY_COLUMNS)
    )


def _replay_zone_summary(validation_rows: pl.DataFrame) -> pl.DataFrame:
    if validation_rows.is_empty():
        return pl.DataFrame(schema=_REPLAY_ZONE_SUMMARY_SCHEMA)
    return (
        validation_rows.group_by(
            [
                "variant_name",
                "planning_mode",
                "zone_id",
                "display_label",
                "source_model_status",
            ]
        )
        .agg(
            pl.len().alias("sample_count"),
            pl.col("telemetry_available").cast(pl.Float64).mean().alias("telemetry_available_rate"),
            pl.col("cue_fired").cast(pl.Float64).mean().alias("cue_fire_rate"),
            pl.col("cue_fired_on_time").cast(pl.Float64).mean().alias("cue_on_time_rate"),
            pl.col("cue_error_m").mean().alias("mean_cue_error_m"),
            pl.col("cue_error_m").abs().median().alias("median_abs_cue_error_m"),
            pl.col("actual_zone_executed").cast(pl.Float64).mean().alias("zone_execution_rate"),
            pl.col("expected_fuel_saved_l").mean().alias("mean_expected_fuel_saved_l"),
            pl.col("actual_fuel_saved_l").mean().alias("mean_actual_fuel_saved_l"),
            pl.col("fuel_saved_error_l").mean().alias("mean_fuel_saved_error_l"),
            pl.col("expected_time_lost_s").mean().alias("mean_expected_time_lost_s"),
            pl.col("actual_time_lost_s").mean().alias("mean_actual_time_lost_s"),
            pl.col("time_lost_error_s").mean().alias("mean_time_lost_error_s"),
        )
        .sort(["variant_name", "planning_mode", "zone_id"])
        .select(_REPLAY_ZONE_SUMMARY_COLUMNS)
    )


def _handoff_plan_slices(
    live_replay_plan: pl.DataFrame,
) -> list[tuple[dict[str, object], pl.DataFrame]]:
    keys = [
        "plan_id",
        "scenario_id",
        "variant_name",
        "planning_mode",
        "run_id",
        "current_lap_number",
        "next_lap_number",
        "track_length_m",
    ]
    slices = []
    for key_row in live_replay_plan.select(keys).unique().sort(keys).iter_rows(named=True):
        plan_slice = live_replay_plan.filter(pl.col("plan_id") == key_row["plan_id"])
        if plan_slice.is_empty():
            continue
        slices.append((key_row, plan_slice))
    return slices


def _telemetry_slice(
    lap_samples: pl.DataFrame,
    *,
    run_id: str,
    lap_number: int,
) -> pl.DataFrame:
    frame = lap_samples.filter(
        (pl.col("run_id") == run_id) & (pl.col("lap_number") == lap_number)
    ).sort("ts")
    if frame.is_empty():
        return frame
    return frame.with_columns(pl.col("lap_elapsed_s").alias("elapsed_s"))


def _planned_lift_start_m(
    brake_reference_m: float,
    selected_lico_distance_m: float,
    *,
    track_length_m: float | None,
) -> float:
    lift_start_m = brake_reference_m - selected_lico_distance_m
    if track_length_m is not None:
        return lift_start_m % track_length_m
    return lift_start_m


def _cue_latency_compensation_distance_m(
    row: dict[str, object],
    *,
    config: ExperimentalLiveReplayValidationConfig,
    reference_speed_kph: float | None,
) -> float:
    if config.cue_latency_compensation_distance_m is not None:
        return float(config.cue_latency_compensation_distance_m)
    if config.cue_latency_compensation_s <= 0.0:
        return 0.0
    if reference_speed_kph is None:
        zone_id = row.get("next_zone_id") or row.get("zone_id") or "<unknown>"
        raise ValueError(
            "experimental live replay cue latency compensation requires "
            "cue_latency_reference_speed_kph or a plan row speed for zone "
            f"{zone_id}"
        )
    return (float(reference_speed_kph) / 3.6) * float(
        config.cue_latency_compensation_s
    )


def _cue_latency_reference_speed_kph(
    row: dict[str, object],
    *,
    config: ExperimentalLiveReplayValidationConfig,
) -> float | None:
    for column_name in (
        "next_cue_latency_reference_speed_kph",
        "next_brake_start_speed_kph",
        "next_mean_brake_start_speed_kph",
        "next_baseline_mean_brake_start_speed_kph",
        "next_approach_speed_kph",
    ):
        value = row.get(column_name)
        if value is not None:
            return float(value)
    if config.cue_latency_reference_speed_kph is None:
        return None
    return float(config.cue_latency_reference_speed_kph)


def _cue_distance_m(
    planned_lift_start_m: float,
    *,
    cue_latency_compensation_distance_m: float,
    track_length_m: float | None,
) -> float:
    cue_distance_m = planned_lift_start_m - cue_latency_compensation_distance_m
    if track_length_m is not None:
        return cue_distance_m % track_length_m
    if cue_distance_m < 0.0:
        raise ValueError(
            "cue latency compensation moves cue_distance_m before lap start "
            "without track_length_m"
        )
    return cue_distance_m


def _run_id_from_scenario_id(scenario_id: str) -> str:
    prefix = "observed_execution:"
    if scenario_id.startswith(prefix):
        return scenario_id[len(prefix) :]
    return scenario_id


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _first_nonempty_string(values: list[object], *, default: str) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return default


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{label} are missing required columns: {missing_text}")


_LIVE_REPLAY_RUNNER_COLUMNS = [
    "schema_version",
    "plan_id",
    "track_name",
    "car_class",
    "race_context_id",
    "zone_id",
    "display_label",
    "brake_reference_m",
    "selected_lico_distance_m",
    "planned_lift_start_m",
    "cue_distance_m",
    "cue_tolerance_m",
    "track_length_m",
    "cue_latency_compensation_s",
    "cue_latency_reference_speed_kph",
    "cue_latency_compensation_distance_m",
    "minimum_confidence_label",
    "expected_fuel_saved_l",
    "expected_time_lost_s",
    "plan_status",
    "source_model_status",
    "source_quality_flags",
    "strategy_role",
    "notes",
]

_LIVE_REPLAY_PLAN_COLUMNS = [
    *_LIVE_REPLAY_RUNNER_COLUMNS,
    "scenario_id",
    "variant_name",
    "planning_mode",
    "run_id",
    "current_lap_number",
    "next_lap_number",
    "next_lap_target_fuel_saved_l",
    "next_lap_expected_fuel_saved_l",
    "next_lap_expected_time_lost_s",
    "next_lap_driver_fuel_execution_scale",
    "next_lap_driver_time_execution_scale",
    "next_lap_driver_zone_execution_scale_count",
    "next_recommended_range_start_m",
    "next_recommended_range_end_m",
    "next_applied_driver_fuel_execution_scale",
    "next_applied_driver_time_execution_scale",
    "next_applied_zone_execution_support_rows",
    "next_applied_zone_specific_execution_scale",
]

_LIVE_REPLAY_PLAN_SCHEMA = {
    "schema_version": pl.Int64,
    "plan_id": pl.String,
    "track_name": pl.String,
    "car_class": pl.String,
    "race_context_id": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "brake_reference_m": pl.Float64,
    "selected_lico_distance_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "cue_distance_m": pl.Float64,
    "cue_tolerance_m": pl.Float64,
    "track_length_m": pl.Float64,
    "cue_latency_compensation_s": pl.Float64,
    "cue_latency_reference_speed_kph": pl.Float64,
    "cue_latency_compensation_distance_m": pl.Float64,
    "minimum_confidence_label": pl.String,
    "expected_fuel_saved_l": pl.Float64,
    "expected_time_lost_s": pl.Float64,
    "plan_status": pl.String,
    "source_model_status": pl.String,
    "source_quality_flags": pl.String,
    "strategy_role": pl.String,
    "notes": pl.String,
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "run_id": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "next_lap_expected_fuel_saved_l": pl.Float64,
    "next_lap_expected_time_lost_s": pl.Float64,
    "next_lap_driver_fuel_execution_scale": pl.Float64,
    "next_lap_driver_time_execution_scale": pl.Float64,
    "next_lap_driver_zone_execution_scale_count": pl.Int64,
    "next_recommended_range_start_m": pl.Float64,
    "next_recommended_range_end_m": pl.Float64,
    "next_applied_driver_fuel_execution_scale": pl.Float64,
    "next_applied_driver_time_execution_scale": pl.Float64,
    "next_applied_zone_execution_support_rows": pl.Int64,
    "next_applied_zone_specific_execution_scale": pl.Boolean,
}

_REPLAY_EVENT_LOG_COLUMNS = [
    "schema_version",
    "plan_id",
    "file_name",
    "run_id",
    "lap_number",
    "zone_id",
    "display_label",
    "cue_trigger_m",
    "planned_lift_start_m",
    "actual_cue_distance_m",
    "cue_error_m",
    "cue_tolerance_m",
    "trigger_status",
    "sample_index",
    "sample_ts",
    "sample_elapsed_s",
    "audio_cue_kind",
    "notes",
    "scenario_id",
    "variant_name",
    "planning_mode",
    "current_lap_number",
    "next_lap_number",
]

_REPLAY_EVENT_LOG_SCHEMA = {
    "schema_version": pl.Int64,
    "plan_id": pl.String,
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "cue_trigger_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "actual_cue_distance_m": pl.Float64,
    "cue_error_m": pl.Float64,
    "cue_tolerance_m": pl.Float64,
    "trigger_status": pl.String,
    "sample_index": pl.Int64,
    "sample_ts": pl.Float64,
    "sample_elapsed_s": pl.Float64,
    "audio_cue_kind": pl.String,
    "notes": pl.String,
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
}

_REPLAY_ACCURACY_COLUMNS = [
    "plan_id",
    "zone_id",
    "display_label",
    "cue_count",
    "on_time_rate",
    "mean_cue_error_m",
    "median_abs_cue_error_m",
    "max_abs_cue_error_m",
    "scenario_id",
    "variant_name",
    "planning_mode",
    "run_id",
    "current_lap_number",
    "next_lap_number",
]

_REPLAY_ACCURACY_SCHEMA = {
    "plan_id": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "cue_count": pl.Int64,
    "on_time_rate": pl.Float64,
    "mean_cue_error_m": pl.Float64,
    "median_abs_cue_error_m": pl.Float64,
    "max_abs_cue_error_m": pl.Float64,
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "run_id": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
}

_REPLAY_VALIDATION_ROW_COLUMNS = [
    "plan_id",
    "scenario_id",
    "variant_name",
    "planning_mode",
    "run_id",
    "current_lap_number",
    "next_lap_number",
    "zone_id",
    "display_label",
    "source_model_status",
    "selected_lico_distance_m",
    "planned_lift_start_m",
    "cue_distance_m",
    "expected_fuel_saved_l",
    "expected_time_lost_s",
    "next_lap_target_fuel_saved_l",
    "next_lap_expected_fuel_saved_l",
    "next_lap_expected_time_lost_s",
    "next_lap_driver_fuel_execution_scale",
    "next_lap_driver_time_execution_scale",
    "next_lap_driver_zone_execution_scale_count",
    "next_recommended_range_start_m",
    "next_recommended_range_end_m",
    "next_applied_driver_fuel_execution_scale",
    "next_applied_driver_time_execution_scale",
    "next_applied_zone_execution_support_rows",
    "next_applied_zone_specific_execution_scale",
    "telemetry_available",
    "cue_fired",
    "cue_fired_on_time",
    "trigger_status",
    "actual_cue_distance_m",
    "cue_error_m",
    "cue_count",
    "on_time_rate",
    "mean_cue_error_m",
    "median_abs_cue_error_m",
    "max_abs_cue_error_m",
    "actual_zone_executed",
    "actual_lift_start_m",
    "actual_lift_distance_before_brake_m",
    "actual_brake_start_m",
    "actual_distance_before_brake_error_m",
    "actual_fuel_saved_l",
    "actual_time_lost_s",
    "fuel_saved_error_l",
    "time_lost_error_s",
    "actual_execution_quality",
    "notes",
    "actual_notes",
]

_REPLAY_VALIDATION_ROW_SCHEMA = {
    "plan_id": pl.String,
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "run_id": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "source_model_status": pl.String,
    "selected_lico_distance_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "cue_distance_m": pl.Float64,
    "expected_fuel_saved_l": pl.Float64,
    "expected_time_lost_s": pl.Float64,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "next_lap_expected_fuel_saved_l": pl.Float64,
    "next_lap_expected_time_lost_s": pl.Float64,
    "next_lap_driver_fuel_execution_scale": pl.Float64,
    "next_lap_driver_time_execution_scale": pl.Float64,
    "next_lap_driver_zone_execution_scale_count": pl.Int64,
    "next_recommended_range_start_m": pl.Float64,
    "next_recommended_range_end_m": pl.Float64,
    "next_applied_driver_fuel_execution_scale": pl.Float64,
    "next_applied_driver_time_execution_scale": pl.Float64,
    "next_applied_zone_execution_support_rows": pl.Int64,
    "next_applied_zone_specific_execution_scale": pl.Boolean,
    "telemetry_available": pl.Boolean,
    "cue_fired": pl.Boolean,
    "cue_fired_on_time": pl.Boolean,
    "trigger_status": pl.String,
    "actual_cue_distance_m": pl.Float64,
    "cue_error_m": pl.Float64,
    "cue_count": pl.Int64,
    "on_time_rate": pl.Float64,
    "mean_cue_error_m": pl.Float64,
    "median_abs_cue_error_m": pl.Float64,
    "max_abs_cue_error_m": pl.Float64,
    "actual_zone_executed": pl.Boolean,
    "actual_lift_start_m": pl.Float64,
    "actual_lift_distance_before_brake_m": pl.Float64,
    "actual_brake_start_m": pl.Float64,
    "actual_distance_before_brake_error_m": pl.Float64,
    "actual_fuel_saved_l": pl.Float64,
    "actual_time_lost_s": pl.Float64,
    "fuel_saved_error_l": pl.Float64,
    "time_lost_error_s": pl.Float64,
    "actual_execution_quality": pl.String,
    "notes": pl.String,
    "actual_notes": pl.String,
}

_REPLAY_HANDOFF_SUMMARY_COLUMNS = [
    "variant_name",
    "planning_mode",
    "scenario_id",
    "run_id",
    "current_lap_number",
    "next_lap_number",
    "planned_zone_count",
    "planned_zone_ids",
    "telemetry_available",
    "cue_fire_rate",
    "cue_on_time_rate",
    "mean_cue_error_m",
    "median_abs_cue_error_m",
    "max_abs_cue_error_m",
    "zone_execution_rate",
    "executed_zone_count",
    "expected_fuel_saved_total_l",
    "actual_fuel_saved_total_l",
    "fuel_saved_total_error_l",
    "expected_time_lost_total_s",
    "actual_time_lost_total_s",
    "time_lost_total_error_s",
    "next_lap_target_fuel_saved_l",
    "next_lap_expected_fuel_saved_l",
    "next_lap_expected_time_lost_s",
    "next_lap_driver_fuel_execution_scale",
    "next_lap_driver_time_execution_scale",
    "next_lap_driver_zone_execution_scale_count",
]

_REPLAY_HANDOFF_SUMMARY_SCHEMA = {
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "scenario_id": pl.String,
    "run_id": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "planned_zone_count": pl.Int64,
    "planned_zone_ids": pl.String,
    "telemetry_available": pl.Boolean,
    "cue_fire_rate": pl.Float64,
    "cue_on_time_rate": pl.Float64,
    "mean_cue_error_m": pl.Float64,
    "median_abs_cue_error_m": pl.Float64,
    "max_abs_cue_error_m": pl.Float64,
    "zone_execution_rate": pl.Float64,
    "executed_zone_count": pl.Int64,
    "expected_fuel_saved_total_l": pl.Float64,
    "actual_fuel_saved_total_l": pl.Float64,
    "fuel_saved_total_error_l": pl.Float64,
    "expected_time_lost_total_s": pl.Float64,
    "actual_time_lost_total_s": pl.Float64,
    "time_lost_total_error_s": pl.Float64,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "next_lap_expected_fuel_saved_l": pl.Float64,
    "next_lap_expected_time_lost_s": pl.Float64,
    "next_lap_driver_fuel_execution_scale": pl.Float64,
    "next_lap_driver_time_execution_scale": pl.Float64,
    "next_lap_driver_zone_execution_scale_count": pl.Int64,
}

_REPLAY_ZONE_SUMMARY_COLUMNS = [
    "variant_name",
    "planning_mode",
    "zone_id",
    "display_label",
    "source_model_status",
    "sample_count",
    "telemetry_available_rate",
    "cue_fire_rate",
    "cue_on_time_rate",
    "mean_cue_error_m",
    "median_abs_cue_error_m",
    "zone_execution_rate",
    "mean_expected_fuel_saved_l",
    "mean_actual_fuel_saved_l",
    "mean_fuel_saved_error_l",
    "mean_expected_time_lost_s",
    "mean_actual_time_lost_s",
    "mean_time_lost_error_s",
]

_REPLAY_ZONE_SUMMARY_SCHEMA = {
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "source_model_status": pl.String,
    "sample_count": pl.Int64,
    "telemetry_available_rate": pl.Float64,
    "cue_fire_rate": pl.Float64,
    "cue_on_time_rate": pl.Float64,
    "mean_cue_error_m": pl.Float64,
    "median_abs_cue_error_m": pl.Float64,
    "zone_execution_rate": pl.Float64,
    "mean_expected_fuel_saved_l": pl.Float64,
    "mean_actual_fuel_saved_l": pl.Float64,
    "mean_fuel_saved_error_l": pl.Float64,
    "mean_expected_time_lost_s": pl.Float64,
    "mean_actual_time_lost_s": pl.Float64,
    "mean_time_lost_error_s": pl.Float64,
}

_REPLAY_TELEMETRY_STATUS_SCHEMA = {
    "plan_id": pl.String,
    "telemetry_available": pl.Boolean,
}
