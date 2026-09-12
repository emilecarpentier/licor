# LICOR restart plan — September 2026

Status: active plan, updated with the first six-zone run on 2026-09-09. Technical preparation
below is pending unless explicitly checked. This document supersedes the May
ordering in the historical roadmap and transfer design document.

## Objective and scope

Make fuel-saving recommendations whose local time cost and achieved savings
are measured on unseen runs, then reduce calibration effort on new circuits.
Use the same LMP2 vehicle first. Extend to drivers and setups with recorded
context and short local calibration; other vehicles/categories require their
own evidence. The current Paul bootstrap uses heuristic priors and local data;
it is not evidence of learned transfer from Spa.

Retain the zone-level objective, deterministic optimizer, raw read-only
ingestion, driver annotations, static cue runner and frozen plan mechanism.
Treat current dynamics fits as explanatory, robust ranges as heuristic, and
adaptive replay as a controller audit until independently validated.

## A. Prepare Paul Ricard before simulator time

- [x] Record the driver-confirmed additional 75 m upstream start margin for T03
  and T08-T09 in the zone config and manual checklist. This is an approximate
  capture boundary, not a requested lift distance.
- [x] Record static driving followed by offline adaptive replay as the workflow.
- [x] Inspect raw telemetry/zone reports and reconcile the remaining checklist
  changes: T01 upstream start, T03 end +50 m, T12 start/end. Keep T15 excluded
  from optimization and preserve the T03 lap-zone mistake annotation.
- [x] Add Paul dataset metadata for both push and both controlled-random runs,
  with quality review and durable driver exclusions.
- [x] Implement a reproducible raw-to-pass path, rebuild quality/readiness,
  then passes, curves, models, priors and the static plan. Record input/config
  hashes and code revision; use portable paths. Retain prior outputs as history.
- [x] Inspect the rebuilt T14/T11 recommendations and any change in zone
  selection. The previous 0.05 L/lap target is a pilot target, not a demonstrated
  requirement to reduce stop count. Paul pit/refill assumptions remain provisional.
- [x] Generate a frozen Paul static prediction-validation pack with telemetry
  and event logs, operator commands, expected outputs and a replay/audio
  preflight. Keep it distinct from minimum-time race-strategy selection.
- [x] Verify the end-to-end path with a focused integration check. Resolve the
  bootstrap cap test discrepancy and local environment import/install issue
  if required by this path; avoid unrelated formatting changes.

Exit: the pack can be rebuilt without manually supplied intermediate CSVs,
references the current zone definitions, and passes replay/preflight checks.
Only then provide the driver the exact commands and one-page run sheet.

Stage A software preparation is complete. The pack and
[French operator run sheet](paul_ricard_static_pilot_run_sheet.md) are available.
Reconstruction produced 31 complete laps, 25 modeling-eligible laps and 150
candidate passes (one explicit T03 exclusion). A first live run showed that the
minimum-time `0.05 L/lap` strategy plan exposed only T03 and T08-T09; this was
an objective mismatch, not a data limit. That two-zone pack and its session are
preserved as prospective history.

The replacement `prediction_validation` profile selects one dense observed bin
for each candidate: T01-T02 33.96 m, T03 36.58 m, T08-T09 94.49 m, T11 59.64 m,
T12 36.42 m and T14 32.95 m. Their descriptive model sum is 0.12855 L and
0.37222 s per LICO lap, but it is not a race recommendation. Synthetic 5/6/7-lap
schedules and the 46,078-sample recorded Paul replay pass with 6 zones and no
audio on push/outlap roles. The runtime now projects between 0.20 s LMU scoring
distance updates; offline replay of the six first-run audio crossings reduces
mean absolute trigger error from 9.55 m to 0.68 m. The first six-zone session is
now recorded and scored provisionally below; audio perception still awaits the
driver debrief.

Rebuild commands from the project root:

```powershell
uv run python scripts/build_paul_ricard_intake.py
uv run python scripts/build_paul_ricard_pilot_plan.py
uv run python scripts/build_paul_ricard_pilot_pack.py
```

