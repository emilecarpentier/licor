# Spa Adaptive Live Validation Protocol

This document defines the exact next-step protocol for LICOR's first pilot
validation outside the offline lab.

The goal is not to prove the whole adaptive system in one session. The goal is
to answer one practical question first:

```text
Do the current cue distances feel timely, natural, and executable enough to
deserve a real recommendation-execution dataset?
```

## Scope

This protocol is intentionally staged.

Stage 1 is executable now:

- use the current experimental Spa live plans;
- validate cue feel in a short driving session;
- capture enough metadata and notes for later intake;
- treat the run as a supervised recommendation-execution pilot.

Stage 2 is now executable in a bounded operator-preview form:

- derive a guarded adaptive handoff from a validated static baseline run;
- freeze that handoff as a new follow-up live plan;
- validate it as its own short live session before any in-session authority is
  granted.

Stage 3 remains blocked for now:

- true adaptive live replanning during the same session;
- next-lap plan updates inside the running cue loop without operator-confirmed
  freeze between blocks.
- session-level reaction-time or cue-latency recalibration inside the live
  validation loop.

The current repo can already validate that adaptive handoffs make sense in
offline replay. It now also includes:

- a first static LMU shared-memory cue runner for true in-session feel
  validation;
- a guarded operator-facing handoff export that can be frozen as a follow-up
  adaptive preview session.

It still does not provide a polished real-time adaptive session harness. Do not
pretend otherwise in the first pilot.

The idea of adapting cue-latency compensation to the driver's effective
reaction time is now a documented future backlog item. It should not be tuned
ad hoc during the current Spa live-validation blocks; the current
`selected_zones_latency_v2` speed-aware baseline remains the reference until the
cross-circuit transfer design work is further along.

Important:

- replay validation is the canonical dry run for plan order, cue coverage, and
  planned-versus-observed schema compatibility;
- replay audio emission is not a substitute for real in-session cue timing
  feel, because the current replay helper does not behave like a polished
  real-time operator loop.

## Canonical Inputs

Use these artifacts as the fixed starting point for the first pilot:

- official static live baseline, selected-zones variant:
  `data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_selected_zones_latency_speed_aware_plan.csv`
- secondary static live comparison variant:
  `data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_all_eligible_latency_speed_aware_plan.csv`
- adaptive replay validation report:
  `data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_validation_report.html`
- replanner validation report:
  `data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_replanner_validation_report.html`
- range-aware variant summary:
  `data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_range_aware_variant_summary.csv`

The selected-zones latency v2 plan is now the frozen live baseline. Keep the
all-eligible latency v2 plan as an optional comparison block, not as the
default operator plan.

Operator packs can be generated with:

```powershell
uv run python scripts/build_spa_live_validation_pack.py
```

This writes ready-to-use pack folders under:

```text
data/processed/experimental/spa_dynamics_v1/live_validation_packs/
```

For the operator-grade A-to-Z session procedure, use:

```text
docs/spa_live_run_playbook.md
```

For the next adaptive follow-up collection block derived from the guarded
between-laps handoff, use:

```text
docs/spa_adaptive_handoff_preview_playbook.md
```

Preflight checks now available:

```powershell
uv run python scripts/run_lmu_live_cues.py --doctor
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
```

## Candidate Variants

### Candidate A: Official frozen selected-zones baseline

Plan file:

```text
spa_lmp2_experimental_live_candidate_selected_zones_latency_speed_aware_plan.csv
```

Plan id:

```text
experimental_live_candidate_range_aware_selected_zones_latency_v2
```

Current cues:

- `T01`: `70 m`
- `T05-T06`: `180 m`
- `T08`: `70 m`
- `T10-T11`: `60 m`
- `T12-T13`: `100 m`
- `T18`: `132.1646 m`

Why this is now the baseline:

- fewer active zones than the all-eligible variant;
- no `T14` cognitive overhead in the first block;
- already aligned with the current experimental base case;
- now latency-compensated with zone-speed-aware cue timing.

### Candidate B: Secondary all-eligible comparison

Plan file:

```text
spa_lmp2_experimental_live_candidate_all_eligible_latency_speed_aware_plan.csv
```

Plan id:

```text
experimental_live_candidate_range_aware_all_eligible_zones_latency_v2
```

Current cues:

- `T01`: `60 m`
- `T05-T06`: `180 m`
- `T08`: `70 m`
- `T10-T11`: `40 m`
- `T12-T13`: `100 m`
- `T14`: `20 m`
- `T18`: `132.1646 m`

Why keep it second:

- it adds the `T14` micro-LICO helper;
- it slightly relaxes `T01` and `T10-T11`;
- it is useful only after Candidate A feels stable enough.

### Candidate C: Guarded adaptive follow-up preview

Plan file:

```text
data/processed/experimental/spa_dynamics_v1/live_validation_packs/selected_zones_latency_v2_guarded_preview/plan.csv
```

Plan id:

```text
experimental_guarded_adaptive_handoff|selected_zones_latency_v2_baseline|adaptive_guarded|observed_execution:recommendation_execution_selected_latency_v2_02|lap_8_to_9
```

Why this exists:

- it is the first operator-facing frozen plan derived from the guarded adaptive
  between-laps logic rather than from the static optimizer alone;
- it lets LICOR validate adaptive readability and cue feel without pretending
  true in-session plan swapping already exists;
- it is the next data-collection step after the frozen baseline has proven
  stable.

## What The First Pilot Is Allowed To Decide

The first pilot may decide:

- whether the frozen selected-zones baseline still feels stable in repeated
  live use;
- whether Candidate B adds useful flexibility without adding distraction;
- whether the frozen guarded adaptive follow-up remains readable when promoted
  from shadow into its own live block;
- which zones feel obviously too early, too late, or awkward in real driving;
- whether the cue loop deserves a real recommendation-execution dataset.

The first pilot must not decide:

- final model truth;
- fuel/time refits;
- tire or fuel-load effects;
- final adaptive live controller quality.

The next adaptive-preview pilot must also not decide:

- that true automatic between-lap plan switching is already justified from one
  or two frozen follow-up runs;
- that the controller may change plans in-session without an operator review
  layer.

## Evaluation Axes

Judge the pilot on two separate axes.

### Axis 1: software and instrumentation health

This axis passes only if:

- the frozen plan file is the one actually used;
- the exact `plan_id` is preserved;
- cue events are logged;
- the raw telemetry file is preserved;
- lap notes are preserved;
- the run can be reconstructed into the same planned-versus-executed review
  schema already used offline.

If any of those are missing, the session may still be useful for feel, but it
does not count as a real recommendation-execution validation run.

### Axis 2: driver execution and cue feel

This axis is the actual pilot-feel question:

- are cues timely?
- are they natural?
- can they be executed without fighting the car?

Do not collapse Axis 1 and Axis 2 into a single pass/fail statement.

## Hard Gates Before Driving

All of the following must be true before a live session starts:

1. The two HTML reports above have been skimmed and no red flag stands out.
2. The exact plan CSV for the session has been frozen and recorded.
3. The audio path has passed a simple bench check:
   - the chosen adapter emits one audible cue;
   - cue volume is high enough to hear under driving load;
   - there is no repeated or stuck tone.
4. Session notes can be captured immediately after each lap with minimal
   friction.
5. The session is not also trying to test setup changes, weather changes, or a
   different car baseline.
6. The session plan has been frozen before driving, and no refit or plan edit
   will be done until the pilot is judged.
7. A zone-by-zone pre-drive signoff has been done for `T05-T06`, `T12-T13`,
   and `T18`.

If any gate fails, do not start the pilot.

## In-Game Session Setup

Use a stable, low-confound session setup:

- track: Spa-Francorchamps;
- car/class: same LMP2/car setup used for recent Spa validation work;
- weather: dry and stable;
- tire wear: off;
- fuel usage: on;
- start fuel: `45-55 L`;
- traffic: minimized if possible;
- no setup experiments during the pilot;
- same audio device and volume across both blocks.
- if session budget allows, one short same-day cue-free baseline block after the
  pilot for context.

Rationale:

- this first session is about cue feel and execution shape;
- tire wear is intentionally removed to keep the session simpler;
- fuel remains on so the run can still become a real recommendation-execution
  artifact later.

## Session Structure

### Block 0: Bench And Garage Check

Before the driving block:

1. Confirm the exact candidate plan file.
2. Confirm the exact `plan_id`.
3. Confirm the audible cue is working.
4. Write the run nickname before leaving the garage.
5. Run the LMU live-cue process with the frozen candidate plan.

Recommended run nicknames:

- `recommendation_execution_selected_latency_v2_01`
- `recommendation_execution_all_eligible_latency_v2_01`

Recommended Candidate A launch command:

```powershell
uv run python scripts/run_lmu_live_cues.py `
  --plan data/processed/experimental/spa_dynamics_v1/live_validation_packs/selected_zones_latency_v2/plan.csv `
  --event-log data/processed/experimental/spa_dynamics_v1/live_validation_packs/selected_zones_latency_v2/live_events.csv `
  --run-id recommendation_execution_selected_latency_v2_01 `
  --file-name recommendation_execution_selected_latency_v2_01 `
  --emit-system-beep `
  --max-laps 6
```

### Block 1: Candidate A Live Feel Check

Use the frozen selected-zones baseline first.

Lap structure:

1. out lap: not scored
2. lap 1: familiarization lap, not scored
3. lap 2: first interaction lap, not scored by default
4. laps 3-5: scored clean laps
5. lap 6: optional confirmation lap if exactly one primary zone remains unclear

Primary zones for this block:

- `T01`
- `T05-T06`
- `T08`
- `T10-T11`
- `T12-T13`
- `T18`

Priority attention during this block:

- `T05-T06`: cue timing can feel busiest here
- `T12-T13`: check whether `100 m` feels natural, not mathematically forced
- `T18`: check whether the cue is executable without fighting the car
- `T10-T11`: expected to feel like a light, natural LICO

### Block 2: Candidate B Comparison

Only run this block if Block 1 passes the go criteria below.

Use a separate telemetry recording for Candidate B. Do not mix Candidate A and
Candidate B inside one LMU file if the session is meant to become a real
`recommendation_execution` artifact later.

