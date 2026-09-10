# Dataset Log

This file documents local telemetry datasets used during LICOR development.
Raw `.duckdb` files stay outside Git. This log keeps the labels, valid laps, and
driver notes needed to reproduce analyses.

A machine-readable mirror of the current working lap labels lives at
`config/datasets/spa_lmp2_v2_2026-05-21.json`. The older
`config/datasets/spa_lmp2_2026-05-14.json` sidecar remains as the historical
v1 snapshot. Keep this document as the human source of driver context, and
update the JSON used by the pipeline when lap labels change.

## Paul Ricard reconstruction — 2026-09-07

The Paul sidecar is `config/datasets/paul_ricard_lmp2_2026-09-07.json`, with a
retrospective collection protocol and explicit zone review in the matching
config directories. It rebuilds two push recordings (May 31) and two varied-LICO
recordings (June 1) from raw files in `data/`.

All 31 completed laps and 279 all-zone passes remain in audit outputs. Modeling
uses 25 laps and 150 candidate passes, including the explicit baseline_02 lap13
T03 exclusion. Baseline_02 lap12 remains excluded; lap14 remains context pending
late-sector review. Lap13 other zones are restored instead of silently omitting
the whole lap as the old modeling CSV did. The clean whole-lap baseline stays
at nine laps. Historical tire wear and randomization seed are unknown.

Readiness flags remain visible: T11 has detected lifts in five of ten baseline
passes, T12 in one; the curve builder excludes these passes from local baseline.
The six candidate models use 143 curve observations after those exclusions:
T01–T02 25, T03 24, T08–T09 25, T11 20, T12 24 and T14 25. Their selected
prediction-validation bins contain respectively 5, 6, 3, 6, 9 and 5 LICO
passes. This is sufficient for a prospective coverage profile, not held-out
proof. T01's local time signal is nonpositive/noisy and T08's far tail remains
uncertain. The raw impact field is Boolean, so no physical impact magnitude is
inferred.

Use `scripts/build_paul_ricard_intake.py`, then the pilot plan/pack builders.
Current outputs live under
`data/processed/experimental/paul_ricard_prediction_validation_2026_09`.
Raw/config/code/output hashes guard against stale inputs. Historical outputs
under `paul_ricard_transfer_v1` and the two-zone
`paul_ricard_pilot_2026_09` pack/session are preserved. See
[the pilot run sheet](paul_ricard_static_pilot_run_sheet.md) for the operator
workflow and the first six-zone result.

## Paul Ricard six-zone live validation — 2026-09-09

The prospective session is preserved under
`data/processed/experimental/paul_ricard_prediction_validation_2026_09/sessions/paul_pilot_20260909_220534`.
It contains seven scored laps: push laps 13, 16 and 19, and static LICO laps 14,
15, 17 and 18. All 24 audible crossings were recorded — six zones on each of
four LICO laps — all were within tolerance, and the maximum absolute trigger
error was `1.331 m`. The driver subsequently confirmed hearing all 24 cues, so
the operational audio/cue verdict passes.

The frozen CSV-only evaluator uses the live-runtime distance projection and
linear interpolation between the bracketing push laps. Its provisional
whole-lap mean is `0.1584 L` saved and `0.3191 s` lost per LICO lap, compared
with the frozen plan's `0.12855 L` and `0.37222 s`. These values are descriptive
only. LMU telemetry recording was not active, so no `.duckdb` exists, and the
driver recalls unclean laps without being able to identify their lap numbers.
The performance result is therefore unscorable and cannot authorize a refit.

Run the recorded-session evaluation from the project root with:

```powershell
.venv\Scripts\python.exe scripts\analyze_paul_ricard_live_validation.py --session-dir .\data\processed\experimental\paul_ricard_prediction_validation_2026_09\sessions\paul_pilot_20260909_220534
```

The session has 24 cue-correlated sampling gaps between `0.100` and `0.129 s`.
They were caused by the blocking system-beep call. Audio emission now runs in
the background for future recordings, but the gaps remain a limitation of this
session. Keep this run permanently separate from the four-run reconstruction
dataset for performance fitting. Its valid contribution is the prospective
operational proof that all six zones can trigger accurately and audibly. The
earlier two-zone session remains preserved as distinct history.

## Paul Ricard five-lap confirmation — 2026-09-09

Session `paul_pilot_20260909_232207` executed the frozen P/L/P/L/P schedule on
absolute laps 22–26. The launcher linked the native LMU recording
`Paul Ricard Circuit_P_2026-09-10T03_22_17Z.duckdb`; its metadata confirms Paul
Ricard ELMS, Oreca 07 #397, LMP2_ELMS and constant partly cloudy conditions.
All 12 software cues fired in tolerance with a maximum absolute trigger error
of `1.513 m`, and the nonblocking beep produced no cue-correlated live-CSV gaps.

