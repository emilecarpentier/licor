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
- `zone_start_throttle_pct` records the first throttle sample inside the zone;
- `zone_start_zero_throttle` flags zone starts that already begin at zero
  throttle;
- actual `brake_start_m` is the first sample in the zone where
  `brake_pct >= 5`;
- LICO starts at the first pre-brake sample where throttle leaves full throttle
  (`throttle_pct <= 99`) within the same continuous lift segment as a qualifying
  zero-input period;
- a qualifying zero-input period is currently `throttle_pct <= 1` for at least
  `0.10 s`;
- rows are marked `valid` only when sampled coverage reaches both zone
  boundaries within a configurable distance tolerance, initially `20 m`.

This first version does not interpolate exact boundary crossings. That is
acceptable for Phase 3 exploration, but final cost/benefit estimates should
eventually use interpolation or distance-resampling so fuel and time deltas are
less sensitive to sample alignment.

Driver review rule: if a zone starts with throttle already at `0%`, the zone
start is too late and should be reviewed. This diagnostic is intentionally a
flag, not an automatic correction, because widening a zone can accidentally
capture throttle inputs from the previous corner.

Isolated throttle artifacts before the real coast phase should not define LICO
start. The current zone-pass extraction ignores earlier throttle dips unless
they belong to the same continuous below-full-throttle segment as the qualifying
zero-input phase. This was added after T08 lap 16 showed repeated impossible
`71.076%` throttle samples before the real lift.

## Zone-Level Cost Summary

`src/licor/analysis/zone_summary.py` summarizes `zone_pass` observations by
`zone_id`, `display_label`, and `lico_intensity`. It filters to valid zone
passes by default, then compares each intensity group against the same zone's
`none` baseline.

Current summary fields include:

- `pass_count`;
- `detected_lico_passes`;
- `detected_lico_rate`;
- `mean_fuel_used_l`;
- `baseline_mean_fuel_used_l`;
- `fuel_saved_vs_baseline_l`;
- `mean_elapsed_time_s`;
- `baseline_mean_elapsed_time_s`;
- `time_lost_vs_baseline_s`;
- `fuel_saved_per_second_lps`;
- average LICO distance, duration, brake start, brake speed, minimum speed, and
  exit speed;
- deltas versus the push baseline for brake start, brake speed, minimum speed,
  and exit speed.

`fuel_saved_per_second_lps` is only populated when LICO was detected and both
fuel saving and local time loss are positive beyond a small numerical epsilon.
Rows that save no fuel, gain time, or have no detected LICO stay visible in the
summary, but are not ranked by the first cost/benefit ranking helper.

This summary is descriptive, not yet a final optimizer. Because the current
dataset uses global LICO runs, a zone's measured time/fuel can still be affected
by previous-zone behavior, fuel mass, and lap-to-lap execution. Targeted
zone-specific data should be preferred before treating a curve as definitive.

## Descriptive Zone Curves

`src/licor/analysis/zone_curves.py` creates the first simple curve-ready tables
from `zone_pass` observations. These are diagnostic tables, not fitted models.

`build_zone_curve_points` produces one point per valid zone pass:

- `lico_distance_before_brake_m`, with no-LICO passes set to `0 m`;
- `fuel_saved_vs_baseline_l`, compared with the same zone's `none` baseline;
- `time_lost_vs_baseline_s`, compared with the same zone's `none` baseline;
- `fuel_saved_per_second_lps`, only when both fuel saving and time loss are
  positive;
- supporting speed and validity fields for driver review.

`summarize_zone_curve_bins` groups those points into simple distance bins,
initially `25 m` wide by default. Each bin reports pass count, detected LICO
rate, average LICO distance, mean fuel saved, mean time lost, and fuel saved per
second lost. Baseline/noise-only bins do not receive a fuel-per-second ratio
unless they contain detected LICO and both mean deltas are positive beyond the
configured numerical epsilon.

These binned curves are meant to answer review questions before modeling:

- does more measured LICO generally save more fuel in this zone?
- does time loss increase smoothly or jump sharply after a threshold?
- are some bins supported by too few observations?
- do speed and exit-quality metrics suggest that the zone boundary or driving
  execution is contaminating the local estimate?

If these descriptive curves look credible, the next step is to fit initial
smooth zone-level cost/benefit curves. If they look noisy or contradictory, the
right answer is usually more targeted telemetry rather than a more complex
model.

