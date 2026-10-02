# LICOR Core Telemetry Schema

## Continual local response replay (offline development)

`analysis/continual_learning.py` observes one target at a time with immutable
`LocalResponse` snapshots. Keep states separate by zone, target and explicit
context (car/track/conditions/reference version). A changed context fails closed;
the caller must initialize new state rather than carry an old correction across
a refuel/setup/weather/reference change without review.

The frozen global `ResponseFit` accepts action and acceleration. A local scale
starts at 1 and is updated only after computing the old-state prediction for
scoring. For accepted passage count n, clamp `(outcome / prior - scale)` to
[-0.5,0.5], divide by `(2+n+1)`, limit the scale step to 0.1, then bound the
new scale to [0.5,1.5]. These are fixed engineering guardrails, not tuned
confidence bounds. Counts represent correlated passages, not independent proof.
Negative targets remain in the evidence and scores; only update influence is
bounded. Missing targets and rejected quality do not update. Zero action has
zero predicted response but gives no dose-response evidence. Zero prior cannot
be corrected multiplicatively and is explicitly marked `zero_prior`, not
certified as an ineffective zone. Outside train-only marginal action or
acceleration support, abstain rather than clip; support is not joint coverage.

`scripts/replay_continual_learning.py` replays Sebring initial run then retry,
numeric lap then physical zone order (never lexical run order). The existing
tracked phase review must match every observation identity and quality tier.
One common empirical tier gates both fuel and time. All 49 passages are retained;
only the 12 `strict_retry` passages may update and enter the primary scores.
Fit the frozen action-only comparison prior from the 171 finite paired,
historically qualified non-Sebring rows; missing prior outcomes are not imputed.
Acceleration remains recorded and support-gated; this simple baseline does not
learn an acceleration interaction. The core supports the existing richer priors,
but no candidate selection or future-outcome tuning happens in this replay.

The executed dose is retrospective, even though response state is prequential.
Planned dose remains distinct. Existing pre-reviewed geometry, retrospective
quality annotations and five dedicated push references are not autonomous
short-qualifying startup. Frozen versus local scores compare predictions of
actually executed actions, not benefits of unexecuted adaptive plans. No live
cues, budget accounting, descriptor refresh, exploration or new training labels
are authorized by this output. Source hashes are checked and outputs must use a
new directory. See `docs/continual_learning_replay_2026-10-01.md`.

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
| `raw_lmu_g_force_lat_g` | `G Force Lat` | G | Native channel retained for audit. In all 16 Spa/Paul files checked on 2026-09-10, this is the longitudinal axis despite its LMU name. |
| `longitudinal_accel_sensor_mps2` | derived from `G Force Lat` | m/s² | `-raw_lmu_g_force_lat_g * 9.80665`; usable only while its correlation with speed-derived acceleration passes the version guard. |
| `raw_lmu_g_force_long_g` | `G Force Long` | G | Native channel retained for audit; behaves like a lateral/steering-related axis in the current files and must not be used as longitudinal acceleration. |
| `path_lateral_m` | `Path Lateral` | m | Track position signal. |
| `track_edge_m` | `Track Edge` | m | Track-limit/context signal. |
| `tyre_wear_pct_fl` | `Tyres Wear.value1` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_fr` | `Tyres Wear.value2` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_rl` | `Tyres Wear.value3` | % | Wheel ordering must be confirmed. |
| `tyre_wear_pct_rr` | `Tyres Wear.value4` | % | Wheel ordering must be confirmed. |

## Static pilot live logs — September 2026

The optional static runtime lap gate uses absolute shared-memory lap numbers.
`--cue-laps` selects laps with audio enabled; other laps still produce crossing
events with `cue_enabled=false`. Treat these as muted diagnostic crossings, not
missed or emitted cues. The runtime accuracy summary includes enabled events
only. An enabled event records a software trigger, not confirmed human hearing.

`--stop-after-lap` ends the run on the first sample with a greater lap number,
before triggering cues in that next lap. With `--telemetry-log`, samples from
push, LICO and outlap roles are preserved with the available fuel, speed,
throttle, brake and gear channels. Preserve the native `.duckdb` as well for
complete events, quality review and timestamp reconciliation.