Driver review identifies errors on the first LICO lap, absolute lap 23: T1 and
probably T13. Lap 23 is excluded from whole-lap scoring. At zone level,
T01–T02/lap23 is excluded because the error is confirmed and no LICO was
detected; T14/lap23 is prudently excluded because the probable T13 error may
contaminate its approach. The other four zone observations from lap23 remain
usable, as do all six from clean LICO lap25.

Native-DuckDB scoring of the one clean whole LICO lap measures `0.1823 L` saved
and `0.6800 s` lost against bracketing push laps, versus frozen predictions of
`0.12855 L` and `0.37222 s`. Ten of twelve zone observations remain included.
This is an authoritative but very small prospective sample: preserve it as a
held-out validation result and do not refit from it. The driver confirmed
hearing all 12 cues, so the operational audio/cue gate is closed.

The all-history, no-double-counting verdict is: T03 and T11 robust for the
tested profile; T01–T02 and T08–T09 promising; T12 unstable because its measured
time cost is much higher than predicted; and T14 insufficient because only one
authoritative held-out observation remains. See
[the 2026-09-10 decision record](decision_record_2026-09-10_cross_circuit.md).

## Label Meaning

The labels `none`, `low`, `medium`, and `high` are collection conditions, not
final optimizer classes. Future models should extract continuous LICO variables
such as lift distance and lift duration from each zone pass.

## Current Local Files

### Spa LMP2 - No LICO / Full Push

| Field | Value |
| --- | --- |
| File | `data/Circuit de Spa-Francorchamps_P_2026-05-14T02_19_09Z_none.duckdb` |
| Track | Circuit de Spa-Francorchamps |
| Car class | LMP2_ELMS |
| Car | Oreca 07 ELMS Custom Team 2025 #397 |
| Session type | Practice |
| Run type | push baseline |
| Collection label | `none` |
| Labels quality | high |

Valid laps:

```text
5, 6, 7, 8, 9
```

Excluded or ignored laps:

```text
3, 4
```

Notes:

- Lap 3 is not representative.
- Lap 4 is above the initial `2:04.000` quality threshold.
- Laps 5-9 form the current push baseline.
- Observed mean fuel use on valid laps: approximately `3.446 L/lap`.
- Observed mean lap time on valid laps: approximately `123.822 s`.

### Spa LMP2 - Low LICO

| Field | Value |
| --- | --- |
| File | `data/Circuit de Spa-Francorchamps_P_2026-05-14T02_49_32Z_low.duckdb` |
| Track | Circuit de Spa-Francorchamps |
| Car class | LMP2_ELMS |
| Car | Oreca 07 ELMS Custom Team 2025 #397 |
| Session type | Practice |
| Run type | global LICO |
| Collection label | `low` |
| Labels quality | medium-high |

Primary stable laps:

```text
16, 17, 18, 19
```

Additional usable but less clean lap:

```text
15
```

Excluded or adaptation laps:

```text
13, 14
```

Notes:

- Early laps include driver adaptation to LICO timing.
- Laps 16-19 are the current stable low-LICO subset.
- Lap 17 is slightly above `2:04.000` but has stable telemetry metrics and should
  be marked `borderline`, not automatically discarded.
- Observed mean fuel use on stable laps: approximately `3.268 L/lap`.
- Observed mean lap time on stable laps: approximately `123.930 s`.
- Low LICO shows a clear fuel saving signal while preserving generally stable
  driving behavior.

### Spa LMP2 - Medium LICO

| Field | Value |
| --- | --- |
| File | `data/Circuit de Spa-Francorchamps_P_2026-05-14T03_18_32Z_medium.duckdb` |
| Track | Circuit de Spa-Francorchamps |
| Car class | LMP2_ELMS |
| Car | Oreca 07 ELMS Custom Team 2025 #397 |
| Session type | Practice |
| Run type | global LICO |
| Collection label | `medium` |
| Labels quality | medium |

Primary stable laps:

```text
24, 25, 26, 27
```

Additional context laps:

```text
22, 23
```

Excluded or adaptation laps:

```text
21
```

Notes:

- Medium LICO reveals that some zones become harder to manage when lifting too
  much.
- Les Combes feels natural with medium LICO and appears robust in telemetry.
- Bus Stop also feels natural to the driver, but the current brake-zone detector
  can split the Bus Stop braking sequence incorrectly.
