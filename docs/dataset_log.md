# Dataset Log

## Continual Sebring replay — 2026-10-01 (Toronto)

No new collection, labels, geometry or production curve refit. Generated
`experimental/continual_sebring_replay_v1/` from the hash-verified harmonized
223-row table and existing tracked phase review. Frozen prior uses 171 finite
paired observations from Spa/Paul/Bahrain, excluding all Sebring outcomes.
All 49 Sebring passages remain in the chronological log (98 target events).
Only 12 restricted `strict_retry` observations update each target; the other
37 cannot update, including one out-of-action-support abstention. Scores are
predict-before-update, development-only, not a new prospective confirmation.
Fixed/local fuel MAE: 7.958/7.263 mL per eligible zone passage; time MAE:
0.07400/0.07130 s. After the first local observation, eight passages have fuel
MAE 10.196/9.154 mL. See `continual_learning_replay_2026-10-01.md` for provenance,
limitations, nonuniform effects and reproduction. No live cue/ML authority.

## Native race/HUD audit — 2026-10-01 (Toronto)

Offline OCR follow-up uses the same OBS video only; no new driving data or ML
rows. `hud_ocr_v1/` preserves frame35 development attempts and frozen14-frame
evaluation (total3/14, autonomy8/14 exact, others missing). V2 rearranges actual
label/value pixels, not digits, and uses a separate preselected14-visible-frame
sample plus2 HUD-absent controls. Results: total9/14, autonomy13/14 exact, both9/14;
no wrong numeric candidates, both absent controls rejected. The estimate/final
flag is missing on12/14. Reference `docs/evidence/bahrain_hud_ocr_holdout_v2.json`
was transcribed from original-pixel crops before inspecting V2 OCR results.
The split is same-video only: close neighbors248/355 are strongly correlated
with earlier reviewed frames. No second independent annotator, low-fuel test,
multi-digit race-total test, live authority, source modification or refit.

Follow-up risk-choice implementation: `analysis/race_scenarios.py` adds pure
conditional short/long player fuel budgets and separate leader pace-switch
sensitivity. New scenario tests use synthetic numbers only (not recommendations
or model evidence). `bahrain_native_context_two_scenarios_v1/` replays the same
3899 source rows with added leader sensitivity; it does not invent a fuel-plan
menu, reserve, qualifying baseline or executed actions for this race. No refit,
training inclusion, source mutation or live change. The previous `_checked`
output remains the historical context-only version.

Race source remains read-only in LMU Telemetry:
`Bahrain International Circuit_R_2026-10-02T01_11_27Z.duckdb`.
Matched capture `race_20261002_011124_945002`: 3899 rows, finalized Ctrl+C,
six race laps and own finish present. Video `D:/OBS/2026-10-01 21-11-01.mp4`
has manually reviewed HUD frames under the separate generated audit folder.
Earlier capture `race_20261002_010905_769963` contains148 rows but an unfinalized
manifest; preserved and excluded, not merged into this race.

Read-only reconciliation: 3793 paired fuel samples, maximum absolute difference
0.00372L; interpolated tank at finish36.58588L, formation/pre-green1.10931L,
race17.30481L. No in-race pit event. Garage fuel resets excluded.
Raw Lap0 contains formation plus race lap1; native1–5 map to race2–6.
Driver review confirms accidents/spins race5–6 (native4–5), not localized.
All data remain diagnostic-only, no dataset sidecar/model refit. The HUD's
fractional total and fuel autonomy are manual evidence, not new API fields.

Follow-up software replay: `scripts/replay_native_race_context.py`, generated
`bahrain_native_context_v1_checked/`, same 3899-row source SHA256. Explicit
context states and causal last-observed-pace forecasts only; no new telemetry,
training labels, clean-lap qualification, model fit or cue authority. Null HUD
confirmed on every input row. Forecast output is exploratory, not model-ready
or a conservative fuel horizon. Earlier `bahrain_native_context_v1/` is retained
as the initial pre-review diagnostic; use the `_checked` output for this version.

## Boundary fuel replay — 2026-09-12

No new empirical telemetry or model refit. `fuel_budget_shadow_scenarios_v1`
contains seven synthetic software scenarios (16 boundaries), not race evidence.
Native HUD identity confirmed by driver. Raw HUD estimates remain diagnostics,
not inferred integer horizons. Prior circuit outputs and frozen packs untouched.

## Fuel-first development — 2026-09-12

No new telemetry collected. `four_circuit_harmonized_v1` preserves all223
canonical rows/targets/quality, harmonizing49 Sebring acceleration values from
existing push8–12 ratio profiles. Planned-dose acceleration is separate.
`four_circuit_response_candidates_v2` evaluates four forms on paired183 strict
or220 sensitivity rows, whole-circuit held out. These are development scores.
`sebring_fuel_first_decisions_v2_final` selects plans before joining initial
test5/6 outcomes; no retry replacement, no local response fit, no live change.
Mixed-zone recombinations are hypothetical, not executed race plans. See
`docs/fuel_first_development_review_2026-09-12.md`.