The Paul launcher freezes the resolved absolute lap schedule, audio setting and
plan hash in session files. Post-run analysis must join events and telemetry to
that schedule rather than infer treatment from whether a cue event exists.
The generated `.cmd` wrapper starts the signed-local `.ps1` with process-scoped
`ExecutionPolicy Bypass`; it does not change the user or machine policy. The
launcher reads shared memory immediately before startup, defaults the first
scored lap to the next absolute lap, and rejects an explicit lap already passed.
See [the pilot run sheet](paul_ricard_static_pilot_run_sheet.md) for the predeclared
comparison method. Historical unscheduled live logs may lack `cue_enabled`;
retain their original all-laps behavior when interpreting those sessions.

`scripts/analyze_paul_ricard_live_validation.py` is the frozen Paul post-run
scorer. It takes a `--session-dir`, verifies the current frozen plan hash and the
full schedule-by-zone crossing set, applies the runtime distance projection to
the recorded telemetry, extracts all six candidate-zone passes and compares
LICO laps with linearly interpolated bracketing push laps. Its default outputs
are written under `<session-dir>/validation/`:

- `lap_validation.csv`;
- `zone_execution_observations.csv`;
- `zone_execution_summary.csv`;
- `plan_used.csv`;
- `track_zones_used.json`;
- `validation_manifest.json`;
- `validation_report.md`.

These are CSV-only prospective-scoring artifacts, not a replacement for native
intake. They can establish software cue coverage, trigger-distance accuracy,
detected lift execution and provisional fuel/time deltas. Track/car identity,
official lap/event reconciliation, impacts, pit state and final exclusions
still require the native `.duckdb`, completed operator metadata and a resolved
driver lap-quality debrief. A debrief that reports unclean laps without their
numbers cannot support inferred exclusions. `validation_manifest.json` must
therefore keep `refit_authorized=false` until those gates are satisfied; the
prospective run must not be added to curve fitting before its frozen predictions
are evaluated and reviewed.

Session `paul_pilot_20260909_220534` is the first six-zone application of this
contract: push laps 13/16/19, LICO laps 14/15/17/18, 24 of 24 audible cues in
tolerance and `1.331 m` maximum absolute trigger error. Projection-aware,
bracketing-push scoring gives a provisional mean of `0.1584 L` saved and
`0.3191 s` lost per LICO lap, versus frozen predictions of `0.12855 L` and
`0.37222 s`. The driver confirmed hearing all 24 cues, which validates the
operational audio result. LMU telemetry was not active, and the driver cannot
identify which laps were unclean, so performance scoring is invalid and the run
is not eligible for refitting.

That session also contains 24 treatment-correlated telemetry gaps of `0.100` to
`0.129 s`, caused by synchronous system-beep emission. Future live runs emit
the beep in the background so audio playback does not block sample collection.
The correction changes future capture only; it must not be applied
retroactively to conceal gaps in the recorded session.

For sessions with a linked native file, the Paul scorer also writes
`duckdb_lap_validation.csv`, `duckdb_zone_execution_observations.csv` and
`duckdb_zone_execution_summary.csv`. The native file must match Paul Ricard and
the session car class and contain every scheduled lap. Whole-lap driver
exclusions and zone-specific exclusions are separate: a corner error can remove
one zone observation without silently discarding unrelated zones from that lap.
Session `paul_pilot_20260909_232207` exercises this contract with lap23 excluded
from whole-lap scoring and only T01–T02/23 plus T14/23 excluded at zone level.

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
- `actual_cue_distance_m`: effective distance used to fire the cue
- `raw_lap_distance_m`: latest raw LMU scoring distance
- `cue_distance_method`: `raw_scoring` or `speed_projected`
- `distance_projection_age_s`: age of the raw-distance anchor used for projection
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

