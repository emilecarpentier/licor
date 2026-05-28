from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class DataReadinessConfig:
    valid_labels: tuple[str, ...] = ("valid",)
    clean_execution_labels: tuple[str, ...] = ("clean", "unknown", "")
    baseline_collection_designs: tuple[str, ...] = ("baseline",)
    baseline_lico_intensities: tuple[str, ...] = ("none",)
    lico_collection_designs: tuple[str, ...] = (
        "controlled_random",
        "targeted_zone",
        "recommendation_execution",
    )
    distance_bin_size_m: float = 25.0
    min_valid_passes_per_zone: int = 6
    min_baseline_passes_per_zone: int = 3
    min_lico_passes_per_zone: int = 3
    min_lico_distance_bins_per_zone: int = 3


def summarize_zone_data_readiness(
    zone_passes: pl.DataFrame,
    *,
    config: DataReadinessConfig | None = None,
) -> pl.DataFrame:
    """Summarize whether each zone has enough evidence for Spa v2 curve updates."""

    readiness_config = config or DataReadinessConfig()
    if zone_passes.is_empty():
        return empty_zone_data_readiness_frame()
    _validate_zone_pass_columns(zone_passes)

    rows = []
    for zone in _zone_rows(zone_passes):
        raw_zone_frame = zone_passes.filter(pl.col("zone_id") == zone["zone_id"])
        zone_frame = _clean_zone_passes(
            raw_zone_frame,
            config=readiness_config,
        )
        rows.append(
            _zone_readiness_row(
                zone,
                raw_zone_frame,
                zone_frame,
                config=readiness_config,
            )
        )

    return pl.DataFrame(rows, schema=_ZONE_DATA_READINESS_SCHEMA, strict=False).select(
        _ZONE_DATA_READINESS_COLUMNS
    )


def summarize_collection_protocol_readiness(
    zone_passes: pl.DataFrame,
    protocol_sessions: pl.DataFrame,
    *,
    live_cue_events: pl.DataFrame | None = None,
    config: DataReadinessConfig | None = None,
) -> pl.DataFrame:
    """Summarize observed clean-lap coverage against a collection protocol."""

    readiness_config = config or DataReadinessConfig()
    if protocol_sessions.is_empty():
        return empty_collection_protocol_readiness_frame()
    _validate_protocol_session_columns(protocol_sessions)
    if not zone_passes.is_empty():
        _validate_zone_pass_columns(zone_passes)

    rows = []
    for session in protocol_sessions.iter_rows(named=True):
        rows.append(
            _protocol_session_readiness_row(
                session,
                zone_passes,
                live_cue_events=live_cue_events,
                config=readiness_config,
            )
        )
    return pl.DataFrame(
        rows,
        schema=_COLLECTION_PROTOCOL_READINESS_SCHEMA,
        strict=False,
    ).select(_COLLECTION_PROTOCOL_READINESS_COLUMNS)


def empty_zone_data_readiness_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_DATA_READINESS_SCHEMA)


def empty_collection_protocol_readiness_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_COLLECTION_PROTOCOL_READINESS_SCHEMA)


def _zone_rows(zone_passes: pl.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "zone_id": row["zone_id"],
            "display_label": row["display_label"],
        }
        for row in zone_passes.select("zone_id", "display_label").unique().sort("zone_id").iter_rows(named=True)
    ]


def _clean_zone_passes(
    zone_passes: pl.DataFrame,
    *,
    config: DataReadinessConfig,
) -> pl.DataFrame:
    frame = zone_passes.filter(pl.col("validity_label").is_in(config.valid_labels))
    if "execution_quality" in frame.columns:
        frame = frame.filter(
            pl.col("execution_quality")
            .fill_null("unknown")
            .is_in(config.clean_execution_labels)
        )
    return frame


