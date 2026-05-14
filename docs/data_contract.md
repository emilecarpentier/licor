# LICOR Core Telemetry Schema

This document defines the normalized internal schema LICOR should use after
reading raw LMU telemetry. Raw LMU channel names should be translated into these
stable names before analysis.

The expected raw LMU channel/event inventory is versioned in
`config/lmu_telemetry_config.reference.json`. That file should be used to detect
missing signals or frequency changes after LMU updates.

## Required Session Metadata

These fields should be captured when available:

- `recording_time`
- `session_type`
- `track_name`
- `track_layout`
- `car_name`
- `car_class`
- `weather_conditions`

The source DuckDB file may include additional fields such as driver name,
SteamID, and session clock time. These are useful for traceability but should not
be required by the analysis pipeline.

## Required Normalized Channels

| Internal name | LMU source | Unit | Type | Notes |
| --- | --- | --- | --- | --- |
| `ts` | reconstructed or event `ts` | s | float | Absolute session timestamp. |
| `elapsed_s` | derived | s | float | Seconds since `session_start_ts`. |
| `lap_number` | `Lap` | count | int | Derived from lap intervals. |
| `lap_distance_m` | `Lap Dist` | m | float | Distance from current lap start. |
| `total_distance_m` | `Total Dist` | m | float | Distance since recording start. |
| `fuel_level_l` | `Fuel Level` | L | float | Used to compute fuel burn. |
| `throttle_pct` | `Throttle Pos` | % | float | Driver throttle input. |
| `brake_pct` | `Brake Pos` | % | float | Driver brake input. |
| `ground_speed_kph` | `Ground Speed` | km/h | float | Main speed channel for reports. |
| `engine_rpm` | `Engine RPM` | RPM | float | Useful for validation. |
| `steering_pct` | `Steering Pos` | % | float | Useful for corner/phase detection. |

## Optional Normalized Channels

