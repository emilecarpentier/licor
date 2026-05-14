# LMU DuckDB Telemetry Format

This document records what LICOR learned from an observed Le Mans Ultimate
telemetry file exported for Spa, LMP2, Practice. The file itself should remain
outside Git.

Performance-specific lap time is intentionally not part of this document. The
goal here is to capture file structure, schema, units, and ingestion rules.

The project also stores a versioned reference copy of LMU's telemetry
configuration at `config/lmu_telemetry_config.reference.json`. That JSON file
contains channel/event names and sampling frequencies, while each DuckDB file
contains the same inventory plus session-specific tables, units, metadata, and
values.

## Database Shape

Observed structure:

- 101 total tables.
- 58 fixed-frequency channels listed in `channelsList`.
- 40 event signals listed in `eventsList`.
- 11 metadata keys listed in `metadata`.

## Structural Tables

### `metadata`

Schema:

| Column | Type | Notes |
| --- | --- | --- |
| `key` | `VARCHAR` | Primary key. |
| `value` | `VARCHAR` | Metadata value. |

Observed metadata keys:

- `Version`
- `DriverName`
- `SteamID`
- `RecordingTime`
- `SessionTime`
- `SessionType`
- `TrackName`
- `TrackLayout`
- `CarName`
- `CarClass`
- `WeatherConditions`

### `channelsList`

Schema:

| Column | Type | Notes |
| --- | --- | --- |
| `channelName` | `VARCHAR` | Primary key. |
| `frequency` | `INTEGER` | Sampling frequency in Hz. |
| `unit` | `VARCHAR` | Unit string. |

Rows in `channelsList` correspond to fixed-frequency tables that generally do
not contain `ts`.

### `eventsList`

Schema:

| Column | Type | Notes |
| --- | --- | --- |
| `eventName` | `VARCHAR` | Primary key. |
| `unit` | `VARCHAR` | Unit string. |

Rows in `eventsList` correspond to event tables that generally contain `ts`.

## Reference Config JSON

Observed source path in a local LMU installation:

```text
C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry/config.json
```

Versioned project copy:

```text
config/lmu_telemetry_config.reference.json
```

Top-level structure:

```text
Channels -> channel key -> Name, Frequency
Events -> event key -> Name
```

This reference config does not include units. Units are available from
`channelsList` and `eventsList` inside each DuckDB telemetry file.

The reference config should be used for:

- validating whether a telemetry file has all expected channels and events;
- detecting frequency changes after LMU updates;
- keeping Codex/ChatGPT grounded in the native LMU signal names;
- regenerating or checking `docs/lmu_channels.md`.

## Fixed-Frequency Channels

Observed fixed-frequency tables store values without explicit timestamps. The
time axis must be reconstructed:

```text
ts = session_start_ts + sample_index / frequency_hz
elapsed_s = sample_index / frequency_hz
```

`session_start_ts` is currently inferred from the first `Lap.ts` event.

Single-value channels use this schema:

| Column | Type |
| --- | --- |
| `value` | `FLOAT` or `BOOLEAN` |

Wheel/corner channels usually use this schema:

| Column | Type |
| --- | --- |
| `value1` | numeric |
| `value2` | numeric |
| `value3` | numeric |
| `value4` | numeric |

The wheel ordering for `value1` to `value4` still needs to be confirmed.

## Event Tables

Most event tables use this schema:

| Column | Type |
| --- | --- |
| `ts` | `DOUBLE` |
| `value` | signal-specific type |

Some event tables contain `value1` to `value4`, for example tyre compound or
wheel detached state.

`Lap` events define lap boundaries. Consecutive `Lap` events can be interpreted
as intervals:

```text
lap_start_ts = Lap[i].ts
lap_end_ts = Lap[i + 1].ts
lap_duration_s = lap_end_ts - lap_start_ts
```

## Critical LICOR Channels

The MVP should depend on these channels first:

| LMU table | Kind | Frequency | Unit | LICOR use |
| --- | --- | ---: | --- | --- |
| `Fuel Level` | fixed | 20 Hz | L | Fuel usage per lap. |
| `Throttle Pos` | fixed | 50 Hz | % | Lift/coast detection. |
| `Brake Pos` | fixed | 50 Hz | % | Braking zone detection. |
| `Ground Speed` | fixed | 100 Hz | km/h | Speed profile. |
| `Lap Dist` | fixed | 10 Hz | m | Distance-based zone location. |
| `Total Dist` | fixed | 10 Hz | m | Session-level distance. |
| `Engine RPM` | fixed | 100 Hz | RPM | Validation/context. |
| `Steering Pos` | fixed | 100 Hz | % | Cornering context. |
| `Lap` | event | n/a | count | Lap intervals. |
| `Lap Time` | event | n/a | s | Completed lap timing metadata. |
| `In Pits` | event | n/a | boolean | Out-lap/in-lap filtering. |
| `Gear` | event | n/a | integer | Driving context. |

## Ingestion Responsibilities

The ingestion layer should:

- open DuckDB files read-only;
- list metadata, channels, events, and schemas;
- reconstruct timestamps for fixed-frequency channels;
- expose event tables with `elapsed_s`;
- infer lap intervals from `Lap`;
- avoid filtering or aligning channels prematurely.

The preprocessing layer should:

- align channels onto a common analysis frequency;
- normalize raw LMU names into LICOR column names;
- assign each sample to a lap interval;
- filter invalid laps.
