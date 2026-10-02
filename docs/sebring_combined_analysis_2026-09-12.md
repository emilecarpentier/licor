# Sebring combined LICO analysis — reproducibility and decision record

## Evidence and scope

Final outputs: `data/processed/experimental/sebring_lmp2_transfer_2026_09/combined_lico_analysis_final/`.
The earlier `combined_lico_analysis_v1/v2` folders are intermediate development
outputs, not additional runs. Final output preserves quality flags through summaries.

Native files were read in place, not moved, deleted or modified. Their hashes
were stable before/after reading and are recorded in `manifest.json`. The two
LICO DuckDBs remain in the LMU Telemetry folder; do not treat generated analysis
as a backup of raw data. No dataset sidecar or model was changed.

- Prior push: `sebring_push_20260912_114122`, native 8–12.
- First attempt: `sebring_lico_20260912_132042`, push 1/4, A 2/6, B 3/5.
- Retry: `sebring_abab_20260912_134132`, A 8/10, B 9.
- First-attempt 7 and retry 11 have no closing native lap event; excluded from
  complete-lap scoring. First-attempt T1/7 has a driver-reported error.

There are four A and three B laps, 49 LICO zone passages, and 49 on-time cues.
The 98 contrast rows represent two reference choices for those same 49 passages.
The first attempt retains unresolved driver-error flags. The retry carries the
driver's report of no major errors, not unconditional certification of clean phases.

## Definitions and findings

Frozen adjacent outcome windows cover 100–5800 m. Native distance timestamps
use the existing first-distinct-update interpolation, with fuel/speed sampled
on their own grids. No boundary is moved after observing results. T3 includes
T4/T5 and T15 includes T16; T17 carryover after the line remains unmeasured.

Median LICO fuel use is 2.744903 L over that interval and lap time is 107.74 s.
Against the five prior push medians, the descriptive difference is 0.259686 L
saved and +0.56 s at whole-lap scale. Against first-attempt push 1/4, it is
0.241575 L and +0.66 s. This is baseline sensitivity, not a confidence interval
or a fuel-mass-adjusted causal estimate. Do not sum median zone deltas and call
that the median lap delta; only per-lap window outcomes telescope exactly.

Provisional zone interpretation, all seven LICO laps retained:

- T7: higher 95 m dose, 0.054505 L / +0.035001 s median against prior push.
- T10: higher 80 m dose, 0.043361 L / +0.048661 s; promising, not zero-cost proof.
- T13: 30→60 m group median contrast adds 0.010249 L and +0.231525 s; weak marginal
  tradeoff in this sample, not a fitted causal slope or instruction to disable it.
- T1: higher-dose extra fuel benefit is small in pooled medians; sensitivity
  reference push 4 has a T1 impact signal and must stay flagged.
- T3–T5: larger time cost; retry 10 starts this window at 54.262% driver pedal.
  Retry 9 starts with filtered throttle 0% but driver pedal 100%. Do not conflate
  possible engine/transmission cuts with intentional lift, or T1 carryover with
  the isolated T3 action.
- T15–T16: higher dose saves more fuel, but pooled time cost shifts from +0.0075
  to +0.1501 s with the push reference. Ranking is not stable enough to freeze.
- T17: higher dose saves more fuel; ending at 5800 m can omit later recovery.

All complete laps pass core technical channel checks. This is distinct from
driver cleanliness. No impact events occur inside the complete LICO windows;
the boolean native impact channel cannot quantify incident severity and an
inherited true value at retry start is not a new impact.

The 49 detected full-release onsets have median error +4.511 m versus planned
lift, range −1.408 to +17.575 m. Threshold: pedal <=5% sustained 0.10 s. This is
not physical audio latency. Brake-shift columns use the frozen prior push
reference and a sustained >=5% brake detector; retain as execution diagnostics.

## Leakage and next gate

All pooled summaries are exploratory. Only original first-attempt laps 5/6
are used for the reported held-out pre-run prediction check: MAE 0.006685 L
and 0.063418 s across 14 zone passages, with unresolved driver-quality caveats.
No refit, preprocessing fit, resplit, online adaptation or model promotion occurred.
Keep calibration laps 2/3 and test laps 5/6 as originally declared; retry is
repeat execution/familiarisation, not a cleaner replacement test chosen afterward.

Next: phase/carryover qualification on existing traces, then four-circuit
low-data benchmarks with training-only transforms. Keep planned-lift acceleration
from push as pre-action context; actual post-lift deceleration is not a substitute.
No general new simulator run is justified solely by the missing fourth retry lap.

## Reproduction and checks

`scripts/analyze_sebring_lico_sessions.py` builds a new output directory and
refuses overwrite. Use `--output` with a fresh directory for reproduction.
`docs/sebring_combined_score_check.sql` independently reproduces all 49 prior-push
contrasts to <1e-10. The companion notebook checks saved hashes, counts, exact
per-lap telescoping, aggregate sensitivity and the held-out calculation.
Its Python cells executed top-to-bottom; Jupyter kernel execution was not tested
because nbformat/nbclient/ipykernel are absent. No dependencies were installed.

Six targeted pytest checks pass (new analysis plus fixed-distance regression).
Ruff passes. Frozen cue packs are unchanged. No simulator/audio retest is required
for this analysis-only change. No Git commit or push was performed.

Report surface: Data Analytics MCP report, canonical input `artifact.json` in
the final output directory. Executive structure: summary, scope, zone tradeoffs,
reference sensitivity, execution, next steps, open questions, caveats. One scatter
of 49 zone passages shows the fuel/time relationship, grouped by session with
blue/gold and a legend; exact lookup uses the 14-row dose table. No trend chart:
too few comparable laps, changing fuel mass and differing dose schedules.
Renderer validation and rendering succeeded; host-level visual inspection was
not available through the current non-voice app tools.