## Initial Zone Models

`src/licor/analysis/zone_models.py` builds the first transparent zone-level
cost/benefit models from the distance-binned curve table. These are not machine
learning models yet; they are deterministic piecewise-linear interpolations
designed to be easy to inspect.

Current model behavior:

- each zone is anchored at `0 m` LICO with `0 L` fuel saved and `0 s` time lost;
- nonzero control points come from binned observations that contain detected
  LICO;
- fuel saving is monotone non-decreasing by default, so a noisier farther-lift
  bin cannot predict less fuel saving than an earlier bin;
- time loss is floored at `0 s` and monotone non-decreasing by default for the
  optimization-facing curve, because a LICO pass that appears faster than the
  push baseline is treated as timing/execution noise rather than free speed;
- `predicted_fuel_saved_per_second_lps` is suppressed when predicted time loss
  is below `0.05 s`, so near-zero denominators do not create unstable ratios;
- predictions are only produced within the observed LICO distance range;
- no extrapolated recommendation is silently created.

The model output includes:

- `zone_id`;
- `display_label`;
- `lico_distance_m`;
- `predicted_fuel_saved_l`;
- `predicted_time_lost_s`;
- `predicted_fuel_saved_per_second_lps`;
- `model_status`;
- `quality_flags`;
- source bin counts and observed maximum LICO distance.

`model_status` is intentionally conservative:

- `model_ready`: enough data and no review exclusion;
- `diagnostic_only`: useful signal exists, but driver review flagged noisy or
  unclear time behavior;
- `low_data`: too few nonzero bins or no positive fuel signal;
- `review_excluded`: driver review currently excludes the zone from
  optimization, such as T09's `no_credible_lico_signal` tag.

Review tags are metadata, not permanent hardcoding. Raw observations and
descriptive bins remain available, so future targeted data or a later ML model
can override current review status.

`low_time_loss_ratio_suppressed` flags zones where at least one nonzero model
point saves fuel but has too little predicted time loss to compute a stable
fuel-per-second ratio. The fuel and time predictions remain visible, but that
point should not be used as a ranked optimization candidate.

`src/licor/reports/zone_model_report.py` renders the piecewise model output into
a standalone Plotly HTML report with fuel, time, and usable-ratio curves for
each zone. The current local Spa artifact is
`data/processed/spa_lmp2_zone_model_report.html`.

`src/licor/reports/zone_curve_report.py` renders these points and bins into a
standalone Plotly HTML report. The report is designed for driver review:

- each zone gets a fuel-saved panel and a time-lost panel;
- individual lap-zone passes are shown as colored points by collection label;
- binned means are drawn as black line/marker traces;
- marker size on binned traces reflects the number of observations in that bin.

The driver's visual review should check whether each zone's relationship looks
credible in racing terms, especially whether increased lift distance produces a
reasonable fuel/time tradeoff and whether speed or exit behavior suggests that a
zone boundary is too wide, too short, or contaminated by an unrelated mistake.

## Full-Lap Sanity Checks

`src/licor/analysis/lap_sanity.py` compares full-lap deltas with the sum of
observed zone-level deltas. This table is diagnostic only; it should not replace
zone-level fuel/time curves as the optimization objective.

`summarize_full_lap_sanity` uses valid lap summaries and zone curve points to
produce one row per lap:

- full-lap fuel saved versus the `none` baseline;
- full-lap time lost versus the `none` baseline;
- summed observed fuel saved across included zone passes;
- summed observed time lost across included zone passes;
- fuel and time residuals, computed as full-lap delta minus summed zone delta;
- zone-to-lap ratios for quick coverage checks;
- counts of included zones and detected LICO zones.

The intended interpretation is:

- small fuel residuals suggest the zone windows capture the main fuel-saving
  behavior;
- large residuals suggest missing zones, contaminated windows, fuel measurement
  noise, or non-zone behavior;
- time residuals can be noisier because global lap time includes execution
  variation and potential recovery outside the reviewed causal windows.

The current Spa sanity artifact is written locally to
`data/processed/spa_lmp2_lap_sanity.csv` when regenerated during analysis.

## Driver Review Annotations

`config/driver_reviews/` stores driver review feedback that should affect
analysis without deleting raw observations. The first Spa review file is
`config/driver_reviews/spa_lmp2_zone_review_2026-05-14.json`.