The final command refuses to overwrite a frozen pack; choose a fresh
`--pack-dir` for a new version. For the existing pack, run it with `--verify-only`.
The real replay command is `uv run python scripts/verify_paul_ricard_pilot_replay.py`;
use a fresh `--output-dir` when repeating it. Historical transfer outputs, the
two-zone `paul_ricard_pilot_2026_09` outputs and the first failed-preflight pack
(`pilot_pack_failed_01`) are preserved separately. Current outputs are under
`paul_ricard_prediction_validation_2026_09`.

Verification on 2026-09-07: all 262 tests passed via `uv run pytest tests` with an
isolated temporary directory. A bare `pytest` discovery also searched generated
data and hit a locked Windows temporary folder; explicitly target `tests`.

## B. One short static pilot run

The first seven-lap session is complete: `paul_pilot_20260909_220534` used push
laps 13/16/19 and LICO laps 14/15/17/18. It produced all 24 expected audible
cues (six zones by four LICO laps), all within tolerance, with a maximum absolute
trigger error of `1.331 m`. Projection-aware scoring with linear interpolation
between the bracketing push laps gives provisional means of `0.1584 L` saved and
`0.3191 s` lost per LICO lap. The frozen plan predicted `0.12855 L` and
`0.37222 s`.

Reproduce that scoring from the project root with:

```powershell
.venv\Scripts\python.exe scripts\analyze_paul_ricard_live_validation.py --session-dir .\data\processed\experimental\paul_ricard_prediction_validation_2026_09\sessions\paul_pilot_20260909_220534
```

The driver confirmed hearing all 24 cues. This closes the operational cue/audio
part of Stage B. It does not validate fuel or time: LMU telemetry recording was
not active, no `.duckdb` exists, and the driver remembers unclean laps but
cannot identify them. The CSV-only fuel/time values are therefore descriptive,
the session is permanently ineligible for refitting, and
`refit_authorized=false` remains mandatory. It also contains 24 beep-correlated
sample gaps of `0.100` to `0.129 s`; the beep now runs in the background for
future collection.

The smallest follow-up is one five-scored-lap confirmation run using the same
frozen six-zone plan: P / L / P / L / P. Start at 55 L, keep tire wear at zero
and weather constant, explicitly confirm that LMU telemetry recording is active
before launching LICOR, and note any dirty absolute lap number before leaving
the simulator. If a lap is compromised and its number is known, preserve it as
an explicit exclusion rather than guessing later.

Simulator time is the limiting resource. The driver can provide 5–7 consecutive
clean laps with tire wear disabled. Tire temperature and fuel load can still
vary. An outlap is not a scored lap. Keep setup and conditions recorded and
the selected LICO plan fixed during the experiment.

Suggested scored sequences (P = push, L = fixed LICO plan):

| Available laps | Sequence |
| --- | --- |
| 5 | P / L / P / L / P |
| 6 | P / L / L / P / P / L |
| 7 | P / L / L / P / L / L / P |

The five- and seven-lap sequences balance mean lap position between conditions;
the six-lap sequence approximately balances it. None eliminates all drift.
Choose the sequence before the run and record deviations. Cue enable/disable
on push versus LICO laps must be covered by the operator preflight.

Assess audio timing and actual lift execution on LICO laps, and compare zone
fuel/time with same-run push observations. Log starting fuel, cue misses,
traffic, errors and actual distances. Apply quality rules independently of
whether the result agrees with the model. A missed cue is an execution outcome,
not evidence of model accuracy at the requested lift distance.

Before collection, freeze predictions and the scoring method. Report individual
laps and uncertainty; a short run can yield an inconclusive outcome. Do not
invent numerical pass thresholds after seeing the results or claim precision
that the sample cannot support.

Exit: separate verdicts for operational cue execution and fuel/time prediction,
with exclusions and uncertainty visible. If prediction fails or remains
uncertain, identify the smallest targeted follow-up rather than collecting
broadly by default.