- Pouhon appears sensitive to too much LICO; telemetry showed a notable minimum
  speed drop at higher LICO levels.
- Observed mean fuel use on stable laps: approximately `3.112 L/lap`.
- Observed mean lap time on stable laps: approximately `124.422 s`.

### Spa LMP2 - High LICO

| Field | Value |
| --- | --- |
| File | `data/Circuit de Spa-Francorchamps_P_2026-05-14T03_36_44Z_high.duckdb` |
| Track | Circuit de Spa-Francorchamps |
| Car class | LMP2_ELMS |
| Car | Oreca 07 ELMS Custom Team 2025 #397 |
| Session type | Practice |
| Run type | global LICO |
| Collection label | `high` |
| Labels quality | medium-high |

Primary stable laps:

```text
31, 32, 33
```

Additional usable but less clean lap:

```text
30
```

Excluded or adaptation laps:

```text
29
```

Notes:

- The driver reported this run felt cleaner and more consistent than medium.
- Telemetry supports this for laps 31-33: fuel use, lap time, and lift behavior
  are relatively stable.
- High LICO is not assumed to be optimal; it is valuable as an extreme point on
  the continuous LICO curve.
- Les Combes remains robust even with high LICO.
- Pouhon and some complex/high-speed zones appear to degrade sharply at high
  LICO.
- Observed mean fuel use on laps 31-33: approximately `2.929 L/lap`.
- Observed mean lap time on laps 31-33: approximately `125.174 s`.

### Spa LMP2 - Pit Stop / Full Refill

| Field | Value |
| --- | --- |
| File | `data/Circuit de Spa-Francorchamps_P_2026-05-14T03_58_38Z_pitstop.duckdb` |
| Track | Circuit de Spa-Francorchamps |
| Car class | LMP2_ELMS |
| Car | Oreca 07 ELMS Custom Team 2025 #397 |
| Session type | Practice |
| Run type | pit stop observation |
| Collection label | `pitstop` |
| Labels quality | medium |

Observed sequence:

```text
outlap
timed lap with pit entry before the end
full fuel refill from roughly 0.4 L to 75 L
outlap to finish line
```

Notes:

- This file should be used for pit/refill analysis, not LICO calibration.
- No tire change was included.
- Observed speed limiter duration: approximately `70.0 s`.
- Observed `In Pits` duration: approximately `68.4 s`.
- Observed stationary duration around refill: approximately `43.3 s`.
- Observed fuel added: approximately `74.6 L`.
- Observed refill duration while fuel level increased: approximately `39.8 s`.
- Observed refill rate in this telemetry file: approximately `1.87 L/s`.
- The observed refill rate should be compared against LMU rules or additional
  pit stop files before being treated as definitive.

## Current Dataset Assessment

The current dataset is sufficient to start coding the first offline analysis
pipeline:

- DuckDB ingestion;
- lap summaries;
- valid lap filtering;
- brake-zone detection;
- driver-reviewed Spa zone definitions;
- zone-pass metrics;
- first continuous LICO fuel/time curves;
- pit stop/refill analysis.

The first offline pipeline now produces reproducible tables, zone models, race
strategy targets, and candidate Spa LICO plans. Additional Spa data should move
from broad `low`/`medium`/`high` labels to a versioned collection protocol that
improves curve coverage, reduces same-lap zone correlation, and prepares
planned-versus-executed validation.

## Spa V2 Collection Protocol

A machine-readable draft protocol lives at
`config/collection_protocols/spa_lmp2_v2_protocol.json`.

The Spa v2 goal is not to manually validate exact optimizer distances by eye.
The goal is to collect better evidence for the model and later validate
exported plans with replay/live cue execution logs.

Planned collection designs:

- one or two additional pit stop files to validate refill behavior;
- a second clean `none` baseline to validate push-run stability;
- controlled-random Spa LICO runs that vary lift distance naturally across
  zones and fill the continuous curves;
- targeted Spa LICO runs for key zones such as T05-T06, T08, T12-T13, T18, and
  T01, with only a small number of zones emphasized at a time;
- live-cue execution runs now that LICOR can export a plan and simulate/log cue
  triggers, with real audio output still to be wired;
- another circuit with mostly push laps plus a small number of varied LICO laps
  to test transfer from Spa without a full manual 50-lap rebuild.

### Spa V2 Integrated Files

The current v2 sidecar now includes two new baseline refresh runs and four
`controlled_random` runs in addition to the original v1 `none` / `low` /
`medium` / `high` / `pitstop` files.