## Sebring phase qualification and compact four-circuit benchmark — 2026-09-12

All 49 LICO zone passages retained: 12 conservative retry passages and 37
exploratory passages. Annotations live in
`config/driver_reviews/sebring_phase_qualification_2026-09-12.json`; this is a
retrospective model-qualification mask, not confirmed driver-error labeling.
Native phase/recovery outputs are in `phase_qualification_v1` under the Sebring
transfer directory. T17 recovery has 6/7 coverage; retry lap10 lacks the required
next-lap100m. No extrapolation or automatic deletion of initial-attempt data.

`four_circuit_low_data_v1` contains a canonical historical table plus Sebring,
whole-circuit-held-out fits, paired model scores, all-pass sensitivity, and fixed
original-run calibration2/3 -> test5/6 adaptation diagnostics. Strict macro MAE
is 0.007817 L / 0.072528 s for action-only. No production ML-table replacement
or live promotion. See `docs/four_circuit_low_data_review_2026-09-12.md`.

## Sebring combined LICO review — 2026-09-12

Both attempts are analyzed together: initial A2/6 and B3/5 plus retry A8/10
and B9, totaling four A, three B and 49 audible cues. Partial push7 and B11 are
not complete scored laps. Final artifacts are in `combined_lico_analysis_final`
under the Sebring transfer directory. Prior five push and initial push1/4 are
separate reference scenarios. Descriptive median contrasts are 0.259686 L / +0.56 s
and 0.241575 L / +0.66 s respectively (fuel100–5800 m, time whole lap).
First-attempt driving errors remain unresolved; T1 push4 impact and T3 entry
pedal flags are preserved. No refit or model-ready promotion. See
`docs/sebring_combined_analysis_2026-09-12.md` for evidence and the next gate.

## Sebring partial first LICO attempt and ABAB retry — 2026-09-12

Run `sebring_lico_20260912_132042` was stopped during its final scheduled push
lap after a T1 error. The driver reports imperfect execution on some LICO
corners; no blanket clean label is assigned. Preserve all existing session
files and the native recording. Notes are retained in
`config/driver_reviews/sebring_first_lico_attempt_2026-09-12.json`; native
telemetry intake and localized lap-zone review remain pending.

The separate `lico_abab_retry_pack_v1` repeats the same frozen cue plan in
four scored laps A/B/A/B (28 beeps), with no scored push lap. It is a repeat
execution/familiarisation session, not a replacement for the original
predeclared calibration/test schedule. Prior push references require
session, fuel-load and driver-learning caveats. No model refit, zone-boundary
change or post-hoc evaluation split is authorized by this retry.
Instructions: `docs/sebring_abab_retry_run_sheet.md`.

## Sebring first push intake — 2026-09-12

### Prospective pack frozen after push review

`data/processed/experimental/sebring_lmp2_transfer_2026_09/lico_validation_pack_v1`
is ready for the first local LICO session. Two static plan IDs execute
P/A/B/P/B/A/P on seven approaches (28 audible cues expected). T5/T16 remain
silent and are included in the downstream outcome groups of T3/T15. No local
LICO observation has been added or refit. Prior push references are native
laps8–12; future calibration is scored laps2/3 and the fixed test is laps5/6.
All35 frozen outcome starts have nonzero filtered and driver throttle. Sensor
correlation is at least0.974 across the five laps. Direct acceleration values
at proposed lifts and wide upstream capture are saved separately from actions.
Synthetic and recorded-push replay checks both emit28 recorded cues, no system
audio; replay cues are all on time. Suite343 tests plus the added launcher
regression pass, Ruff clean, PowerShell AST valid. Interruption cannot be
announced as completion without a logged crossing beyond the seventh lap.
Only the simulator can validate actual audio/heard count and driver execution.
Instructions: `docs/sebring_lico_validation_run_sheet.md`.

Run `sebring_push_20260912_114122`, native source
`data/Sebring International Raceway_P_2026-09-12T15_41_46Z.duckdb` copied with
matching SHA-256; original retained. Driver reports no notable errors. Retain
native laps8–12; exclude partial pit outlap7. Lap13 has no closing event.
Reviewed sidecar: `config/datasets/sebring_lmp2_circuit_d_reviewed_2026-09-12.json`.
Five complete push laps pass core channel coverage; nine repeated main braking
landmarks are exploratory. Three coast flags fall within preceding braking and
are not intentional LICO actions. Zone-start and recovery checks remain pending.
No model refit or live cue authorization. Full record and reproduction:
`docs/sebring_push_intake_2026-09-12.md`.

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