Driver review can currently record:

- `zone_pass_exclusions`, keyed by `lap_number` and `zone_id`, for isolated
  pilot errors such as a missed brake point;
- `zone_annotations`, keyed by `zone_id`, for interpretation tags such as
  `clean_signal`, `noisy_time_signal`, `time_signal_unclear`, or
  `no_credible_lico_signal`.

`src/licor/analysis/driver_review.py` applies these annotations by changing the
affected observation's `validity_label` to `driver_excluded` and adding review
metadata columns. Downstream curve and summary functions filter to `valid`
observations by default, so excluded lap-zone observations are omitted while the
rest of the lap remains usable.

Current Spa driver review decisions:

- exclude only lap 24 / T01 because the driver missed the brake point;
- exclude only lap 24 / T14 because it is a driver-error outlier;
- keep the rest of lap 24 usable;
- tag T09 as `no_credible_lico_signal` rather than changing the track-zone table
  to a structural non-candidate yet;
- investigate T08 because observed LICO distances cluster near the zone start
  and around 100 m before braking.
- move T08 `start_distance_m` and `lico_window_start_m` 20 m earlier after
  targeted throttle/brake/speed review;
- expected LICO lift shape is a rapid transition from `100%` throttle to `0%`
  throttle, so release-rate variation should be treated cautiously unless the
  input trace clearly shows a different driver action.

`src/licor/reports/zone_telemetry_report.py` supports this kind of targeted
review by rendering throttle, brake, and speed traces around one zone across
laps. It overlays zone start, brake reference, zone end, and detected LICO-start
markers. This report should be used when a curve-level anomaly needs inspection
at the raw input level, such as the current T08 question.

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

Current implementation in `src/licor/analysis/pit_stop.py` extracts one
`pit_stop_observation` row per detected pit stop from a dedicated telemetry
file. It intentionally ignores the initial active pit/limiter state at session
open by default, because the Spa pitstop file starts on an out-lap from the pit
lane before the actual observed stop.

The current extraction uses:

- `In Pits` event transitions for `pit_entry_ts`, `pit_exit_ts`, and
  `in_pits_duration_s`;
- `Speed Limiter` event transitions for pit-lane commitment time;
- `Ground Speed <= 1.0 km/h` for the longest stationary segment inside the pit
  interval;
- positive `Fuel Level` deltas above `0.01 L` to detect the refill window;
- configurable minimum refill/stationary durations and fuel-added thresholds;
- an optional `reference_refill_rate_lps` to compare telemetry-derived refill
  rate with a rules/config value.

The first generated Spa artifact is
`data/processed/spa_lmp2_pit_stop_observations.csv`. For the current file, the
observed stop is valid and reports approximately:

- `70.02 s` speed-limiter/pit-lane commitment time;
- `43.27 s` stationary time;
- `39.80 s` refill duration;
- `74.56 L` fuel added;
- `1.873 L/s` observed refill rate.

This observation remains empirical. It should be compared with LMU rules values
or additional pit stop files before becoming a universal strategy parameter.

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

Current implementation in `src/licor/analysis/race_strategy.py` adds the first
transparent strategy helpers. These helpers are intentionally simple and should
be treated as strategic estimates, not final race calls.

`RaceStrategyConfig` currently includes:

- `race_duration_min`;
- `tank_capacity_l`;
- `baseline_fuel_per_lap_l`;
- `baseline_lap_time_s`;
- `pit_lane_commitment_time_s`;
- `refill_rate_lps`;
- optional `starting_fuel_l`, defaulting to tank capacity;
- `mandatory_stop_count`;
- `count_final_lap_after_clock`, defaulting to `true`;
- optional `race_laps_override` for championship-observed race distances.

The current strategy model uses:

- `race_laps = ceil(race_duration_s / baseline_lap_time_s)` by default;
- `max_stint_laps = floor(tank_capacity_l / fuel_per_lap_l)`;
- `required_stop_count = ceil(race_laps / max_stint_laps) - 1`, bounded by
  `mandatory_stop_count`;
- `estimated_total_time_s = race_laps * lap_time_s
  + required_stop_count * pit_lane_commitment_time_s`;
