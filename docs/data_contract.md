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
- `track_name`
- `car_class`
- `name`
- `start_distance_m`
- `lico_window_start_m`
- `brake_reference_m`
- `end_distance_m`
- `notes`

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
