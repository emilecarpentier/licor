from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Protocol

import polars as pl

from licor.analysis import (
    LiveCueRunnerConfig,
    load_live_cue_plan,
    summarize_live_cue_event_accuracy,
)
from licor.live.audio import AudioCue, AudioCueAdapter, NullAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample, LMUSharedMemoryReader


@dataclass(frozen=True)
class LiveStaticCueSessionConfig(LiveCueRunnerConfig):
    update_timeout_ms: int = 250
    write_accuracy_log: bool = True
    overwrite_existing_logs: bool = False
    max_laps: int | None = None
    max_events: int | None = None
    cue_lap_numbers: tuple[int, ...] | None = None
    stop_after_lap_number: int | None = None


class LiveTelemetrySampleSource(Protocol):
    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample | None:
        """Read the next available live telemetry sample."""

    def close(self) -> None:
        """Release any open resources."""


class LMUSharedMemorySampleSource:
    def __init__(self, reader: LMUSharedMemoryReader) -> None:
        self._reader = reader

    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample | None:
        return self._reader.read_next_player_sample(timeout_ms=timeout_ms)

    def close(self) -> None:
        self._reader.close()


def run_static_live_cue_session(
    *,
    plan_path: str | Path,
    event_log_path: str | Path,
    accuracy_log_path: str | Path | None = None,
    telemetry_log_path: str | Path | None = None,
    sample_source: LiveTelemetrySampleSource,
    audio_adapter: AudioCueAdapter | None = None,
    config: LiveStaticCueSessionConfig | None = None,
) -> pl.DataFrame:
    session_config = config or LiveStaticCueSessionConfig()
    plan = load_live_cue_plan(plan_path)
    runtime = _LiveCueRuntime(plan, config=session_config)
    event_path = _prepare_csv_output(
        event_log_path,
        overwrite_existing=session_config.overwrite_existing_logs,
        header=_LIVE_CUE_EVENT_LOG_COLUMNS,
    )
    emitted_rows: list[dict[str, object]] = []
    adapter = audio_adapter or NullAudioCueAdapter()
    telemetry_handle = None

    try:
        if telemetry_log_path is not None:
            telemetry_columns = [field.name for field in fields(LmuLiveTelemetrySample)]
            telemetry_path = _prepare_csv_output(
                telemetry_log_path,
                overwrite_existing=session_config.overwrite_existing_logs,
                header=telemetry_columns,
            )
            telemetry_handle = telemetry_path.open("a", newline="", encoding="utf-8")
            telemetry_writer = csv.DictWriter(
                telemetry_handle, fieldnames=telemetry_columns
            )
            telemetry_count = 0
        while True:
            sample = sample_source.read_next_sample(
                timeout_ms=session_config.update_timeout_ms
            )
            if sample is None:
                continue
            if telemetry_handle is not None:
                telemetry_writer.writerow(asdict(sample))
                telemetry_count += 1
                if telemetry_count % 100 == 0:
                    telemetry_handle.flush()
            for event in runtime.process_sample(sample):
                _append_csv_row(
                    event_path, header=_LIVE_CUE_EVENT_LOG_COLUMNS, row=event
                )
                emitted_rows.append(event)
                if not event["cue_enabled"]:
                    continue
                adapter.emit(
                    AudioCue(
                        plan_id=str(event["plan_id"]),
                        zone_id=str(event["zone_id"]),
                        display_label=str(event["display_label"]),
                        lap_number=int(event["lap_number"]),
                        trigger_status=str(event["trigger_status"]),
                        audio_cue_kind=str(event["audio_cue_kind"]),
                    )
                )
            if runtime.should_stop():
                break
    except KeyboardInterrupt:
        pass
    finally:
        if telemetry_handle is not None:
            telemetry_handle.close()
        sample_source.close()

    events = (
        pl.DataFrame(
            emitted_rows, schema=_LIVE_CUE_EVENT_LOG_SCHEMA, strict=False
        ).select(_LIVE_CUE_EVENT_LOG_COLUMNS)
        if emitted_rows
        else pl.DataFrame(schema=_LIVE_CUE_EVENT_LOG_SCHEMA)
    )
    if session_config.write_accuracy_log:
        accuracy_path = accuracy_log_path or _default_accuracy_log_path(event_path)
        accuracy = summarize_live_cue_event_accuracy(
            events.filter(pl.col("cue_enabled"))
        )
        _write_frame(
            accuracy,
            accuracy_path,
            overwrite_existing=session_config.overwrite_existing_logs,
        )
    return events