def _zone_readiness_row(
    zone: dict[str, Any],
    raw_zone_frame: pl.DataFrame,
    zone_frame: pl.DataFrame,
    *,
    config: DataReadinessConfig,
) -> dict[str, Any]:
    baseline = _baseline_passes(zone_frame, config=config)
    lico = _lico_candidate_passes(zone_frame, config=config)
    distance_bins = _lico_distance_bins(lico, config=config)
    collection_designs = _unique_strings(zone_frame, "collection_design")
    if "collection_design" not in zone_frame.columns and not collection_designs:
        collection_designs = _unique_strings(zone_frame, "lico_intensity")
    if _has_collection_design_metadata(zone_frame):
        collection_designs = _non_empty_unique_strings(zone_frame, "collection_design")
    elif "lico_intensity" in zone_frame.columns:
        collection_designs = _unique_strings(zone_frame, "lico_intensity")

    metrics = {
        "total_pass_count": raw_zone_frame.height,
        "valid_pass_count": zone_frame.height,
        "invalid_pass_count": raw_zone_frame.height - zone_frame.height,
        "unique_run_count": _unique_run_count(zone_frame),
        "unique_lap_count": _unique_lap_count(zone_frame),
        "baseline_pass_count": baseline.height,
        "lico_pass_count": _lico_candidate_passes(zone_frame, config=config).height,
        "controlled_random_pass_count": _design_count(zone_frame, "controlled_random"),
        "targeted_zone_pass_count": _design_count(zone_frame, "targeted_zone"),
        "recommendation_execution_pass_count": _design_count(
            zone_frame,
            "recommendation_execution",
        ),
        "lico_distance_bin_count": len(distance_bins),
        "min_lico_distance_before_brake_m": _optional_min(
            lico,
            "lico_start_distance_before_brake_m",
        ),
        "max_lico_distance_before_brake_m": _optional_max(
            lico,
            "lico_start_distance_before_brake_m",
        ),
        "collection_designs": collection_designs,
        "validity_labels": _unique_strings(raw_zone_frame, "validity_label"),
        "baseline_detected_lico_pass_count": baseline.filter(pl.col("has_lico")).height,
    }
    flags = _zone_readiness_flags(metrics, config=config)
    return {
        **zone,
        **metrics,
        "readiness_status": _zone_readiness_status(flags),
        "readiness_flags": flags,
    }


def _protocol_session_readiness_row(
    session: dict[str, Any],
    zone_passes: pl.DataFrame,
    *,
    live_cue_events: pl.DataFrame | None,
    config: DataReadinessConfig,
) -> dict[str, Any]:
    collection_design = str(session["collection_design"])
    target_zones = list(session.get("target_zones") or [])
    minimum_clean_laps = int(session["minimum_clean_laps"])
    if collection_design == "pitstop_validation":
        return _protocol_row(
            session,
            observed_clean_laps=0,
            observed_runs=0,
            observed_target_zones=[],
            observed_cue_event_count=0,
            readiness_status="not_applicable_to_zone_pass_readiness",
            readiness_flags=["pitstop_requires_pit_stop_observations"],
        )
    if (
        collection_design not in {"baseline"}
        and not zone_passes.is_empty()
        and not _has_collection_design_metadata(zone_passes)
    ):
        flags = ["missing_collection_design_metadata"]
        if session.get("target_zones_source"):
            flags.append(f"target_zones_source:{session['target_zones_source']}")
        return _protocol_row(
            session,
            observed_clean_laps=0,
            observed_runs=0,
            observed_target_zones=[],
            observed_cue_event_count=0,
            readiness_status="unlinked_metadata",
            readiness_flags=flags,
        )

    matching = _matching_protocol_passes(
        zone_passes,
        collection_design=collection_design,
        target_zones=target_zones,
        config=config,
    )
    observed_clean_laps = _unique_lap_count(matching)
    observed_runs = _unique_run_count(matching)
    observed_target_zones = _unique_strings(matching, "zone_id")
    expected_audio_cue_plan_ids = _expected_audio_cue_plan_ids(matching)
    expected_run_ids = _unique_strings(matching, "run_id")
    observed_cue_event_count, cue_link_flags = _matching_cue_event_count(
        live_cue_events,
        collection_design=collection_design,
        expected_audio_cue_plan_ids=expected_audio_cue_plan_ids,
        expected_run_ids=expected_run_ids,
    )
    flags = []
    if matching.is_empty():
        flags.append("no_matching_zone_passes")
    if session.get("target_zones_source"):
        flags.append(f"target_zones_source:{session['target_zones_source']}")
    if target_zones and not set(target_zones).issubset(set(observed_target_zones)):
        flags.append("missing_target_zone_observations")
    if observed_clean_laps < minimum_clean_laps:
        flags.append("below_minimum_clean_laps")
    readiness_status = "complete" if not flags else "needs_more_data"
    if collection_design == "recommendation_execution":
        if session.get("target_zones_source") == "from_exported_plan":
            flags.append("requires_exported_plan_targets")
        if not expected_audio_cue_plan_ids:
            flags.append("missing_audio_cue_plan_id")
        flags.extend(cue_link_flags)
        if observed_cue_event_count == 0:
            flags.append("missing_cue_event_logs")
        readiness_status = (
            "complete"
            if (
                observed_clean_laps >= minimum_clean_laps
                and observed_cue_event_count > 0
                and expected_audio_cue_plan_ids
                and not cue_link_flags
            )
            else "needs_plan_or_execution_logs"
        )

    return _protocol_row(
        session,
        observed_clean_laps=observed_clean_laps,
        observed_runs=observed_runs,
        observed_target_zones=observed_target_zones,
        observed_cue_event_count=observed_cue_event_count,
        readiness_status=readiness_status,
        readiness_flags=flags,
    )