Selection purpose must be explicit before this export. A `race_strategy` plan
may legitimately export only the minimum-time zones needed for its sourced fuel
target. A `prediction_validation` or `collection_coverage` plan must use an
explicit coverage policy instead of inflating a fuel target merely to force more
zones. The Paul six-zone profile records `plan_purpose`, `selection_policy` and
`target_source`; its descriptive fuel/time sum is not a race recommendation.

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

LMU exposes the scoring lap distance more coarsely than the telemetry speed. In
the first Paul live session, distance stayed fixed for about `0.20 s` then
jumped by 13–16 m, making five of six cues appear late despite distance-crossing
logic. The live runtime now projects distance for at most `0.25 s` between raw
scoring updates using the mean live speed. The raw distance remains in the
telemetry log; the event's `actual_cue_distance_m` records the projected trigger
position used by the runtime.
Runtime event logs using this projection are schema version 2 and retain the raw
distance, method, and projection age beside the effective trigger distance. A
small backward correction when a projected position is replaced by a fresher
raw scoring value is held monotonic. A decrease larger than half a known track
length, or 100 m when length is unavailable, is treated as a reset rather than
projection noise. Recorded replay verification also
requires every cue to remain within its declared tolerance and in plan order.

## Cross-Circuit Learning Tables

The first concrete contract is
`config/ml/licor_lmp2_feature_contract_v1.json`. Its observation grain is
`dataset_id / circuit_id / run_id / lap_number / zone_id`; the lineage key also
retains the raw-file SHA-256, zone-definition hash and extractor version.
`scripts/build_cross_circuit_ml_table.py` rebuilds Spa and Paul Ricard from the
native DuckDB files and writes the versioned table, feature registry, split
assignments, fold-local push references and fold feature views under
`data/processed/experimental/cross_circuit_ml_v1/`.

The raw observation table is intentionally rich, but column availability is
part of the schema. Each field is classified as identifier, static context,
pre-action candidate, planned action, observed action, post-action outcome,
quality or audit-only. Dynamic context such as approach speed and tyre
temperature is not a decision input until its timestamp is explicitly proven
to precede the decision cutoff. Same-pass braking, minimum-speed and exit
quantities are outcomes or diagnostics, not pre-action predictors.

The primary transferable action is not normalized by the manually chosen LICO
window. It is defined inside each fold as:

```text
planned_lift_lead_vs_push_brake_m
    = forward_distance(planned_lift_start_m,
                       median_clean_push_brake_onset_m)

planned_lift_lead_to_push_deceleration_ratio
    = planned_lift_lead_vs_push_brake_m
      / median_clean_push_brake_onset_to_min_speed_distance_m
```

Historical training retains the corresponding **executed** quantities and the
coast length (`lico_distance_m`) separately. The old
`lico_start_distance_before_brake_m` is explicitly renamed as a legacy lead to
the manual brake reference in the pooled table; it must not masquerade as the
physical push-braking ratio.

Push references are fitted only after assigning `train`, `calibration` and
`test` roles. A calibrated zero-LICO-shot fold may use clean push laps from the
destination circuit as `calibration`, but those rows never fit the response
model and no local LICO result may be inspected. Each reference needs at least
three clean push passes per zone and carries its support and dispersion. Zones
without a sustained braking event remain usable with absolute action fields,
but the ratio is unavailable. Contract v1 also rejects a push denominator when
its within-fold coefficient of variation exceeds `0.15`, when no stable
acceleration recovery follows the minimum-speed point, or when the observed
lift begins after the push brake onset.

Manual `lico_window_start_m` and `zone_end_m` are capture/QC metadata. They do
not appear in the ratio or its denominator. Fuel/time targets remain local to
one zone and are rebuilt from fold-local push medians; the older globally
attached `baseline_mean_*` and `*_vs_baseline_*` columns are diagnostic only
and are removed from the raw cross-circuit observation table.

Driver errors may contaminate only part of a zone and must therefore be masked
by metric phase when the evidence supports that distinction. A slide or wide
exit after an otherwise normal approach and brake onset invalidates local
elapsed-time, exit-speed and related post-action targets for that pass, but it
does not invalidate pre-action acceleration, approach speed or physical brake
onset. Conversely, an entry or braking error invalidates those physical
references as well. Whole-zone `driver_excluded` remains the fail-safe when the
onset of the error cannot be localized. The raw pass and driver note stay in
the audit table in every case.