## Cross-circuit ML pack — 2026-09-10

The first pooled LMP2 table is rebuilt from the 13 available Spa runs and four
historical Paul Ricard runs at one row per `run / lap / zone`. It contains 663
raw observations across 14 circuit-zone definitions. The pack lives under
`data/processed/experimental/cross_circuit_ml_v1/` and includes raw CSV/Parquet
observations, a feature-role registry, eight split assignments, fold-local push
references, fold feature views and a hashed build manifest.

The builder deduplicates native telemetry by SHA-256 and refuses to ingest the
locked confirmation run `paul_pilot_20260909_232207`. Baseline means, action
ratios and fuel/time deltas are fitted after the split from the authorized push
rows. Existing Spa `baseline_mean_*` columns are not carried into the pooled
raw table. This pack is model-ready infrastructure, not evidence that the
Spa↔Paul transfer already generalizes.

`diagnostic_action_only_predictions.csv` and
`diagnostic_action_only_metrics.csv` contain the first retrospective stress
tests. They now contain the full action-only benchmark, an action-only fit on
the acceleration-available paired subset, and a two-term monotone model using
`action` plus `action × push acceleration at the lift`. The acceleration
profile is reconstructed at physical lead ratios `0`, `0.25`, `0.5`, `1.0`
and `1.5` from
fold-authorized push laps. Sixty fold-zone profiles meet the acceleration
support gate; 42 also meet the stricter physical braking-denominator gate.

On equal rows, acceleration does not yet improve the two-circuit transfer
stress test. Spa→Paul is unchanged for fuel (`0.00641 L` MAE) and time
(`0.11255 s`); both fitted interaction slopes are zero. Paul→Spa is slightly
worse than paired action-only for fuel (`0.00777` vs `0.00751 L`) and time
(`0.07510` vs `0.07280 s`), although the fitted time interaction is positive.
This is evidence that the variable is physically relevant but not identified
well enough by only two circuit tasks and the current linear form. The files
remain diagnostic and must not be mistaken for frozen predictions on a new
circuit.

## Bahrain circuit-C push collection — prepared 2026-09-10

Bahrain is selected prospectively as circuit C because the driver reports high
repeatability and the standard Grand Prix layout contains clear
long-straight/heavy-braking LICO opportunities. The first session is registered
as `baseline_push_01` under protocol `bahrain_lmp2_circuit_c_v1`. It requires
five clean full-push laps with 55 L at garage departure, zero tire wear,
constant weather, one unchanged setup and native LMU DuckDB recording. Up to
two replacement laps may be recorded, but all laps and driver notes must be
retained.

The frozen push-only pack contains no LICO plan, cue or audio path. It creates
the operator session, preserves lap notes and links the newest native DuckDB.
No Bahrain LICO prediction may be frozen until this run passes intake and its
physical braking/acceleration zones are reviewed.

### Bahrain Push Baseline 01 — recorded 2026-09-11

- File: `data/Bahrain International Circuit_P_2026-09-12T01_49_14Z.duckdb`
- SHA-256: `36ed02a48914b285ed449183e67f1942bf4bc275484aea57bcba2efe178994bb`
- Run id: `bahrain_push_20260911_212732`
- Collection design: `baseline`
- Complete intervals: laps `15–20`; lap15 is the outlap and laps16–20 are push.
- Unclosed context: lap21 contains only about `4.27 s / 301 m` after the line.
- Clean whole laps: `16, 17`.
- Borderline but locally usable laps: `18, 19, 20`.
- Driver review: displayed lap19 maps to stored lap18 and has a wide T15 exit;
  displayed lap20 maps to stored lap19 and has a rear slide/wide T4 exit;
  displayed lap21 maps to stored lap20 and has excessive T15 apex speed plus a
  wide exit.
- Intake interpretation: preserve all unaffected zones plus pre-action and
  brake-onset descriptors in the affected zones. Mask T15 exit outcomes on
  lap18, T4 mid/exit outcomes on lap19, and T15 brake-release/apex/exit outcomes
  on lap20. Do not use the affected complete-zone time/fuel values as clean push
  targets.
- Native channel continuity: no sampling gaps in brake, throttle, distance,
  speed, fuel, longitudinal-G or tyre-temperature timelines; no post-initial
  impact transition was recorded. The native `G Force Long` channel is present,
  but its alignment with speed-derived longitudinal acceleration has not passed
  the coherence gate and remains diagnostic until resolved.
- Status: run metadata validates against the frozen protocol. Eight repeatable
  physical brake clusters have five ready observations each. T05–T07 and T13
  remain validation-only; six zones enter the first live block. Phase-specific
  masks leave T04 with four clean outcome references and T14–T15 with three,
  while preserving five brake-onset/acceleration references.

### Bahrain zero-LICO-shot validation — frozen 2026-09-11

