# Dataset Log

This file documents local telemetry datasets used during LICOR development.
Raw `.duckdb` files stay outside Git. This log keeps the labels, valid laps, and
driver notes needed to reproduce analyses.

A machine-readable mirror of the current working lap labels lives at
`config/datasets/spa_lmp2_v2_2026-05-21.json`. The older
`config/datasets/spa_lmp2_2026-05-14.json` sidecar remains as the historical
v1 snapshot. Keep this document as the human source of driver context, and
update the JSON used by the pipeline when lap labels change.

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

Current interpretation after four Spa v2 `controlled_random` runs:

- controlled-random coverage is now strong enough to refit Spa zone curves
  before scheduling targeted-zone collection;
- targeted-zone runs are no longer the default next step and should be used
  only if post-refit diagnostics still show weak bins, unstable optimizer
  choices, or zone-boundary uncertainty;
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