| Internal name | LMU source | Unit | Notes |
| --- | --- | --- | --- |
| `gps_speed_mps` | `GPS Speed` | m/s | Cross-check for `Ground Speed`. |
| `gear` | `Gear` | integer | Event-style table in observed LMU files. |
| `g_lat` | `G Force Lat` | G | Cornering phase detection. |
| `g_long` | `G Force Long` | G | Braking/acceleration validation. |
| `path_lateral_m` | `Path Lateral` | m | Track position signal. |
| `track_edge_m` | `Track Edge` | m | Track-limit/context signal. |
| `tyre_wear_pct_fl` | `Tyres Wear.value1` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_fr` | `Tyres Wear.value2` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_rl` | `Tyres Wear.value3` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_rr` | `Tyres Wear.value4` | % | Wheel ordering must be confirmed. |

## Core Raw Channels

- Fuel Level
- Throttle Pos
- Brake Pos
- Ground Speed
- Lap Dist
- Steering Pos
- Engine RPM

## Core Raw Events

- Lap
- Lap Time
- Current Sector
- Gear

## Valid Lap Rules

A valid analysis lap should initially satisfy:

- lap has a start and end `Lap` event;
- lap is not the out-lap;
- lap is not marked as in-pit;
- lap has complete fuel, throttle, brake, speed, and distance coverage;
- lap distance reaches the expected track length range;
- driver notes do not mark the lap as invalid.

Warm-up laps may be loaded but should be excluded from calibration unless the
driver explicitly labels them as usable.

Current implementation in `src/licor/analysis/lap_summary.py` uses:

- consecutive `Lap` events as lap boundaries;
- required coverage for `Fuel Level`, `Lap Dist`, `Ground Speed`, `Throttle Pos`,
  and `Brake Pos`;
- configurable lap-distance bounds, initially `6500` to `7500` meters for Spa;
- non-negative full-lap fuel burn from first minus last `Fuel Level` sample;
- no active `In Pits` state during the lap interval;
- driver labels from `config/datasets/spa_lmp2_2026-05-14.json`.

Driver labels `valid` and `borderline` are included in the calibration lap set
when basic telemetry validation also passes. Driver labels `context`,
`excluded`, and `unlabeled` remain visible in the summary table but are not
included by `filter_valid_laps`.

## Driver Intent Labels

Raw telemetry should be paired with a small sidecar label file or table. Suggested
fields:

- `file_name`
- `run_id`
- `lap_number`
- `session_type`
- `run_type`: `push`, `global_lico`, `targeted_lico`, `race`, `practice`
- `lico_intensity`: `none`, `light`, `medium`, `heavy`, `unknown`
- `target_zone`
- `labels_quality`: `high`, `medium`, `low`
- `notes`

`lico_intensity` is a collection label, not a final optimization class. The
model should use it to understand the experiment design, then extract continuous
LICO variables from telemetry.

## Zone-Level Analysis Tables

LICOR should eventually represent each driver pass through a track zone as a
row. Full-lap summaries are useful, but zone observations are the core unit for
LICO optimization.

Suggested `track_zone` fields:

- `zone_id`
- `turn_numbers`
- `track_name`
- `car_class`
- `display_label`
- `start_distance_m`
- `lico_window_start_m`
- `brake_reference_m`
- `end_distance_m`
- `lico_eligible`
- `optimization_role`
- `validation_end_rule`
- `review_status`
- `notes`

Current editable track-zone configs live under `config/track_zones/`. The first
draft is `config/track_zones/spa_lmp2_zones.draft.json`. Numeric distance fields
may be `null` while awaiting driver review; code should treat those rows as
incomplete rather than silently inventing boundaries.

Track zones should use generally known turn numbers as the stable identifier
instead of local corner names. Human-readable corner names may appear in notes,
but code should use `turn_numbers`, `zone_id`, and `display_label`.

`lico_eligible` distinguishes zones that may be optimized from zones that should
only be used for validation or context. It should stay binary and conservative:
use `false` for structural non-candidates such as the second Bus Stop brake
pressure. Do not hardcode intensity limits such as "no heavy LICO at Pouhon" in
the zone table; those should be learned later from zone-level cost/benefit data.

`validation_end_rule` documents how the post-braking validation boundary was
chosen. A stable full-throttle point may work for simple corners, while corner
complexes such as Les Combes should use a driver-reviewed manual boundary.

`brake_reference_m` is the distance of the reference brake point for the zone.
It is the anchor used to express LICO as "lift X meters before brake". Initially,
it is computed conservatively from clean full-push laps as the earliest observed
brake start in the zone. This approximates the earliest brake point expected with
maximum fuel and no LICO. A driver ideal reference means the brake marker or
brake point the driver would consider correct for a clean full-push lap, even if
a specific telemetry lap braked slightly early or late.

`lico_window_start_m` should initially be proposed from observed high-LICO laps:
take the earliest detected LICO start in that zone, then subtract a safety buffer
of `30 m`. The value remains driver-reviewed rather than final truth.

## Zone Validation Visualization

`src/licor/reports/zone_validation_map.py` can render zone proposals as a Plotly
HTML validation report. If future telemetry or an external track map provides
XY coordinates, the report can plot a true circuit map. The current LMU files do
not expose XY/GPS position channels, so the first Spa report falls back to a
distance-strip view using `lap_distance_m` on the x-axis and `Path Lateral` when
available on the y-axis.

`config/track_maps/spa_francorchamps_osm.geojson` stores a local OpenStreetMap
trace of the main Spa circuit, excluding pit lane, karting, rallycross, joker
lap, and moto-layout variants. `src/licor/reports/track_map.py` converts that
longitude/latitude trace into local meters, computes cumulative distance, and
scales it to the LMU observed lap-distance length for top-down validation. The
map should be treated as a visual validation aid; start/finish offset and exact
game-vs-OSM distance alignment may still need review.

Marker projection supports `map_distance_offset_m`, applied as
`(lmu_distance_m + offset) % track_length_m`. This is the calibration knob for
aligning LMU `lap_distance_m` with the external OSM trace. If all brake markers
appear after apexes, the offset should usually move negative.

`proposed_end_distance_m` is an automatic visualization aid, not a final track
zone boundary. The initial rule places the end before the next zone start and
keeps at least a short validation window after the brake reference. Final
`end_distance_m` values must come from driver review.

Suggested `zone_pass` fields:

- `file_name`
- `run_id`
- `lap_number`
- `zone_id`
- `lico_intensity`
- `fuel_used_l`
- `elapsed_time_s`
- `fuel_delta_l`
- `time_delta_s`
- `lico_start_m`
- `lico_start_distance_before_brake_m`
- `lico_duration_s`
- `lico_distance_m`
- `throttle_release_rate`
- `minimum_throttle_pct_before_brake`
- `average_throttle_pct_before_brake`
- `brake_start_m`
- `brake_start_speed_kph`
- `min_speed_kph`
- `exit_speed_kph`
- `validity_label`
- `notes`

Current implementation in `src/licor/analysis/zone_pass.py` creates one
`zone_pass` row for each selected lap and each complete, driver-reviewed,
candidate `track_zone`. By default, validation-only and incomplete zones are
skipped. This keeps Bus Stop T19 out of optimization until it has complete
validation boundaries and an explicit reason to be included.

Initial `zone_pass` extraction is sample-based:

- zone boundaries use the first and last telemetry samples inside
  `[start_distance_m, end_distance_m]`;
- fuel used is `fuel_start_l - fuel_end_l` inside the zone window;
- elapsed time is last sample timestamp minus first sample timestamp;
- actual `brake_start_m` is the first sample in the zone where
  `brake_pct >= 5`;
- LICO starts at the first pre-brake sample where throttle leaves full throttle
  (`throttle_pct <= 99`) before a qualifying zero-input period;
- a qualifying zero-input period is currently `throttle_pct <= 1` for at least
  `0.10 s`;
- rows are marked `valid` only when sampled coverage reaches both zone
  boundaries within a configurable distance tolerance, initially `20 m`.

This first version does not interpolate exact boundary crossings. That is
acceptable for Phase 3 exploration, but final cost/benefit estimates should
eventually use interpolation or distance-resampling so fuel and time deltas are
less sensitive to sample alignment.

## Current Braking And LICO Detection

The first implementation in `src/licor/analysis/zone_detection.py` builds a
per-lap telemetry table on the `Brake Pos` timeline and aligns `Throttle Pos`,
`Lap Dist`, and `Ground Speed` by timestamp.

Initial braking-zone detection uses:

- brake active when `brake_pct >= 5.0`;
- minimum raw brake segment duration of `0.25 s`;
- merge adjacent brake segments only when the off-brake gap is at most `0.25 s`
  and `25 m`.

The merge rule is intended to remove tiny brake-input chatter, not to merge two
deliberate brake pressures. Bus Stop-style separate brake pressures should remain
separate detected zones; later track-zone configuration should mark the second
Bus Stop pressure as not eligible for LICO optimization.

Initial LICO-zone detection uses:

- LICO start when throttle leaves full throttle, currently
  `throttle_pct <= 99.0`;
- a required zero-input phase, currently `throttle_pct <= 1.0` for at least
  `0.10 s`;
- minimum lift duration of `0.20 s`;
- minimum lift distance of `10 m`;
- a lookback window of `8.0 s` and `500 m` before the detected brake start;
- maximum gap of `1.0 s` from lift end to brake start.

Each braking zone produces a LICO row. When no qualifying lift is found, the row
is kept with `has_lico = false` so push laps and non-LICO zones remain explicit
comparison points.

## Pit Stop Analysis Tables

Pit stop telemetry should be represented separately from LICO calibration laps.

Suggested `pit_stop_observation` fields:

- `file_name`
- `run_id`
- `track_name`
- `car_class`
- `pit_entry_ts`
- `pit_exit_ts`
- `speed_limiter_on_ts`
- `speed_limiter_off_ts`
- `stationary_start_ts`
- `stationary_end_ts`
- `refill_start_ts`
- `refill_end_ts`
- `fuel_start_l`
- `fuel_end_l`
- `fuel_added_l`
- `observed_refill_rate_lps`
- `stationary_duration_s`
- `speed_limiter_duration_s`
- `in_pits_duration_s`
- `tire_change_included`
- `notes`

Suggested `race_strategy_config` fields:

- `race_duration_min`
- `tank_capacity_l`
- `baseline_fuel_per_lap_l`
- `baseline_lap_time_s`
- `pit_stop_loss_s`
- `refill_rate_lps`
- `fuel_target_l_per_lap`
- `mandatory_stop_count`
- `tire_change_time_s`
- `notes`