def run_lmu_static_live_cue_session(
    *,
    plan_path: str | Path,
    event_log_path: str | Path,
    accuracy_log_path: str | Path | None = None,
    telemetry_log_path: str | Path | None = None,
    audio_adapter: AudioCueAdapter | None = None,
    config: LiveStaticCueSessionConfig | None = None,
) -> pl.DataFrame:
    sample_source = LMUSharedMemorySampleSource(LMUSharedMemoryReader())
    return run_static_live_cue_session(
        plan_path=plan_path,
        event_log_path=event_log_path,
        accuracy_log_path=accuracy_log_path,
        telemetry_log_path=telemetry_log_path,
        sample_source=sample_source,
        audio_adapter=audio_adapter,
        config=config,
    )


class _LiveCueRuntime:
    def __init__(
        self, live_cue_plan: pl.DataFrame, *, config: LiveStaticCueSessionConfig
    ) -> None:
        self._config = config
        self._cues = list(live_cue_plan.sort("cue_distance_m").iter_rows(named=True))
        self._track_length_m = _track_length_m(live_cue_plan, config.track_length_m)
        self._triggered_by_lap: dict[int, set[tuple[str, str]]] = {}
        self._previous_by_lap: dict[int, LmuLiveTelemetrySample] = {}
        self._sample_index = 0
        self._event_count = 0
        self._first_lap_number: int | None = None
        self._max_lap_seen: int | None = None

    def process_sample(self, sample: LmuLiveTelemetrySample) -> list[dict[str, object]]:
        if self._first_lap_number is None:
            self._first_lap_number = sample.lap_number
        self._max_lap_seen = (
            sample.lap_number
            if self._max_lap_seen is None
            else max(self._max_lap_seen, sample.lap_number)
        )
        if (
            self._config.stop_after_lap_number is not None
            and sample.lap_number > self._config.stop_after_lap_number
        ):
            return []

        previous_sample = self._previous_by_lap.get(sample.lap_number)
        triggered_zones = self._triggered_by_lap.setdefault(sample.lap_number, set())
        events: list[dict[str, object]] = []

        for cue in self._cues:
            cue_key = (str(cue["plan_id"]), str(cue["zone_id"]))
            if cue_key in triggered_zones:
                continue
            if not _should_trigger_cue(
                cue_distance_m=float(cue["cue_distance_m"]),
                previous_distance_m=None
                if previous_sample is None
                else previous_sample.lap_distance_m,
                current_distance_m=sample.lap_distance_m,
                track_length_m=self._track_length_m,
                max_initial_late_distance_m=self._config.max_initial_late_distance_m,
            ):
                continue
            triggered_zones.add(cue_key)
            event = _cue_event_row(
                cue,
                sample,
                sample_index=self._sample_index,
                config=self._config,
                track_length_m=self._track_length_m,
            )
            events.append(event)
            self._event_count += 1

        self._sample_index += 1
        self._previous_by_lap[sample.lap_number] = sample
        return events

    def should_stop(self) -> bool:
        if (
            self._config.stop_after_lap_number is not None
            and self._max_lap_seen is not None
            and self._max_lap_seen > self._config.stop_after_lap_number
        ):
            return True
        if (
            self._config.max_events is not None
            and self._event_count >= self._config.max_events
        ):
            return True
        if (
            self._config.max_laps is not None
            and self._first_lap_number is not None
            and self._max_lap_seen is not None
            and (self._max_lap_seen - self._first_lap_number + 1)
            > self._config.max_laps
        ):
            return True
        return False


