# LICOR restart plan — September 2026

Status: active plan, agreed direction as of 2026-09-07. Technical preparation
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
- [x] Generate a frozen Paul static live-cue pack with telemetry and event logs,
  operator commands, expected outputs and a replay/audio preflight.
- [x] Verify the end-to-end path with a focused integration check. Resolve the
  bootstrap cap test discrepancy and local environment import/install issue
  if required by this path; avoid unrelated formatting changes.

Exit: the pack can be rebuilt without manually supplied intermediate CSVs,
references the current zone definitions, and passes replay/preflight checks.
Only then provide the driver the exact commands and one-page run sheet.

Stage A software preparation is complete. The pack and
[French operator run sheet](paul_ricard_static_pilot_run_sheet.md) are available.
Reconstruction produced 31 complete laps, 25 modeling-eligible laps and 150
candidate passes (one explicit T03 exclusion). The new plan selects T03 at
36.58 m and T08-T09 at 94.49 m, predicting 0.05596 L and 0.10889 s per LICO lap.
These remain exploratory predictions. Synthetic 5/6/7-lap schedules and the
46,078-sample recorded Paul replay passed, with no audio on push/outlap roles.
Real audio perception and LMU capture must be checked at the session preflight.

Rebuild commands from the project root:

```powershell
uv run python scripts/build_paul_ricard_intake.py
uv run python scripts/build_paul_ricard_pilot_plan.py
uv run python scripts/build_paul_ricard_pilot_pack.py
```

The final command refuses to overwrite a frozen pack; choose a fresh
`--pack-dir` for a new version. For the existing pack, run it with `--verify-only`.
The real replay command is `uv run python scripts/verify_paul_ricard_pilot_replay.py`;
use a fresh `--output-dir` when repeating it. Historical transfer outputs and the
first failed-preflight pack (`pilot_pack_failed_01`) are preserved separately.

Verification on 2026-09-07: all 262 tests passed via `uv run pytest tests` with an
isolated temporary directory. A bare `pytest` discovery also searched generated
data and hit a locked Windows temporary folder; explicitly target `tests`.

## B. One short static pilot run

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

After the Paul measurement loop works, prioritize circuit diversity over many
additional Spa laps. A working collection target is 4–6 circuits total, not a
guarantee of sufficient statistical power. Record vehicle, driver and setup
context so future effects can be distinguished rather than silently pooled.

Prototype a hierarchical fuel/time model with partial pooling or a multitask
Gaussian process, using pre-action zone descriptors and normalized lift action.
Calibrate uncertainty and detect unsupported contexts. Consider active selection
of the next experiment once uncertainty is reliable. Defer deep meta-learning
and reinforcement learning until simpler baselines and task diversity justify them.

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