- `fuel_to_refill_l = max(0, race_laps * fuel_per_lap_l - starting_fuel_l)`;
- `estimated_refill_duration_s = fuel_to_refill_l / refill_rate_lps`.

Fuel-saving targets are computed by asking how much fuel per lap is allowed for
each target stop count:

```text
target_fuel_per_lap_l =
    tank_capacity_l * (target_stop_count + 1) / race_laps
```

The current Spa strategy artifacts are:

- `data/processed/spa_lmp2_race_strategy_scenarios.csv`;
- `data/processed/spa_lmp2_fuel_saving_targets.csv`.

For the current Spa ELMS use case, the driver supplied a championship-observed
distance of `48` laps. With observed baseline laps and measured pit stop
telemetry, full-push requires `2` stops, while a `1`-stop target requires
approximately `0.321 L/lap` fuel saving versus the current push baseline.

This first strategy pass compares observed global collection labels (`low`,
`medium`, `high`) against full-push. It is useful for scale and feasibility, but
the final recommendation should come from a zone-level plan with driver-reviewed
model quality rather than from global LICO labels.

## Zone-Level Fuel Target Optimizer

`src/licor/analysis/zone_optimizer.py` adds a first conservative optimizer for
turning strategy fuel targets into zone-level LICO plans. It chooses at most one
model point per zone and minimizes total predicted time loss while requiring:

- `model_status == "model_ready"` by default;
- no extrapolated model points;
- nonzero points with a usable fuel-per-second ratio;
- nonzero points with predicted time loss of at least `0.05 s`.

The optimizer returns one row per considered zone with selected LICO distance,
predicted fuel saved, predicted time lost, total plan fuel/time, fuel surplus,
and `plan_status`.

Current plan statuses:

- `target_met`: the selected model-ready zones reach the requested fuel target;
- `target_unreachable`: even the best available model-ready zone combination is
  below the requested target.

The current Spa 48-lap artifact is
`data/processed/spa_lmp2_zone_lico_plan_model_ready.csv`. With only `model_ready`
zones (`T05-T06`, `T10-T11`, `T18`), the plan reaches approximately
`0.307 L/lap` saved versus a `0.321 L/lap` 1-stop target, so it is marked
`target_unreachable`. This is intentionally conservative: diagnostic-only zones
remain excluded until driver review or targeted data makes them safe to use.

## Driver Strategy Priors

`config/strategy_priors/` stores driver feasibility priors for strategy
optimization. These priors are separate from structural track zones and signal
quality reviews:

- `track_zones` says where a zone is;
- `driver_reviews` says how credible the current telemetry signal is;
- `strategy_priors` says whether the driver considers LICO feasible in race
  terms.

The first Spa file is
`config/strategy_priors/spa_lmp2_driver_priors_2026-05-14.json`. It records
driver feasibility ratings on a `0` to `5` scale:

- `5/5`: T05-T06, T18;
- `4/5`: T12-T13, T08, T01;
- `2/5`: T10-T11, T14;
- `0/5`: T19, T09.

Implementation note: the driver message listed T12 twice. The current config
interprets that as `T12-T13 = 4/5` and `T14 = 2/5`, based on the immediately
preceding driver comments that T12-T13 is OK and T14 allows very little LICO.

Strategy priors can:

- exclude structural non-candidates;
- allow diagnostic-only model points when the driver says LICO is feasible;
- cap maximum LICO distance for limited zones such as T10-T11 or T14.

The optimizer keeps model time predictions unchanged. Priors affect candidate
eligibility, diagnostic-zone allowance, maximum LICO distance, and review
metadata only. Driver feasibility ratings express how natural or race-usable a
zone feels; they do not create an arbitrary time-loss penalty. The model remains
responsible for estimating fuel saved and time lost.

The current Spa driver-prior artifacts are:

- `data/processed/spa_lmp2_zone_lico_plan_conservative_model_ready.csv`;
- `data/processed/spa_lmp2_zone_lico_plan_driver_priors_prudent.csv`;
- `data/processed/spa_lmp2_zone_lico_plan_driver_priors_exploratory.csv`.

The prudent driver-prior plan reaches the `48`-lap one-stop target with roughly
`0.324 L/lap` predicted fuel saving and `0.717 s/lap` predicted time loss.
`optimization_time_lost_s` is currently equal to the model-predicted time loss.
This should be treated as a candidate for visual review, not a final
recommendation.