def _cue_event_row(
    cue: dict[str, object],
    sample: LmuLiveTelemetrySample,
    *,
    sample_index: int,
    config: LiveStaticCueSessionConfig,
    track_length_m: float | None,
) -> dict[str, object]:
    cue_distance_m = float(cue["cue_distance_m"])
    cue_tolerance_m = float(
        cue.get("cue_tolerance_m") or config.default_cue_tolerance_m
    )
    cue_error_m = _signed_distance_delta_m(
        sample.lap_distance_m,
        cue_distance_m,
        track_length_m=track_length_m,
    )
    return {
        "schema_version": 1,
        "plan_id": str(cue["plan_id"]),
        "file_name": config.file_name,
        "run_id": config.run_id,
        "lap_number": sample.lap_number,
        "zone_id": str(cue["zone_id"]),
        "display_label": str(cue["display_label"]),
        "cue_trigger_m": cue_distance_m,
        "planned_lift_start_m": float(cue["planned_lift_start_m"]),
        "actual_cue_distance_m": sample.lap_distance_m,
        "cue_error_m": cue_error_m,
        "cue_tolerance_m": cue_tolerance_m,
        "trigger_status": _trigger_status(cue_error_m, cue_tolerance_m),
        "sample_index": sample_index,
        "sample_ts": sample.ts,
        "sample_elapsed_s": sample.elapsed_s,
        "audio_cue_kind": config.audio_cue_kind,
        "cue_enabled": (
            config.cue_lap_numbers is None
            or sample.lap_number in config.cue_lap_numbers
        ),
        "notes": str(cue.get("notes") or ""),
    }


def _should_trigger_cue(
    *,
    cue_distance_m: float,
    previous_distance_m: float | None,
    current_distance_m: float,
    track_length_m: float | None,
    max_initial_late_distance_m: float,
) -> bool:
    if previous_distance_m is None:
        return 0.0 <= current_distance_m - cue_distance_m <= max_initial_late_distance_m
    if current_distance_m >= previous_distance_m:
        return previous_distance_m < cue_distance_m <= current_distance_m
    if track_length_m is None:
        return False
    return cue_distance_m > previous_distance_m or cue_distance_m <= current_distance_m


def _signed_distance_delta_m(
    actual_m: float,
    planned_m: float,
    *,
    track_length_m: float | None,
) -> float:
    delta_m = actual_m - planned_m
    if track_length_m is None:
        return delta_m
    half_track_m = track_length_m / 2.0
    return ((delta_m + half_track_m) % track_length_m) - half_track_m


def _trigger_status(cue_error_m: float, cue_tolerance_m: float) -> str:
    if abs(cue_error_m) <= cue_tolerance_m:
        return "fired_on_time"
    if cue_error_m < 0.0:
        return "fired_early"
    return "fired_late"


def _track_length_m(
    live_cue_plan: pl.DataFrame, config_track_length_m: float | None
) -> float | None:
    if "track_length_m" not in live_cue_plan.columns:
        return config_track_length_m
    non_null = [
        float(value) for value in live_cue_plan["track_length_m"].drop_nulls().to_list()
    ]
    if not non_null:
        return config_track_length_m
    track_lengths = set(non_null)
    if len(track_lengths) != 1:
        raise ValueError("live cue plan track_length_m values must be consistent")
    plan_track_length_m = next(iter(track_lengths))
    if (
        config_track_length_m is not None
        and abs(config_track_length_m - plan_track_length_m) > 1e-9
    ):
        raise ValueError("config track_length_m conflicts with live cue plan")
    return plan_track_length_m


def _prepare_csv_output(
    path: str | Path,
    *,
    overwrite_existing: bool,
    header: list[str],
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite_existing:
        raise FileExistsError(f"refusing to overwrite existing log: {output_path}")
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=header).writeheader()
    return output_path


def _append_csv_row(path: Path, *, header: list[str], row: dict[str, object]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writerow(row)


def _write_frame(
    frame: pl.DataFrame, path: str | Path, *, overwrite_existing: bool
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite_existing:
        raise FileExistsError(f"refusing to overwrite existing log: {output_path}")
    frame.write_csv(output_path)
    return output_path


def _default_accuracy_log_path(event_log_path: str | Path) -> Path:
    path = Path(event_log_path)
    return path.with_name(f"{path.stem}_accuracy{path.suffix}")


_LIVE_CUE_EVENT_LOG_COLUMNS = [
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
    "cue_enabled",
    "notes",
]

_LIVE_CUE_EVENT_LOG_SCHEMA = {
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
    "cue_enabled": pl.Boolean,
    "notes": pl.String,
}