def _matching_protocol_passes(
    zone_passes: pl.DataFrame,
    *,
    collection_design: str,
    target_zones: list[str],
    config: DataReadinessConfig,
) -> pl.DataFrame:
    if zone_passes.is_empty():
        return zone_passes
    frame = _clean_zone_passes(zone_passes, config=config)
    if _has_collection_design_metadata(frame):
        frame = frame.filter(pl.col("collection_design") == collection_design)
    elif collection_design == "baseline":
        frame = frame.filter(pl.col("lico_intensity").is_in(config.baseline_lico_intensities))
    else:
        return frame.head(0)
    if target_zones:
        frame = frame.filter(pl.col("zone_id").is_in(target_zones))
    return frame


def _protocol_row(
    session: dict[str, Any],
    *,
    observed_clean_laps: int,
    observed_runs: int,
    observed_target_zones: list[str],
    observed_cue_event_count: int,
    readiness_status: str,
    readiness_flags: list[str],
) -> dict[str, Any]:
    return {
        "protocol_id": session["protocol_id"],
        "session_id": session["session_id"],
        "collection_design": session["collection_design"],
        "target_zones": list(session.get("target_zones") or []),
        "target_zones_source": session.get("target_zones_source") or "",
        "minimum_clean_laps": int(session["minimum_clean_laps"]),
        "observed_clean_laps": observed_clean_laps,
        "observed_runs": observed_runs,
        "observed_target_zones": observed_target_zones,
        "observed_cue_event_count": observed_cue_event_count,
        "readiness_status": readiness_status,
        "readiness_flags": readiness_flags,
    }


def _baseline_passes(
    zone_frame: pl.DataFrame,
    *,
    config: DataReadinessConfig,
) -> pl.DataFrame:
    if zone_frame.is_empty():
        return zone_frame
    if _has_collection_design_metadata(zone_frame):
        return zone_frame.filter(pl.col("collection_design").is_in(config.baseline_collection_designs))
    return zone_frame.filter(pl.col("lico_intensity").is_in(config.baseline_lico_intensities))


def _lico_candidate_passes(
    zone_frame: pl.DataFrame,
    *,
    config: DataReadinessConfig,
) -> pl.DataFrame:
    frame = zone_frame.filter(pl.col("has_lico"))
    if not _has_collection_design_metadata(frame):
        return frame
    return frame.filter(pl.col("collection_design").is_in(config.lico_collection_designs))