Current gate: the five-lap confirmation is recorded with a native DuckDB and
resolved lap-quality notes. All 12 software cues fired in tolerance and no
beep-correlated sampling gaps occurred. After excluding lap23 from whole-lap
scoring, T01–T02/lap23 for the confirmed T1 error and T14/lap23 for the probable
T13 contamination, native scoring retains ten zone observations and one clean
LICO lap. That lap saved `0.1823 L` for `0.6800 s`, versus `0.12855 L` and
`0.37222 s` predicted. The driver heard all 12 cues. The all-history verdict is
T03/T11 robust for the tested profile, T01–T02/T08–T09 promising, T12 unstable
on time cost and T14 insufficient. This is too little evidence for refitting;
`refit_authorized` stays false.

## C. Offline validation and adaptive replay

Replay adaptive decisions after the run. At each simulated lap boundary, use
only the information available by then. Inspect requested target changes,
distance changes, oscillation and sensitivity to missed cues. Recorded outcomes
belong to the static actions actually driven; they do not reveal the outcomes
of alternative adaptive actions.

Build leave-one-run/session-out prediction evaluation. Fit baselines,
normalization, feature selection and models within each training fold; do not
randomly split zone rows from the same run across train and test. Keep a future
recommendation-execution run untouched for prospective evaluation.

Compare existing piecewise curves, the robust heuristic and a simple monotone
alternative. Evaluate fuel/time error, interval coverage, target attainment
and plan time cost. Post-lift apex/exit/braking outcomes are diagnostic variables
unless a separate model predicts them using information available beforehand.

Exit: promotion to model-ready depends on repeated held-out evidence and useful
decision accuracy, not in-sample R-squared or curve shape alone.

## D. Low-data transfer and model development

Compare local-only fitting, current heuristic priors and a learned transferable
prior at equal local calibration budgets. Reserve a whole destination run for
testing; with further circuits, use leave-one-circuit-out evaluation. Report
learning curves, uncertainty, manual corrections and unsafe/unusable proposals.

The Paul measurement loop is now operational. Prioritize circuit diversity over
additional broad Spa or Paul collection. The immediate target is two more
circuits, for four circuits total; 4–6 remains the broader working range, not a
guarantee of sufficient statistical power. Per new circuit, use five clean push
laps followed by one seven-lap `P/L/L/P/L/L/P` varied-LICO block. Freeze the
zero-LICO-shot prediction before local LICO outcomes are visible. Record
vehicle, driver and setup context so future effects can be distinguished rather
than silently pooled.

The pooled run/lap/zone table and leakage-safe split harness now exist under
`data/processed/experimental/cross_circuit_ml_v1/`. Compare
the current local curve, the existing heuristic archetype and a simple
regularized/monotone pooled model. Spa-to-Paul and Paul-to-Spa are diagnostic
stress tests only because there are just two circuits. Split before baseline
construction and group by whole run/circuit; fit transforms on training only.
The first pooled comparison now includes an acceleration-conditioned monotone
model. Its pre-action acceleration is interpolated from fold-local clean-push
profiles at the proposed physical lift ratio; same-pass post-lift acceleration
is excluded. On the paired Spa↔Paul rows it does not yet beat action-only, so
acceleration stays mandatory in the contract but no performance claim is made
until circuits C and D add independent task variation.
After circuits C and D, evaluate leave-one-circuit-out before deciding whether a
hierarchical fuel/time model or multitask Gaussian process is justified. Use
only verified pre-action descriptors and the physical planned-lift-lead to
push-deceleration ratio. Defer deep meta-learning
and reinforcement learning until simpler baselines and task diversity justify them.

