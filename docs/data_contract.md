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
- driver labels from `config/datasets/spa_lmp2_v2_2026-05-21.json`.

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
- `collection_protocol_id`
- `collection_session_id`: optional protocol session identifier when the run
  should be tied to a specific planned session
- `target_zone`
- `target_zones`
- `target_zones_source`: optional sentinel such as `from_exported_plan` when
  zones should be resolved from a referenced plan rather than listed manually
- `collection_design`: `baseline`, `global_label`, `controlled_random`,
  `targeted_zone`, `pitstop_validation`, `recommendation_execution`, `other`
- `planned_lico_profile_id`
- `planned_lico_profile_description`
- `audio_cue_plan_id`
- `execution_quality`
- `labels_quality`: `high`, `medium`, `low`
- `driver_notes`

`lico_intensity` is a collection label, not a final optimization class. The
model should use it to understand the experiment design, then extract continuous
LICO variables from telemetry.

The first Spa labels `none`, `low`, `medium`, and `high` were useful for finding
the first cost/benefit relationships. Future labels should describe experiment
design more explicitly. Controlled-random runs help fill continuous curves,
targeted-zone runs help isolate one zone's causal effect, and
recommendation-execution runs validate whether a model-generated plan can be
followed and whether its predicted fuel/time outcome appears in telemetry.

The first planned Spa v2 protocol is versioned in
`config/collection_protocols/spa_lmp2_v2_protocol.json`. It defines the intended
collection designs, required run metadata, priority zones, and execution-quality
labels for the next Spa data collection pass. Dataset sidecars should reference
that protocol through `collection_protocol_id` instead of duplicating the full
protocol in every run entry.

Current implementation in `src/licor/analysis/lap_summary.py` accepts the v2
metadata fields on each `RunLapLabels` entry and propagates them into lap
summaries. `src/licor/analysis/zone_pass.py` carries the same run-level metadata
into every extracted `zone_pass` row. This means future non-labelled or weakly
labelled Spa v2 runs can feed readiness reports directly from their sidecar JSON
instead of relying on the legacy `none`/`low`/`medium`/`high` collection labels.

`src/licor/analysis/collection_metadata.py` provides the pre-telemetry
validation layer for those sidecars:

- `run_collection_metadata_frame` emits one run-metadata row per sidecar run;
- `validate_dataset_collection_metadata` checks protocol id, collection design,
  target zones, execution quality, LICO profile id, and required audio plan id
  for recommendation-execution runs;
- `attach_collection_metadata_to_zone_passes` can enrich an existing
  `zone_pass` table by `run_id` when metadata was generated separately.

The validation layer should report missing v2 metadata explicitly. It should not
infer `collection_design` from old global labels such as `low` or `high`.

Suggested `execution_quality` labels:

- `clean`: the intended LICO action and braking/exiting phase were executed
  normally;
- `partial`: the lap or zone is usable for context, but one part of the
  intended LICO action was not clean;
- `poor`: a driver mistake, missed brake point, abnormal exit, or telemetry
  artifact likely contaminates the zone;
- `unknown`: no driver review is available yet.

## Data Readiness Tables

`src/licor/analysis/data_readiness.py` provides readiness summaries for Spa v2
and future weakly labelled collection passes. These summaries are descriptive:
they tell us whether the dataset has enough clean coverage to update curves,
not whether a zone is strategically optimal.

Suggested `zone_data_readiness` fields:

- `zone_id`
- `display_label`
- `total_pass_count`
- `valid_pass_count`
- `invalid_pass_count`
- `unique_run_count`
- `unique_lap_count`
- `baseline_pass_count`
- `lico_pass_count`
- `controlled_random_pass_count`
- `targeted_zone_pass_count`
- `recommendation_execution_pass_count`
- `lico_distance_bin_count`
- `min_lico_distance_before_brake_m`
- `max_lico_distance_before_brake_m`
- `collection_designs`
- `validity_labels`
- `readiness_status`
- `readiness_flags`

Suggested `collection_protocol_readiness` fields:

- `protocol_id`
- `session_id`
- `collection_design`
- `target_zones`
- `target_zones_source`
- `minimum_clean_laps`
- `observed_clean_laps`
- `observed_runs`
- `observed_target_zones`
- `observed_cue_event_count`
- `readiness_status`
- `readiness_flags`

Readiness deliberately keeps baseline/no-LICO passes separate from LICO
distance bins. `has_lico == false` is not treated as proof of a clean push lap
unless collection metadata or legacy `none` labels support that interpretation.
For Spa v2, `collection_design` is the preferred context signal; older global
`none`/`low`/`medium`/`high` labels are only a fallback.

`recommendation_execution` readiness is stricter than ordinary zone-pass
coverage. When `target_zones_source` is `from_exported_plan`, zone passes alone
are not enough: cue/event logs must also be present so the run can be evaluated
as planned-versus-executed validation. Pit stop validation is intentionally
outside `zone_pass` readiness and should be checked through pit-stop observation
tables.

`src/licor/analysis/processed_artifacts.py` persists the current reproducible
Spa analysis artifacts used by readiness:

- `data/processed/spa_lmp2_zone_passes.csv`;
- `data/processed/spa_lmp2_zone_passes.parquet`;
- `data/processed/spa_lmp2_v2_zone_data_readiness.csv`;
- `data/processed/spa_lmp2_v2_protocol_readiness.csv`.

CSV outputs serialize list-valued columns with `|` separators so they remain
plain spreadsheet-friendly files. Parquet keeps richer nested column types.

## Core Lap Telemetry Report

`src/licor/reports/lap_telemetry_report.py` provides the offline Plotly report
for full-lap speed, throttle, brake, fuel level, and lap-distance traces. It is
intended for quick validation of current and future data collection runs before
opening any Streamlit workflow.

The report consumes normalized lap samples with these columns:

- `run_id`;
- `lap_number`;
- `collection_label`;
- `driver_lap_label`;
- `lap_elapsed_s`;
- `lap_distance_m`;
- `ground_speed_kph`;
- `throttle_pct`;
- `brake_pct`;
- `fuel_level_l`.

`build_labeled_lap_telemetry_samples` rebuilds this sample table from a dataset
sidecar and LMU DuckDB files, including only driver-labelled `valid` and
`borderline` laps by default. `create_lap_telemetry_report_figure` renders the
five metric rows as a pure Plotly figure, and
`write_lap_telemetry_report_html` writes a self-contained HTML file with Plotly
embedded so the report can be opened without a Streamlit server or an internet
connection.

The current Spa artifact is:

- `data/processed/spa_lmp2_lap_telemetry_report.html`.

## Run/Lap Quality Manifest

`src/licor/analysis/lap_quality.py` provides the v2 run/lap quality manifest.
It is an audit table, not a model and not a strategic decision surface. Its job
is to answer "usable for what?" before future data is allowed to influence zone
readiness, curve updates, or plan-execution validation.

The manifest combines:

- lap summary fields such as driver labels, fuel used, lap time, basic validity,
  and exclusion reason;
- run-level v2 metadata such as protocol id, collection design, execution
  quality, and label quality;
- optional lap-sample continuity checks such as sample count, max time gap, max
  distance gap, distance monotonicity, fuel increases, speed jumps, and input
  value ranges;
- optional zone-pass checks such as valid zone-pass rate, detected LICO count,
  zero-throttle zone starts, and brake-reference drift.

Key output fields:

- `quality_status`: `ready`, `review_recommended`, or `needs_review`;
- `quality_flags`: explicit audit reasons such as `missing_collection_design`,
  `large_time_gap`, `low_valid_zone_pass_rate`, or `detected_lico`;
- `recommended_uses`: list-valued permissions such as `report_only`,
  `lap_summary`, `zone_readiness`, `curve_update_candidate`,
  `baseline_reference`, or `plan_execution_review`.