def _lico_distance_bins(
    zone_frame: pl.DataFrame,
    *,
    config: DataReadinessConfig,
) -> set[float]:
    if zone_frame.is_empty():
        return set()
    distances = (
        zone_frame.filter(pl.col("lico_start_distance_before_brake_m").is_not_null())
        .with_columns(
            (
                (
                    pl.col("lico_start_distance_before_brake_m")
                    / config.distance_bin_size_m
                ).floor()
                * config.distance_bin_size_m
            ).alias("distance_bin_m")
        )["distance_bin_m"]
        .to_list()
    )
    return {float(distance) for distance in distances}


def _zone_readiness_flags(
    metrics: dict[str, Any],
    *,
    config: DataReadinessConfig,
) -> list[str]:
    flags = []
    if metrics["valid_pass_count"] < config.min_valid_passes_per_zone:
        flags.append("low_valid_pass_count")
    if metrics["baseline_pass_count"] < config.min_baseline_passes_per_zone:
        flags.append("needs_baseline_refresh")
    if metrics["lico_pass_count"] < config.min_lico_passes_per_zone:
        flags.append("needs_detected_lico_passes")
    if metrics["lico_distance_bin_count"] < config.min_lico_distance_bins_per_zone:
        flags.append("needs_lico_distance_variation")
    if not metrics["collection_designs"]:
        flags.append("missing_collection_design_context")
    if metrics["invalid_pass_count"] > 0:
        flags.append("has_invalid_or_filtered_passes")
    if metrics["baseline_detected_lico_pass_count"] > 0:
        flags.append("baseline_contains_detected_lico")
    return flags


def _zone_readiness_status(flags: list[str]) -> str:
    if not flags:
        return "ready_for_curve_update"
    if "needs_baseline_refresh" in flags:
        return "needs_baseline"
    if "needs_detected_lico_passes" in flags:
        return "needs_lico_samples"
    if "needs_lico_distance_variation" in flags:
        return "needs_distance_variation"
    return "needs_review"


def _design_count(zone_frame: pl.DataFrame, design: str) -> int:
    if not _has_collection_design_metadata(zone_frame):
        return 0
    return zone_frame.filter(pl.col("collection_design") == design).height


def _has_collection_design_metadata(frame: pl.DataFrame) -> bool:
    if "collection_design" not in frame.columns:
        return False
    return bool(_non_empty_unique_strings(frame, "collection_design"))


def _matching_cue_event_count(
    live_cue_events: pl.DataFrame | None,
    *,
    collection_design: str,
    expected_audio_cue_plan_ids: list[str],
    expected_run_ids: list[str],
) -> tuple[int, list[str]]:
    if collection_design != "recommendation_execution":
        return 0, []
    if live_cue_events is None or live_cue_events.is_empty():
        return 0, []
    flags = []
    frame = live_cue_events
    if expected_audio_cue_plan_ids:
        if "plan_id" not in frame.columns:
            return 0, ["cue_logs_missing_plan_id"]
        frame = frame.filter(pl.col("plan_id").is_in(expected_audio_cue_plan_ids))
        if frame.is_empty():
            return 0, ["cue_logs_do_not_match_audio_cue_plan_id"]
    if expected_run_ids and "run_id" in frame.columns:
        frame = frame.filter(pl.col("run_id").is_in(expected_run_ids))
        if frame.is_empty():
            return 0, ["cue_logs_do_not_match_run_id"]
    return frame.height, flags


def _expected_audio_cue_plan_ids(frame: pl.DataFrame) -> list[str]:
    if frame.is_empty() or "audio_cue_plan_id" not in frame.columns:
        return []
    return _non_empty_unique_strings(frame, "audio_cue_plan_id")


def _unique_run_count(frame: pl.DataFrame) -> int:
    if frame.is_empty() or "run_id" not in frame.columns:
        return 0
    return frame.filter(pl.col("run_id").is_not_null()).select("run_id").unique().height


def _unique_lap_count(frame: pl.DataFrame) -> int:
    if frame.is_empty():
        return 0
    columns = [column for column in ("run_id", "lap_number") if column in frame.columns]
    if not columns:
        return 0
    return frame.select(columns).unique().height