Select circuits C and D with a driver-repeatability gate. Score clean-lap and
brake/lift repeatability at double weight relative to physical diversity, and
reject a candidate below 3/5 for driver repeatability. The preferred pair is
one high-diversity circuit and one high-repeatability circuit. Bahrain is now
fixed as circuit C because the driver can repeat it reliably and it contains
clear long-straight/heavy-braking LICO opportunities. Circuit D remains open.
The Bahrain `baseline_push_01` protocol and push-only session pack are frozen.
Run `bahrain_push_20260911_212732` is now recorded in a native DuckDB: lap15 is
the outlap, laps16–20 are five complete push laps, and lap21 is only the short
post-line fragment. Driver display labels 19/20/21 map to stored laps18/19/20.
The first two push laps are clean whole laps. Lap18 retains a clean T15 approach,
braking and apex but has a contaminated exit; lap19 retains the T4 approach and
braking but has a rear-slide-contaminated mid/exit; lap20 retains T15 approach
and brake onset but its excessive apex speed and wide exit contaminate the
post-brake outcome. Build candidate zones from all usable physical inputs, keep
metric-specific masks on the affected outcomes, and freeze any Bahrain
zero-LICO-shot proposal before the varied-LICO block. The descriptor gate can
therefore be assessed without discarding three otherwise useful laps; reduced
T4/T15 outcome support must remain visible in uncertainty and can be augmented
by the push laps in the later `P/L/L/P/L/L/P` block.

That descriptor and freeze step is now complete. The first Bahrain static
validation selects T01–T03, T04, T08, T10, T11 and T14–T15 at respectively
`75/60/40/65/55/70 m`; T05–T07 and T13 remain validation-only. The normalized
actions are based on each zone's push braking distance, not the manual capture
window. Acceleration at the proposed lift is derived from push speed traces and
enforced as a guardrail; the learned interaction remains shadow-only. The
frozen pack passed hash verification and a 24-cue/48-crossing synthetic
preflight. Run `bahrain_lico_20260911_224825` has now completed that seven-lap
block. All 24 enabled cues fired on time. Against the same-run push laps, the
corrected median result is `0.1719 L` over 100–5350 m for `0.400 s/lap` lost, compared
with the frozen `0.2186 L` and `0.5820 s` prediction. Five of the six selected
zones remain useful candidates. T10 is the exception: once the outcome window
is extended for a recovery diagnostic, its 60.9 m executed coast costs a median
`0.1984 s` for `0.0339 L`, with a maximum of `0.3054 s`. Earlier local
values were biased by interpolation of repeated scoring distances and are
superseded by native timestamp scoring. Keep T05–T07 and T13 silent, deprioritize the tested T10 action from
the efficient plan, and preserve a very-light isolated T10 trial as optional.

The corrected prospective score is locked; ML v2 contains 759 observations and
three retrospective leave-one-circuit-out folds with native fixed-distance
targets throughout. A separate 0/1/2-lap within-run calibration study improves
fuel error quickly but provides only modest time improvement and no clear
advantage over local-only estimation. Broader capture envelopes and direct
push acceleration samples at candidate lifts now allow examination beyond the
old 200 m window without authorizing unvalidated large actions. See
`docs/bahrain_transfer_review_2026-09-11.md` for evidence and limitations.

Next, select circuit D using driver repeatability. Its five-push protocol is
prepared in `docs/circuit_d_push_protocol.md`; after intake, freeze two action
intensities per selected zone in a seven-lap P/A/B/P/B/A/P block. A fourth
circuit enables serious model development, not a guarantee of rapid learning
or transfer to new drivers, setups or aggressive actions.

Exit: transferred information reduces the local data needed to achieve a stated
held-out accuracy/decision target compared with local-only fitting.

## E. Later live authority and product work

Promote adaptive recommendations only after static validation and credible
offline checks, followed by a bounded prospective driving comparison. Driver
and setup adaptation require their own held-out groups. Dashboard polish follows
the validated recommendation loop.

## Working discipline

Each slice has a reproducible command, provenance, a focused check and a short
decision log. Keep historical artifacts distinguishable from current outputs.
Avoid expanding adaptive reports/scenarios while their empirical gates remain
open. Update this plan and the roadmap when a gate is passed or evidence changes
the direction. No stage here is marked complete merely because code exists.