Transfer models should reduce the calibration budget, not silently replace
circuit-specific push laps, varied LICO laps or manual review for unusual
zones. With only Spa and Paul Ricard, both cross-circuit directions remain
diagnostic stress tests rather than estimates of generalization.

### Frozen scoring endpoint and recovery endpoint

The manually reviewed `zone_end_m` remains the prospective scoring endpoint
that was known when a plan was frozen. It must not be moved after inspecting a
new-circuit result. A second, explicitly labeled recovery endpoint may be used
as a post-run diagnostic when speed, elapsed-time or acceleration has not
recovered by `zone_end_m`. It must:

- be derived with one fixed rule for every lap in the comparison;
- end before the next LICO action can contribute;
- score push and LICO laps at the same absolute distances;
- remain a separate column and artifact from the frozen score; and
- be versioned into the next target definition only after the prospective
  result has been preserved.

This distinction prevents short capture windows from making an action appear
cheap while also preventing an outcome-informed endpoint from silently
improving or worsening the original frozen prediction. With corrected native
timestamp interpolation, Bahrain T10's frozen endpoint at `2800 m` reports
`0.133 s`; the diagnostic endpoint at `3080 m` reports a median `0.198 s` and a
maximum `0.305 s`. Earlier `0.193/0.295 s` estimates are superseded because
interpolation incorrectly used the last repeat of a held scoring distance.

`fixed_distance.py` now interpolates crossing timestamps between the first
samples of distinct native distance updates, then samples fuel/speed on their
own timestamp grids. Distance resets at lap start are trimmed; internal
non-monotonicity or missing coverage is rejected rather than extrapolated.
All circuits in ML v2 use this same outcome rule. Physical source timestamps
remain discrete; near-zero costs and negative observed deltas require caution.

Upstream feature capture, the candidate action range, and the scoring outcome
window are separate objects. Bahrain's `bahrain_lmp2_capture_envelope_v2.json`
retains broader approaches (about 475–500 m lift lead) without changing the
prospective score windows. Capture may overlap a previous zone; outcome costs
must not be added across overlapping windows. A 500 m detector lookback is an
implementation limit, not a physical maximum. Acceleration for candidates
beyond the original ratio grid is sampled directly from push traces at the
candidate; it must not be clipped to a smaller lift's acceleration.

ML v2 labels scheduled push laps and silent zones using the session schedule.
Natural short coasts remain detector diagnostics and do not become response
training observations. Phase masks null only contaminated outcomes and
apex-dependent descriptors; onset evidence remains available. Each target and
physical denominator requires its own minimum support of three. Entire runs
stay in one LOCO role. A separate within-run adaptation study explicitly labels
its weaker independence and never alters the prospective frozen score.

### Acceleration at the proposed lift

Sebring prospective two-dose validation freezes separate plan IDs A/B and an
absolute `lap_number,plan_id` schedule; a multi-plan live file without a mapping
is rejected. Only the mapped plan can sound, and push laps remain silent.
Each event retains its plan ID. The seven non-overlapping outcome groups include
the silent downstream corners T5/T16 in T3/T15; their costs must not be added
again. Source references are prior push laps8–12, not the upcoming test outcomes.
Scored laps2/3 calibrate, and laps5/6 remain the fixed local-budget test cohort.

The Sebring approach grid samples acceleration directly every 5 m up to 500 m,
without clipping to ratio 1.5. This is an offline capture audit, not authority for
large lifts. `Throttle Pos Unfiltered` distinguishes the driver's full throttle
from brief filtered throttle cuts (observed during a full-pedal approach).
Filtered throttle and physical acceleration remain preserved; this does not
change the historical detector or refit its data. All 35 push outcome starts
are audited for filtered/unfiltered zero throttle before the pack is frozen.
The audio lead compensation remains 0.35 s and must be checked against actual
execution. Wider capture and newly frozen recovery boundaries remain distinct.