Baseline fuel/time deltas in this manifest are audit signals only. They should
not be interpreted as fuel saved, time lost, optimizer evidence, or zone-level
model output. Zone-specific credibility remains the responsibility of
`zone_pass`, driver review annotations, curve diagnostics, and readiness tables.

The current Spa artifact is:

- `data/processed/spa_lmp2_v2_lap_quality_manifest.csv`.

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
`config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json`.

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

`src/licor/reports/zone_plan_report.py` overlays selected optimizer points on
the zone model fuel, time, and fuel-per-second curves. The current local Spa
artifact is
`data/processed/spa_lmp2_zone_lico_plan_driver_priors_prudent_report.html`.
This report is meant for driver validation of selected LICO distances,
especially diagnostic zones such as T01, T08, and T12-T13.

`src/licor/analysis/zone_plan_diagnostics.py` adds optimizer-facing diagnostics
that stay independent from report rendering. `build_zone_marginal_efficiency`
turns a zone model curve into consecutive segments so the project can inspect
incremental, not only cumulative, fuel/time efficiency. Key fields include:

- `from_lico_distance_m` and `to_lico_distance_m`;
- `incremental_fuel_saved_l`;
- `incremental_time_lost_s`;
- `marginal_fuel_saved_per_second_lps`;
- `best_cumulative_ratio_distance_m`;
- `is_after_best_cumulative_ratio_distance`;
- `contains_selected_plan_point`;
- `marginal_flags`.

This table is meant to answer why an optimizer may choose a point beyond the
best cumulative ratio. A later segment can be less efficient marginally but
still be required to reach the race fuel target.

The same module provides `summarize_zone_plan_sensitivity`, which reruns the
zone optimizer across named scenarios and returns one row per scenario. Initial
scenario support includes:

- base optimizer settings;
- capping each zone at its best cumulative ratio point;
- excluding diagnostic-only zones;
- adding a fuel safety margin to the target;
- custom per-zone maximum LICO distances.

Sensitivity outputs should be treated as decision diagnostics. They should not
replace the optimizer objective; they explain how fragile or robust a plan is
when the allowed model surface changes.

## Live Cue Plan And Execution Tables

Exact recommended lift distances are difficult for the driver to validate by
visual inspection and difficult to execute from memory. LICOR should eventually
export a simple live-cue plan that can be consumed by a telemetry runner.

Suggested `live_cue_plan` fields:

- `schema_version`
- `plan_id`
- `track_name`
- `car_class`
- `race_context_id`
- `zone_id`
- `display_label`
- `brake_reference_m`
- `selected_lico_distance_m`
- `planned_lift_start_m`
- `cue_distance_m`
- `cue_tolerance_m`
- `track_length_m`
- `minimum_confidence_label`
- `expected_fuel_saved_l`
- `expected_time_lost_s`
- `plan_status`
- `source_model_status`
- `source_quality_flags`
- `strategy_role`
- `notes`

Suggested `live_cue_execution` fields:

- `schema_version`
- `plan_id`
- `file_name`
- `run_id`
- `lap_number`
- `zone_id`
- `cue_trigger_m`
- `planned_lift_start_m`
- `actual_lift_start_m`
- `actual_lift_distance_before_brake_m`
- `actual_brake_start_m`
- `cue_error_m`
- `fuel_saved_vs_baseline_l`
- `time_lost_vs_baseline_s`
- `execution_quality`
- `notes`

Suggested `live_cue_event_log` fields:

- `schema_version`
- `plan_id`
- `file_name`
- `run_id`
- `lap_number`
- `zone_id`
- `display_label`
- `cue_trigger_m`
- `planned_lift_start_m`
- `actual_cue_distance_m`
- `cue_error_m`
- `cue_tolerance_m`
- `trigger_status`: `fired_on_time`, `fired_late`, or `fired_early`
- `sample_index`
- `sample_ts`
- `sample_elapsed_s`
- `audio_cue_kind`
- `notes`

The live cue runner should not replace the offline optimizer. It should execute
an exported plan, log what happened, and feed planned-versus-executed telemetry
back into the offline model.