#### Baseline Refresh 01

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-21T22_10_36Z_baseline_push_01.duckdb`
- Run id: `spa_lmp2_2026-05-21T22_10_36Z_baseline_push_01`
- Collection design: `baseline`
- Collection label: `none`
- Valid laps: `5, 6, 7, 8, 9, 10`
- Excluded laps: `4`
- Notes: clean push-baseline refresh.

#### Baseline Refresh 02

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-21T22_31_31Z_baseline_push_02.duckdb`
- Run id: `spa_lmp2_2026-05-21T22_31_31Z_baseline_push_02`
- Collection design: `baseline`
- Collection label: `none`
- Valid laps: `13, 15, 16, 17, 18, 19`
- Excluded laps: `12, 14`
- Zone-only exclusion: lap `15` / `T08`
- Notes: lap 14 is removed after the off-track error; lap 15 stays usable
  except for T08.

#### Controlled Random 01

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-21T22_57_26Z_controlled_random_01.duckdb`
- Run id: `spa_lmp2_2026-05-21T22_57_26Z_controlled_random_01`
- Collection design: `controlled_random`
- Valid laps: `22, 23, 24, 25, 26`
- Excluded laps: `21`
- Notes: includes the intentional `T12-T13` boundary probe on lap 26.

#### Controlled Random 02

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-22T00_16_10Z_controlled_random_02.duckdb`
- Run id: `spa_lmp2_2026-05-22T00_16_10Z_controlled_random_02`
- Collection design: `controlled_random`
- Valid laps: `29, 30, 31, 34, 35, 36`
- Borderline laps: `32, 33`
- Excluded laps: `28`
- Zone-only exclusions: lap `32` / `T14`, lap `32` / `T18`, lap `33` / `T01`
- Notes: driver-reported accident lap maps to LMU lap 32; unaffected earlier
  zones stay usable.