The first transferable acceleration context is built from clean full-push laps,
not from the LICO passage being predicted. For each physical braking event, the
builder samples one-second approach windows ending `0.20 s` before points at
`0`, `0.25`, `0.5`, `1.0` and `1.5` times the physical push deceleration
distance ahead of the brake onset. The primary value is the median mapped sensor acceleration;
a regression of ground speed against time is the fallback and sensor-axis
check.

Inside each fold, clean-push profiles are aggregated separately by circuit and
zone. The proposed lift ratio selects an interpolated value:

```text
push_acceleration_at_planned_lift_mps2
    = interpolate(fold_push_acceleration_profile,
                  planned_lift_lead_to_push_deceleration_ratio)

planned_acceleration_weighted_action
    = planned_lift_lead_to_push_deceleration_ratio
      * max(push_acceleration_at_planned_lift_mps2, 0)
```

This explicitly distinguishes a lift while the car is still accelerating from
a lift near terminal speed. Ratios outside `[0, 1.5]` are clipped for the
acceleration lookup and flagged as `clipped_low` or `clipped_high`; diagnostic
model scores use only `in_range` rows. `observed_pre_lift_acceleration_mps2` remains an execution diagnostic:
it is not silently substituted for the push counterfactual in static planning.

### Compact four-circuit retrospective response benchmark

Native race diagnostic captures follow `docs/native_race_capture_protocol.md`:
5 Hz JSONL, raw native clocks and counters, unique vehicle-ID player matching,
null HUD estimates, no inferred race horizon. These non-atomic raw snapshots
require context segmentation and freshness checks before budget replay or ML.

Offline HUD OCR in `scripts/audit_hud_ocr.py` is a separate diagnostic, not a
new native source. Raw text, frame time/hash, numeric candidates, ambiguity and
missingness are preserved. Frame35 is development; evaluations exclude it and
count visible-frame exact/wrong/missing separately from correct-absent/false-
positive controls. No OCR digit repair, carry-forward, future lookahead or
implicit conversion of fractional total into remaining player laps. Ambiguous
approximation markers produce unknown status. OCR syntax is not calibrated
confidence. All outputs keep `live_authorized=false`; native logger HUD fields
remain null. Display rounding and update latency remain properties of the HUD.

`race_context.replay_race_context` consumes those snapshots chronologically,
without consulting future rows. It separates formation, racing, clock expiry,
leader finish, own finish, pit/garage, pause, caution and unavailable states.
Only the player's native finish flag can yield zero remaining laps. Context
history resets on inactive states, identity/clock/lap discontinuity, skipped
player laps, >1s capture gaps/frozen scoring, or fuel increases >0.01L. These
thresholds are diagnostic guards for the 5Hz capture, not calibrated bounds or
proof of refueling. Ambiguous leader changes/skipped crossings clear leader pace.

`licor_nominal_remaining_laps` is a boundary-only, constant-last-observed-pace
forecast, distinct from raw `hud_total_laps`. It needs two observed crossings of
each car in the active context; it does not borrow qualifying/prior-session laps.
The prototype assumes the first leader crossing strictly after timer expiry,
then counts player crossings at unchanged pace. An overdue leader crossing
(last observed lap duration +1s) causes abstention, not invented missed laps.
First observed scoring crossings retain sampling latency; no future-assisted
interpolation is used. The forecast has no pit/traffic/incident model and does
not certify a clean lap. `upper_remaining_laps` remains null until observed own
finish, and `fuel_plan_authorized` is always false. Never substitute this point
forecast for the fuel budget's required upper horizon. No raw HUD rounding.

`leader_switch` adds a conditional sensitivity at eligible player boundaries.
It concerns leader totals, never automatically player totals. The chosen pair
brackets the leader crossing nearest timer expiry; the predicted next crossing
is held fixed while the mean duration of subsequent complete laps varies.
`short_crossing_minus_timer_s` is positive if that crossing occurs after expiry;
`pace_minus_switch_s_per_lap` is positive when faster future full laps would
reach the extra-lap threshold. Equality uses the explicit prototype convention
of a crossing at expiry requiring another lap. `near_switch` uses a1s diagnostic
tolerance, not a probability. With no full laps left, the pace threshold is null.
The pair can change; it is a sensitivity comparison, not a persistent race plan.

