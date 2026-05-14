# Architecture

LICOR is organized as an offline telemetry pipeline first. Live telemetry,
overlays, and audio cues are future layers that should consume the same core
analysis functions after they are validated offline.

## Data Flow

1. Read LMU telemetry DuckDB files.
2. Optionally validate available signals against the versioned LMU telemetry
   reference config.
3. Extract session metadata, channel definitions, event definitions, and raw
   telemetry series.
4. Reconstruct timestamps for fixed-frequency channels.
5. Normalize LMU channel names into LICOR internal column names.
6. Split the session into lap intervals.
7. Exclude out-laps, in-laps, warm-up laps, and invalid laps.
8. Compute lap summaries and fuel usage as sanity checks.
9. Detect braking zones.
10. Build driver-reviewed track zones around approach, LICO, braking, corner,
    and stabilization phases.
11. Compare push and LICO behavior inside each zone.
12. Rank zone-level recommendations by fuel saved versus local time lost.
13. Feed zone-level fuel/time curves into race strategy and pit stop analysis.

## Modules

- ingestion: read LMU telemetry DuckDB files and expose raw channels/events.
- preprocessing: clean, align, resample, normalize, and validate telemetry.
- analysis: compute fuel, lap, braking, and LICO metrics.
- optimization: choose best lift zones for a fuel target.
- reports: generate summaries, plots, and tables.
- app: Streamlit dashboard after the core pipeline works.
- live: future live telemetry support.

## Strategy Layer

The LICO model should eventually connect to a race strategy layer. Zone-level
analysis estimates how expensive it is to save fuel. Strategy analysis decides
whether that saving is valuable enough to change the pit stop plan.

The first strategy use case is 100-minute ELMS LMP2 racing, where full-push fuel
consumption may require two stops on some circuits while a LICO plan may make
one stop possible.

Pit stop telemetry should be analyzed separately from LICO calibration telemetry.
It can estimate pit lane commitment time, stationary time, refill duration, fuel
added, and observed refill rate.

## LMU DuckDB Ingestion

LMU telemetry files are DuckDB databases with three structural tables:

- `metadata`: session-level key/value information.
- `channelsList`: fixed-frequency channels, their sampling rate, and units.
- `eventsList`: event-style signals and their units.

Fixed-frequency channels such as `Ground Speed`, `Brake Pos`, and `Fuel Level`
do not contain a timestamp column. Their timestamps must be reconstructed from
their sample index and frequency:

```text
ts = session_start_ts + sample_index / frequency_hz
```

Event tables such as `Lap`, `Lap Time`, `Gear`, and `In Pits` contain their own
`ts` column.

The first implementation lives in `src/licor/ingestion/duckdb_reader.py`.

The project also keeps `config/lmu_telemetry_config.reference.json`, copied from
LMU's telemetry folder. This file defines the expected channel/event inventory
and sampling frequencies before a `.duckdb` file is opened. Code for loading and
validating this reference lives in `src/licor/ingestion/lmu_config.py`.

## Current Assumptions

- `Lap` events are the best initial anchor for `session_start_ts`.
- Consecutive `Lap` events define lap intervals.
- Full-lap metrics are sanity checks, not the primary LICO optimization target.
- The primary analysis unit is a causal track zone: approach, LICO window,
  braking, corner/complex, and exit stabilization point.
- Race strategy is the reason to optimize LICO. Zone-level recommendations must
  eventually be evaluated against pit stop costs and race length.
- Raw telemetry files stay outside Git.
- Continuous channel alignment should happen in preprocessing, not ingestion.
- Driver intent labels should be stored separately from raw telemetry.