The prospective plan `bahrain_lmp2_zero_lico_shot_static_v1` was frozen before
any Bahrain LICO outcome. Its action-only monotone response was fitted on 187
unique historical LICO observations from Spa and Paul Ricard only. Bahrain
contributes push braking geometry and speed-derived acceleration profiles, not
response targets. The acceleration interaction remains shadow-only; a
pre-action acceleration-weighted guard caps every selected action.

The next run is exactly `P/L/L/P/L/L/P`. Six zones use conservative physical
ratios between about `0.35` and `0.47`; T05–T07 and T13 are silent. The pack at
`data/processed/experimental/bahrain_lmp2_transfer_2026_09/lico_validation_pack_v1/`
hashes its raw push input, historical model artifacts, predictions, plan and
launchers. Synthetic runtime preflight emits 24 cues and logs 48 crossings.

### Bahrain zero-LICO-shot validation — recorded and scored 2026-09-11

**Historical analysis_v1: local timing/fuel metrics below are superseded by the
native timestamp correction in analysis_v2_final. See the correction entry
and `docs/bahrain_transfer_review_2026-09-11.md`. The original predictions and
raw recording remain unchanged.**

- Run id: `bahrain_lico_20260911_224825`.
- Native file: `data/Bahrain International Circuit_P_2026-09-12T02_48_51Z.duckdb`.
- SHA-256: `bf4a2f5e679629efb0e78f7476d962102697b38cdaac000179e1f1c7eac23054`.
- Complete scored block: push laps `23, 26, 29`; LICO laps `24, 25, 27, 28`.
- Execution: 24 enabled cues, all fired on time, with a maximum absolute cue
  error of `1.442 m`. The driver reported no notable error and judged the zone
  selection and lift points appropriate except for an overly strong T10 action.
- Whole-lap prospective result: median observed saving `0.1731 L/lap` for an
  official median cost of `0.400 s/lap`, versus the frozen prediction of
  `0.2186 L/lap` and `0.5820 s/lap`.
- Recovery-aware T10 result: `0.0315 L` saved for `0.2945 s` lost at the
  executed median action of `60.9 m`; individual time losses span
  `0.1921–0.3812 s`. The frozen T10 window ended at `2800 m` and therefore
  understated the cost that persisted down the following acceleration zone.
- Decision: retain T01–T03, T04, T08, T11 and T14–T15 for the next model
  iteration; keep T05–T07 and T13 silent; remove the tested 65 m T10 action
  from the efficient plan. A later T10 retest, if useful, must be isolated and
  much lighter rather than folded into the next broad validation block.
- Audit note: native `LastImpactMagnitude` toggled near `750 m` on push lap29.
  The driver reported no incident and lap29 was the fastest lap, so it remains
  included with a review tag. The previous Bahrain push baseline closely
  matches the same-run push medians, including T10 (`11.28 s` and about
  `0.224 L` in both), supporting the counterfactual used here.
- Reproducible outputs: the session's `analysis_v1/` directory, built by
  `scripts/analyze_bahrain_lico_validation.py`. Silent-zone differences are
  contextual diagnostics only because no LICO action occurred there; they are
  not interpreted as causal zone savings or costs.

### Bahrain correction and three-circuit ML v2 — 2026-09-11

The live scoring distance was repeated between approximately 0.20 s updates;
analysis_v1 wrongly interpolated from the last repeat. The new native
per-channel timestamp interpolation yields `0.17186 L` saved and `0.41367 s`
lost over 100–5350 m; official median lap loss remains `0.400 s`. T10's frozen
cost is `0.13285 s` and its extended diagnostic median is `0.19837 s`
(`0.12090–0.30543 s`), with `0.03391 L` saved. Local negative T1 differences
remain observational, not evidence of a causal time benefit.

The corrected score loads and verifies session-frozen zones and predictions.
`docs/evidence/bahrain_score_manifest_v2.json` and
`docs/evidence/bahrain_zone_scores_v2.csv` retain small Git-tracked evidence.
All previous artifacts stay archived; the v1 scoring CLI is disabled to
prevent accidental reuse of the superseded interpolation.

The v2 ML pack contains 759 observations from three circuits and three grouped
folds. All outcomes use the corrected native rule. Scheduled push/silent
coasts do not fit responses; phase-specific masks preserve clean physical
evidence and independent support thresholds guard each target. Six Spa lap32
rows have non-monotonic distance and retain null outcomes. The Paul live
confirmation remains locked outside the table. A separate within-run Bahrain
adaptation study reserves laps27/28 across 0/1/2 calibration budgets; fuel
improves rapidly, time modestly, and transfer has not yet beaten local-only
estimation convincingly. Full decisions and reproduction commands are in
`docs/bahrain_transfer_review_2026-09-11.md`.