`race_scenarios.compare_fuel_scenarios` takes explicit adjacent positive counts
of whole remaining **player** laps to finish or next refuel, current tank,
frozen admissible plan menu, reserve and consumption allowance. Each budget
sets nominal=upper to its own hypothesis; the longer branch is not asserted to
bound every possible race. Both recommendations are returned without selecting
a scenario by default. Infeasible branches retain deficits, not an executable
recommendation. Predictions conditional on a supplied current plan assume it
continues; unknown execution is null, never inferred from previous suggestions.
No0.1L default,15-lap trigger, future-refill credit, training or live authority.
The native replay does not yet automatically supply this comparator's player
hypotheses, plan menu or qualified consumption inputs.

The boundary-only `fuel_budget_replay` uses explicit completed/remaining lap
counts; native HUD decimal totals and fuel-lap estimates are diagnostic fields,
not converted source-of-truth integers. Its residual is observed full-lap fuel
minus the frozen prediction for the actually executed plan. It requires a usable
consecutive interval. No planned shadow action is assumed executed. The rolling
positive residual envelope is not statistically calibrated or zone-causal.
Confirmed finish clears further plans; refuel requires an explicit new context.

Follow-up outputs in `four_circuit_harmonized_v1` preserve identities, outcomes
and quality tiers; `acceleration_previous` records the prior method, while
`acceleration_harmonized`/`acceleration` use the common ratio-profile method.
`acceleration_planned_harmonized` is exported for Sebring only and must be used
for planned-action decisions instead of executed-action context. Historical
planned acceleration is explicitly unavailable in this compact export.

The response candidate benchmark remains development-only. Positive quadratic
coefficients ensure convexity at fixed acceleration, not global monotonicity
along a varying-acceleration approach. Fuel overprediction diagnostics are
not calibrated safety margins. Decision audits distinguish observed whole
A/B plans from hypothetical mixtures of zone responses. They cannot certify
race fuel sufficiency from seven outcome windows.

The offline `fuel_budget` boundary calculator takes explicit whole remaining
laps, upper lap bound, reserve, future formation burn and conservative push
consumption. It credits only current tank fuel. Its target is finish or next
refuel, never an implicit sum of future refills. Do not call mid-lap. Fuel
feasibility precedes time minimization; unreachable is a first-class result.

`scripts/qualify_sebring_phases.py` exports all 49 Sebring LICO passages with
explicit quality tiers and phase annotations. `strict_retry` is a retrospective
restricted sensitivity (12 passages), not a clean-driver or complete-recovery
certificate. The other 37 observations remain `exploratory_only`. Recovery
extensions use frozen geometry, stop before the next cue, and are never added
to overlapping outcome totals. Phase-specific push medians are not additive.

`scripts/evaluate_four_circuit_low_data.py` uses one historical destination-fold
copy per observation and dedicated prior-push targets; it is not ML v2 dataset
replacement. The locked Paul confirmation remains excluded. Whole circuits/runs
are separated for response fitting. Action-only and acceleration-interaction
models share finite paired coverage. Executed action and post-run qualification
make these retrospective diagnostics, not prospective decision validation.

Macro MAE equally weights four circuit-level MAEs, but fitting weights individual
observations equally, not circuits equally. Export fit identities, coefficients,
training ranges and test marginal-range exceedances. Range inclusion does not
certify joint support. No preprocessing or tuning uses test outcomes.

The original Sebring run alone supports provisional calibration budgets0/1/2:
calibration laps2/3, fixed test laps5/6 for every budget. The retry never replaces
this test. Local adaptation shrinks a non-negative slope toward a non-Sebring
prior with a fixed penalty scaled by the first calibration planned action.
Unlocalized initial errors and common-session references remain limitations.
If new model choices are optimized against these scores, treat the scores as
development evidence and require a newly frozen prospective confirmation.