def _unique_strings(frame: pl.DataFrame, column: str) -> list[str]:
    if frame.is_empty() or column not in frame.columns:
        return []
    return sorted(str(value) for value in frame[column].drop_nulls().unique().to_list())


def _non_empty_unique_strings(frame: pl.DataFrame, column: str) -> list[str]:
    return [
        value
        for value in _unique_strings(frame, column)
        if value.strip()
    ]


def _optional_min(frame: pl.DataFrame, column: str) -> float | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    value = frame[column].drop_nulls().min()
    return None if value is None else float(value)


def _optional_max(frame: pl.DataFrame, column: str) -> float | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    value = frame[column].drop_nulls().max()
    return None if value is None else float(value)


def _validate_zone_pass_columns(zone_passes: pl.DataFrame) -> None:
    required_columns = {
        "zone_id",
        "display_label",
        "run_id",
        "lap_number",
        "lico_intensity",
        "has_lico",
        "lico_start_distance_before_brake_m",
        "validity_label",
    }
    missing_columns = required_columns - set(zone_passes.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"zone_passes missing required columns: {missing}")


def _validate_protocol_session_columns(protocol_sessions: pl.DataFrame) -> None:
    required_columns = {
        "protocol_id",
        "session_id",
        "collection_design",
        "target_zones",
        "target_zones_source",
        "minimum_clean_laps",
    }
    missing_columns = required_columns - set(protocol_sessions.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"protocol_sessions missing required columns: {missing}")


_ZONE_DATA_READINESS_COLUMNS = [
    "zone_id",
    "display_label",
    "total_pass_count",
    "valid_pass_count",
    "invalid_pass_count",
    "unique_run_count",
    "unique_lap_count",
    "baseline_pass_count",
    "lico_pass_count",
    "controlled_random_pass_count",
    "targeted_zone_pass_count",
    "recommendation_execution_pass_count",
    "lico_distance_bin_count",
    "min_lico_distance_before_brake_m",
    "max_lico_distance_before_brake_m",
    "collection_designs",
    "validity_labels",
    "baseline_detected_lico_pass_count",
    "readiness_status",
    "readiness_flags",
]

_ZONE_DATA_READINESS_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "total_pass_count": pl.Int64,
    "valid_pass_count": pl.Int64,
    "invalid_pass_count": pl.Int64,
    "unique_run_count": pl.Int64,
    "unique_lap_count": pl.Int64,
    "baseline_pass_count": pl.Int64,
    "lico_pass_count": pl.Int64,
    "controlled_random_pass_count": pl.Int64,
    "targeted_zone_pass_count": pl.Int64,
    "recommendation_execution_pass_count": pl.Int64,
    "lico_distance_bin_count": pl.Int64,
    "min_lico_distance_before_brake_m": pl.Float64,
    "max_lico_distance_before_brake_m": pl.Float64,
    "collection_designs": pl.List(pl.String),
    "validity_labels": pl.List(pl.String),
    "baseline_detected_lico_pass_count": pl.Int64,
    "readiness_status": pl.String,
    "readiness_flags": pl.List(pl.String),
}

_COLLECTION_PROTOCOL_READINESS_COLUMNS = [
    "protocol_id",
    "session_id",
    "collection_design",
    "target_zones",
    "target_zones_source",
    "minimum_clean_laps",
    "observed_clean_laps",
    "observed_runs",
    "observed_target_zones",
    "observed_cue_event_count",
    "readiness_status",
    "readiness_flags",
]

_COLLECTION_PROTOCOL_READINESS_SCHEMA = {
    "protocol_id": pl.String,
    "session_id": pl.String,
    "collection_design": pl.String,
    "target_zones": pl.List(pl.String),
    "target_zones_source": pl.String,
    "minimum_clean_laps": pl.Int64,
    "observed_clean_laps": pl.Int64,
    "observed_runs": pl.Int64,
    "observed_target_zones": pl.List(pl.String),
    "observed_cue_event_count": pl.Int64,
    "readiness_status": pl.String,
    "readiness_flags": pl.List(pl.String),
}