Current implementation in `src/licor/analysis/live_plan.py` defines the first
versioned export contract:

- `build_live_cue_plan` consumes a zone-level optimizer plan and reviewed
  `track_zone` definitions;
- `planned_lift_start_m` is calculated as
  `brake_reference_m - selected_lico_distance_m`;
- when a `track_length_m` is provided, lift-start distance wraps around the lap
  start using modulo track length;
- `cue_distance_m` is the actual trigger point for the beep and may be earlier
  than `planned_lift_start_m` when cue latency compensation is configured;
- `planned_lift_start_m` remains the intended lift anchor even when the cue is
  advanced to compensate for human reaction time and system latency;
- only selected LICO zones are exported by default;
- missing `brake_reference_m` for a selected zone is an error, because a live
  cue plan cannot safely invent the driver reference point.

`build_live_cue_executions_from_zone_passes` creates the first replay-style
execution table by joining an exported plan to observed `zone_pass` rows. It
records planned lift start, observed lift start, observed brake start, cue error
in meters, local fuel/time deltas, and execution quality. When track length is
available, cue error is a signed circular distance so start/finish wraparound
does not create false multi-kilometer errors. Fuel/time deltas are read from
baseline-delta columns when present and otherwise remain null for raw
`zone_pass` rows that do not carry baseline comparisons. This is a replay schema
foundation, not a real-time audio implementation yet.

`src/licor/analysis/live_cue_runner.py` adds the first minimal cue runtime. It
loads a versioned `live_cue_plan` CSV, validates the required runtime columns,
and simulates cue triggering from ordered telemetry samples containing
`lap_number`, `lap_distance_m`, and `ts`. The runner:

- triggers on distance crossing, not exact equality;
- suppresses duplicate triggers per lap and zone;
- handles start/finish wrap when `track_length_m` is available;
- logs both `cue_trigger_m` and `planned_lift_start_m` so future latency
  compensation can move the trigger without losing the intended lift anchor;
- summarizes cue timing accuracy by plan and zone.

This is a deterministic software cue/logging prototype. The actual sound output
adapter remains a separate integration step.

`src/licor/live/` contains the first I/O wrapper around that deterministic
runner:

- `RecordingAudioCueAdapter` records cue payloads in memory for tests;
- `NullAudioCueAdapter` disables sound while keeping the replay/logging path;
- `SystemBeepAudioCueAdapter` is the minimal real-audio adapter and should stay
  outside automated tests;
- `run_replay_live_cue_session` loads a plan CSV and telemetry sample CSV,
  emits one audio-adapter call per triggered cue, writes the primary
  `live_cue_event_log`, and optionally writes the derived accuracy summary.

The event log is the auditable source of truth. The accuracy log is derived and
can be regenerated from events. Replay sessions write logs before calling the
audio adapter, and existing log files are not overwritten unless
`overwrite_existing_logs` is explicitly enabled.

## Cross-Circuit Learning Tables

To generalize beyond Spa without manually rebuilding every zone, LICOR should
store reusable zone features and transfer-model outputs separately from
driver-reviewed final configs.

Suggested `zone_feature` fields:

- `track_name`
- `car_class`
- `zone_id`
- `turn_numbers`
- `approach_speed_kph`
- `brake_reference_m`
- `brake_start_speed_kph`
- `brake_severity`
- `straight_length_before_brake_m`
- `corner_complexity_label`
- `exit_acceleration_distance_m`
- `baseline_fuel_used_l`
- `baseline_elapsed_time_s`
- `feature_quality`

Suggested `transfer_prior` fields:

- `source_model_id`
- `target_track_name`
- `target_zone_id`
- `predicted_lico_feasibility`
- `predicted_curve_shape`
- `uncertainty_label`
- `requires_manual_review`
- `notes`

Machine learning or heavier statistical models should use these tables to
propose starting points for new circuits. They should reduce the calibration
budget, not silently replace circuit-specific push laps, varied LICO laps, or
manual review for unusual zones.