#### Controlled Random 03

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-22T00_41_25Z_controlled_random_03.duckdb`
- Run id: `spa_lmp2_2026-05-22T00_41_25Z_controlled_random_03`
- Collection design: `controlled_random`
- Valid laps: `39, 40, 41, 42, 43, 44, 45`
- Excluded laps: `38`
- Notes: clean run with no impact-based exclusions.

#### Controlled Random 04

- File: `data/Circuit de Spa-Francorchamps_P_2026-05-22T01_05_54Z_controlled_random_04.duckdb`
- Run id: `spa_lmp2_2026-05-22T01_05_54Z_controlled_random_04`
- Collection design: `controlled_random`
- Valid laps: `48, 49, 50, 51, 52, 53`
- Excluded laps: `47`
- Notes: a light wall touch before Eau Rouge on lap 50 was reviewed and kept as
  non-contaminating.

#### Recommendation Execution Selected 01

- File:
  `C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry/Circuit de Spa-Francorchamps_P_2026-05-27T03_18_06Z.duckdb`
- Run id: `recommendation_execution_selected_01`
- Collection design: `recommendation_execution`
- Planned profile: `spa_exp_live_candidate_selected_v1`
- Audio cue plan id:
  `experimental_live_candidate_range_aware_selected_zones_v1`
- Valid laps: `2, 3, 4, 5, 6`
- Context laps: `1`
- Excluded laps: `0`
- Notes: first real live-cue Candidate A validation. Driver debrief reported
  that all active zones felt natural and correctly timed and would be marked
  `N` across the board. No per-lap note sheet was transcribed during the
  session, so the intake stores the verdict as session-level review input.

#### Recommendation Execution Selected Latency V2 02

- File:
  `C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry/Circuit de Spa-Francorchamps_P_2026-05-28T01_48_35Z.duckdb`
- Run id: `recommendation_execution_selected_latency_v2_02`
- Collection design: `recommendation_execution`
- Planned profile: `spa_exp_live_candidate_selected_latency_v2`
- Audio cue plan id:
  `experimental_live_candidate_range_aware_selected_zones_latency_v2`
- Valid laps: `8, 9`
- Excluded laps: `7`
- Notes: telemetry-enabled confirmation run for the speed-aware selected-zones
  latency v2 plan. Lap 7 is excluded because it still contains the initial
  in-pits/shared-memory attachment context. The planned-versus-executed review
  on laps 8-9 shows near-zero mean distance error across the active zones, so
  this run freezes `selected_zones_latency_v2` as the current live baseline.
  Lap notes and zone signoff were not fully transcribed, so the run should be
  read as strong plan-execution evidence rather than a deep workload study.

#### Recommendation Execution Selected Latency V2 Guarded Preview 01

- File:
  `C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/UserData/Telemetry/Circuit de Spa-Francorchamps_P_2026-05-31T02_08_30Z.duckdb`
- Run id: `recommendation_execution_selected_latency_v2_guarded_preview_01`
- Collection design: `recommendation_execution`
- Planned profile: `spa_exp_guarded_handoff_selected_latency_v2`
- Audio cue plan id:
  `experimental_guarded_adaptive_handoff|selected_zones_latency_v2_baseline|adaptive_guarded|observed_execution:recommendation_execution_selected_latency_v2_02|lap_8_to_9`
- Valid laps: `2, 3, 4, 5`
- Context laps: `1`
- Excluded laps: `0`
- Notes: first telemetry-backed live run of the guarded adaptive operator-preview
  follow-up candidate. The driver reported 2-3 missed audible cues because of
  music, so a few corners may show later-than-intended lift or braking despite
  an otherwise coherent plan. The telemetry review still supports keeping the
  run: mean lift-start deltas stay moderate overall, with one obvious outlier
  on `T08` lap 4 and a few later-than-ideal moments on `T18`, `T05-T06`, and
  `T10-T11`. The raw cue log continued into non-telemetry laps `6-7` after the
  session; those rows are ignored from processed intake artifacts.

Current interpretation after four Spa v2 `controlled_random` runs:

- controlled-random coverage is now strong enough to refit Spa zone curves
  before scheduling targeted-zone collection;
- targeted-zone runs are no longer the default next step and should be used
  only if post-refit diagnostics still show weak bins, unstable optimizer
  choices, or zone-boundary uncertainty;
- the speed-aware static live cue layer is now credible enough to act as the
  live baseline for future adaptive work;
- recommendation-execution runs now matter more than additional random
  collection if the refit produces a credible plan that can be replayed or
  executed with live cues.

Future data should record the experiment design, not just the broad LICO level:

- `collection_protocol_id`;
- `collection_session_id` when a run maps to a specific planned protocol
  session;
- `collection_design`;
- `target_zones`;
- `target_zones_source` when targets come from an exported plan;
- `planned_lico_profile_id`;
- `planned_lico_profile_description`;
- `audio_cue_plan_id` for recommendation-execution runs;
- `execution_quality`;
- `labels_quality`;
- driver notes.

Use global labels only when they are truly the collection intent; otherwise
prefer labels such as `controlled_random`, `targeted_zone`, or
`recommendation_execution`. Recommendation-execution data should include a
stable `plan_id`, plus cue event logs that record scheduled trigger distance,
actual trigger distance, and timing accuracy.

Before refitting curves from Spa v2, run the data-readiness summaries. They
should report, by zone and by protocol session, whether there are enough clean
baseline passes, detected LICO passes, and LICO-distance bins. Missing
`collection_design` metadata should be treated as unlinked context for new Spa
v2 designs, not silently inferred from old global labels.

The ingestion sidecar contract is now wired into analysis code. Future Spa v2
dataset JSON files can include the fields above, and LICOR will propagate them
from `RunLapLabels` into lap summaries and `zone_pass` rows. Before processing
new telemetry, run `validate_dataset_collection_metadata` against
`config/collection_protocols/spa_lmp2_v2_protocol.json` to catch missing
protocol ids, unknown target zones, missing LICO profile ids, or missing
`audio_cue_plan_id` values for recommendation-execution runs.

The current mixed Spa v1 plus Spa v2 runs can now be persisted as zone-pass
artifacts:

- `data/processed/spa_lmp2_zone_passes.csv`;
- `data/processed/spa_lmp2_zone_passes.parquet`;
- `data/processed/spa_lmp2_v2_zone_data_readiness.csv`;
- `data/processed/spa_lmp2_v2_protocol_readiness.csv`.
- `data/processed/spa_lmp2_v2_lap_quality_manifest.csv`;
- `data/processed/spa_lmp2_lap_telemetry_report.html`.

Because the current runs predate the Spa v2 protocol, protocol readiness should
show the new controlled-random, targeted-zone, and recommendation-execution
sessions as unlinked until new metadata-rich runs are collected.

The lap telemetry report is a self-contained Plotly HTML review tool for speed,
throttle, brake, fuel level, and lap distance across labelled valid/borderline
laps. It is meant to help inspect future data collection quality before any
Streamlit dashboard work.

The lap quality manifest is an audit table for future collection triage. It
keeps quality flags and recommended uses separate from zone model conclusions:
a lap can be useful for reports, lap summaries, zone readiness, curve-update
candidates, baseline references, or plan-execution review depending on its
metadata, sample continuity, lap-summary status, and zone-pass health.