Lap structure:

1. one reset lap
2. three scored clean laps

Focus questions for this block:

- does `T14 = 20 m` feel almost invisible and harmless?
- does `T01 = 60 m` feel better, worse, or the same as `70 m`?
- does `T10-T11 = 40 m` still feel natural, or does it become too small to be
  worth the cognitive load?

Candidate B should not be promoted from one ordered A-then-B feel comparison
alone. Keep it only if later evidence shows repeated driver preference or
clearer planned-versus-executed behavior than Candidate A.

## Lap Notes

Use a deliberately tiny coding system so notes do not become the workload.

Per zone:

- `N`: natural
- `E`: too early
- `L`: too late
- `A`: awkward but still manageable
- `S`: unsafe or unacceptable
- `X`: invalidate this zone for the lap because of traffic, mistake, or loss of
  focus

Suggested lap sheet:

| Lap | Variant | T01 | T05-T06 | T08 | T10-T11 | T12-T13 | T14 | T18 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | selected | | | | | | n/a | | familiarization only |
| 2 | selected | | | | | | n/a | | |
| 3 | selected | | | | | | n/a | | |
| 4 | selected | | | | | | n/a | | |
| 5 | selected | | | | | | n/a | | optional |
| 1 | all_eligible | | | | | | | | reset lap |
| 2 | all_eligible | | | | | | | | |
| 3 | all_eligible | | | | | | | | |
| 4 | all_eligible | | | | | | | | |

Use the Notes column only for short, important remarks such as:

- `T05-T06 beep felt rushed`
- `T18 cue good but required commitment`
- `traffic invalidated T01/T05-T06`

Per-zone conclusion rule:

- a zone may be marked `provisionally_ok` only after at least two clean
  non-`X` observations in that zone;
- a zone may remain `unknown` after the block, and that is acceptable.

## Stop And Abort Rules

Stop the current block immediately if any of these happen:

- any cue in `T01`, `T05-T06`, or `T18` feels unsafe;
- the same primary zone is `E`, `L`, or `S` on two clean laps in a row;
- more than two primary zones feel `A` or worse on the same clean lap;
- cue audibility becomes unreliable;
- the driver feels overloaded enough that the notes would no longer be honest.

Abort the whole pilot if:

- the cue system behaves inconsistently;
- the first block never produces at least two clean scored laps;
- the driver has to start compensating for the system instead of driving the
  car.

## Go / No-Go Criteria

### Candidate A passes if:

- at least three clean scored laps exist;
- no primary zone is marked `S`;
- no more than one primary zone is marked `E` or `L` on two clean laps in a
  row;
- the driver would be willing to run another short stint with the same cue set.

If Candidate A fails, stop live testing and return to offline review.

### Candidate B is worth keeping only if:

- `T14` stays non-distracting;
- the relaxed `T01` / `T10-T11` points do not make the session feel worse;
- the driver would actually choose this variant over Candidate A.

If Candidate B adds no clear benefit, the selected-zones latency v2 baseline
remains the default live plan.

## Data Capture Requirements

This pilot should be treated as the first true
`recommendation_execution`-style collection candidate.

Keep the following together:

- raw telemetry file;
- exact exported plan CSV used;
- exact `plan_id`;
- raw cue event log if a live logging path is available;
- lap notes from the table above;
- session-level notes such as audio device, weather, and anything unusual.

Hard rule:

- incomplete logs mean no formal conclusion for recommendation-execution
  readiness.

When the run is later added to the dataset sidecar, preserve at least:

- `collection_design = recommendation_execution`
- `target_zones_source = from_exported_plan`
- `planned_lico_profile_id`
- `audio_cue_plan_id = <exact plan_id>`
- `execution_quality`
- `labels_quality`
- driver notes

Suggested `planned_lico_profile_id` values:

- `spa_exp_live_candidate_selected_latency_v2`
- `spa_exp_live_candidate_all_eligible_latency_v2`

## Post-Session Review

After the session:

1. decide whether each scored lap is clean enough for review;
2. preserve the lap sheet before watching any replay;
3. compare the notes against the exported plan, not against memory alone;
4. judge software/instrumentation health separately from driver execution;
5. only then decide whether one zone needs offline re-review;
6. do not refit any model until the pilot is judged and archived as a frozen
   review input.

The first post-session question is not:

```text
Did the model prove itself?
```

It is:

```text
Did the cues feel plausible enough to justify a real recommendation-execution
intake and review cycle?
```

Any positive conclusion must stay scoped to the exact operating window tested:

- dry;
- stable conditions;
- tire wear off;
- roughly `45-55 L` starting fuel;
- the exact exported plan used in the session.

## Transition To The Next Phase

If Candidate A or Candidate B passes, the next project step is:

1. collect and ingest the real recommendation-execution run;
2. link it to the exact `audio_cue_plan_id`;
3. review planned-versus-executed evidence with the same schema already used in
   offline replay;
4. only then decide whether the real-time adaptive bridge should be built next.

If both candidates fail, do not jump to broad new data collection. Return to
offline review for the specific failed zones first.
