# Dataset Log

This file documents local telemetry datasets used during LICOR development.
Raw `.duckdb` files stay outside Git. This log keeps the labels, valid laps, and
driver notes needed to reproduce analyses.

A machine-readable mirror of the current lap labels lives at
`config/datasets/spa_lmp2_2026-05-14.json`. Keep this document as the human
source of driver context, and update the JSON when lap labels used by the
pipeline change.

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

Additional data should be collected only after the first pipeline can produce
reproducible tables from these files.

## Suggested Future Data

Collect later, after the first pipeline exists:

- one or two additional pit stop files to validate refill behavior;
- targeted LICO runs for Les Combes, Bus Stop, Pouhon, and Fagnes;
- a second clean `none` baseline to validate push-run stability;
- another circuit with mostly push laps to test generalization.
