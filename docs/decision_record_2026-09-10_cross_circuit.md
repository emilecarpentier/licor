# LICOR decision record — Paul Ricard verdict and cross-circuit direction

Date: 2026-09-10

## Decision

LICOR should now enter a **low-data cross-circuit transfer phase**, but it is
not ready to claim a learned blind multi-circuit model. The immediate software
work is to build a leakage-safe pooled modeling table and grouped evaluation
harness from the existing Spa and Paul Ricard evidence. The next simulator
budget should prioritize two additional LMP2 circuits instead of broad extra
collection at Spa or Paul Ricard.

The intended product target is not literally zero local data. It is
**zero-LICO-shot or few-LICO-shot transfer**: use a small local push baseline to
describe a new circuit, then require substantially fewer local LICO laps than a
from-scratch curve fit.

## Evidence inventory and independence

All current derived artifacts were reconciled to their underlying sessions so
that copies and rebuilds are not counted as new observations.

- Spa contains 65 processed run/lap pairs and 520 zone-pass rows across 13
  non-pit run identifiers. The fitted curve table uses 425 observations from 54
  run/lap pairs and ten calibration runs; recommendation-execution sessions are
  operational/held-out evidence, not independent new circuit tasks.
- Paul Ricard historical modeling contains 25 eligible run/lap pairs, 150
  candidate passes and 143 curve observations from four raw runs. The
  `paul_ricard_transfer_v1`, `paul_ricard_pilot_2026_09` and current prediction
  validation trees are different generations derived from those same four
  runs, not additional sample size.
- Session `paul_pilot_20260909_232207` is held out from fitting. It retains ten
  authoritative zone observations after the recorded exclusions and one clean
  whole LICO lap. All 12 cues were heard.
- The earlier six-zone live session `paul_pilot_20260909_220534` corroborates
  cue operation and some zone directions, but its performance CSV is not used
  as quantitative training or test evidence because there is no native DuckDB
  and the dirty laps cannot be identified.
- The effective transfer sample is only two circuits. All native data describe
  the same LMP2_ELMS Oreca 07 #397 and driver. Setup is not consistently
  available. Driver, setup and vehicle generalization therefore remain
  untested.

The hundreds of zone rows are useful for local response fitting, but they do
not turn two circuits into hundreds of independent transfer tasks. A random
row split would be pseudoreplication.

## Paul Ricard verdict by zone

The current historical model stays frozen. The table combines its full
four-run support with the native held-out confirmation; the two generations are
reported separately rather than pooled into a refit.

| Zone | Historical curve support | Exact selected-bin support | Held-out N | Fuel observed vs predicted | Time observed vs predicted | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| T01–T02 | 25 points / 13 LICO | 5 | 1 | 0.0517 vs 0.0141 L | ~0.000 vs 0.000 s | Promising; positive fuel signal, but only one authoritative execution and a noisy/non-monotone time curve. |
| T03 | 24 / 11 | 6 | 2 | 0.0168 vs 0.0146 L | 0.090 vs 0.0556 s | Robust for the tested profile; fuel is close and both held-out repetitions agree. Time is modestly underestimated. |
| T08–T09 | 25 / 14 | 3 | 2 | 0.0563 vs 0.0414 L | 0.125 vs 0.0533 s | Promising; strongest repeatable fuel gain, but sparse exact-bin support and time cost above prediction. |
| T11 | 20 / 14 | 6 | 2 | 0.0197 vs 0.0187 L | 0.040 vs 0.210 s | Robust for fuel/profile execution. The conservative time prediction overstates the observed cost, but the full time curve is not yet robust. |
| T12 | 24 / 13 | 9 | 2 | 0.0191 vs 0.0221 L | 0.185 vs 0.0333 s | Unstable trade-off; fuel is directionally sound, but time cost is about 5.6 times the prediction. Do not promote unchanged into time-optimal planning. |
| T14 | 25 / 10 | 5 | 1 | 0.0117 vs 0.0177 L | -0.020 vs 0.020 s | Insufficient; positive but small fuel evidence and only one admissible held-out observation. |

At whole-lap level, the one fully clean LICO lap saved `0.1823 L` for `0.6800
s`, versus `0.12855 L` and `0.37222 s` predicted. The fuel-saving direction is
confirmed, but the aggregate time cost was underestimated. The main local
modeling issue is now the fuel/time trade-off, especially T12 and then T08–T09,
not cue delivery or the existence of fuel savings.

## Leakage-safe modeling work that can start now

Before collecting another lap, build an inspectable table at
`run / lap / zone` grain from the reviewed zone-pass rows and sidecar context.
Pre-register the targets, allowed pre-action features and split groups.

Compare three deliberately simple baselines at equal local data budgets:

1. the current local piecewise curve;
2. the current transferable-archetype heuristic;
3. a low-dimensional regularized or monotone pooled model.

Use whole-circuit outer splits and whole-run inner splits. With only Spa and
Paul Ricard, Spa-to-Paul and Paul-to-Spa results are stress tests, not a
generalization estimate and not a basis for choosing a complex model.

The split must happen before baseline construction. Each fold must fit its own
baseline, imputation, scaling and feature selection. Circuit-prefixed
`zone_id` is not a model feature. Post-action quantities such as observed brake,
apex or exit deltas are diagnostic outcomes unless a separate pre-action model
predicts them.

The primary normalized action is now the planned lift lead to the fold-fitted
push brake onset divided by the fold-fitted push brake-onset-to-minimum-speed
distance. Keep planned and executed leads, coast length and absolute distances
separate. LICO-window length is capture/QC metadata only; it is not an action
normalizer. Useful context candidates include fold-local push approach/brake
speed, braking severity, straight/complexity proxies and push fuel/time
references. Predict fuel saved and time lost separately, with uncertainty and
unsupported-context flags.

Acceleration at the proposed lift is now a required context rather than an
optional future feature. The relevant counterfactual is the acceleration the
car would still have under full push at the proposed lift point. Clean push
traces therefore provide an approach-acceleration profile at physical lead
ratios `0`, `0.25`, `0.5`, `1.0` and `1.5`; the fold view interpolates that profile at the
planned/executed action ratio and exposes an `action × acceleration`
interaction. Same-pass acceleration after a LICO begins is never used to
predict that LICO outcome.

The current LMU files also expose an axis-label trap: `G Force Lat`, with sign
reversed, matches longitudinal speed acceleration in all 16 checked DuckDBs;
`G Force Long` does not. The builder validates the mapped sensor against a
speed-derived slope and falls back to the latter if correlation is below
`0.80`.

Implementation status on 2026-09-10: the pooled Spa-Paul observation table,
feature-availability registry, eight explicit grouped folds, fold-local push
references and derived fold views are reproducible from native telemetry with
`scripts/build_cross_circuit_ml_table.py`. The raw table contains no globally
fitted baseline deltas, and `paul_pilot_20260909_232207` is locked outside the
builder. This completes the table/split construction gate, not the model
comparison gate.

The first deliberately weak benchmark is also recorded. A zero-intercept,
non-negative action-only response model uses the executed physical action ratio
for retrospective testing; it is not yet a frozen planned-action predictor.
After rejecting truncated events and push denominators with a coefficient of
variation above `0.15`, Spa→Paul reduces fuel MAE from `0.02704 L` to
`0.00637 L` and time MAE from `0.13125 s` to `0.11231 s`. Paul→Spa reduces
fuel MAE from `0.03969 L` to `0.00752 L` and time MAE from `0.10142 s` to
`0.06969 s`.
These are row-level diagnostic errors with run-macro counterparts in the
artifact. One Paul leave-run-out fold is worse than the zero predictor for time,
so the result supports the transfer hypothesis much more clearly for fuel than
for time. It does not yet compare the local curve or archetype heuristic and
does not justify model promotion. Forty-two fold-zone references remain ready;
the physical ratio currently covers five Spa zones and three Paul zones.
Improving or explicitly declining the denominator for complex/truncated zones
is therefore part of the remaining model-comparison work. The first
acceleration-conditioned monotone benchmark is now emitted beside the
action-only benchmark; comparisons must use the paired acceleration-available
subset because coverage differs.

On that paired subset, the new term is not yet a performance improvement.
Spa→Paul is unchanged for fuel (`0.00641 L` MAE) and time (`0.11255 s`), with
both interaction slopes fitted to zero. Paul→Spa is slightly worse than the
paired action-only fit for fuel (`0.00777` versus `0.00751 L`) and time
(`0.07510` versus `0.07280 s`), although its time interaction is positive.
This does not invalidate the physical variable; it shows that two circuits and
a two-term linear response do not identify its transferable effect reliably.
Keep it in the contract and test it prospectively on circuits C and D without
claiming an accuracy gain now.

## Circuit selection gate

Circuit diversity is not sufficient if driver inconsistency overwhelms the
zone signal. Before freezing circuits C and D, score every candidate from 1 to
5 on:

1. clean-lap repeatability for the current driver (double weight);
2. repeatability of brake/lift points in candidate zones (double weight);
3. diversity of realistic LICO approaches relative to Spa and Paul Ricard;
4. number of usable heavy, medium and plateau-speed braking approaches;
5. scored laps obtainable per hour.

A circuit with driver repeatability below 3 is rejected regardless of physical
diversity. The intended pair is one high-diversity circuit and one
high-repeatability circuit; they must not both be selected merely because their
layouts are interesting. Bahrain is selected as circuit C: the driver reports
high repeatability, and its long straights followed by heavy braking into slow
corners provide clear LICO treatments. Imola, COTA, Sebring and Interlagos
remain candidates for circuit D. Paul Ricard is explicitly a weak-repeatability
reference, not a template for that selection.

The circuit-C push protocol is frozen as
`bahrain_lmp2_circuit_c_v1`. Its first session collects five clean push laps
before any Bahrain LICO response is available; a push-only launcher preserves
the native telemetry link and driver notes without starting the live cue path.

## Minimal new-circuit protocol

Choose two additional circuits with meaningfully different braking/geometry
profiles while keeping the same LMP2 vehicle, driver, fuel start, tire-wear
setting and controlled weather. Record setup identity even when setup is not an
optimization variable.

For each circuit:

1. collect five clean push laps for local baselines and pre-action descriptors;
2. freeze the zero-LICO-shot predictions before seeing local LICO outcomes;
3. collect one seven-lap `P / L / L / P / L / L / P` block with varied,
   pre-generated LICO actions and a native DuckDB;
4. record lap/zone errors immediately and evaluate the frozen predictions
   before adding the circuit to training.

This is 12 scored laps per circuit and about 24 new scored laps for circuits C
and D. It is a pragmatic first challenge budget, not a guarantee of statistical
power. A separate second run is required later on a destination circuit to
measure one-, two- and four-LICO-lap adaptation without training and testing on
different laps from the same session.

At four total circuits, run four-fold leave-one-circuit-out evaluation and
learning curves at zero, one, two and four local LICO laps. Promotion requires
the transferred model to reduce held-out error or decision regret versus the
local-only and heuristic baselines at the same budget, without increasing
unsupported/unsafe zone proposals. Absolute tolerances must be fixed before the
new outcomes are inspected.

## Consequences

- Do not broadly collect more Spa or Paul Ricard laps now. A targeted Paul run
  may later resolve T14/T01 support or T12/T08 time-cost uncertainty, but it
  does not unlock cross-circuit learning.
- Do not refit from `paul_pilot_20260909_232207`; it remains the prospective
  test of the frozen Paul model.
- Do not start with deep meta-learning, reinforcement learning or a high-capacity
  multitask GP. First establish the pooled-table contract, grouped baselines and
  uncertainty behavior.
- Generalization to drivers and setups comes after circuit transfer. It will
  require crossed data: a second driver on at least two existing circuits and
  setup variation that is not confounded with a new driver or circuit.

## Next executable sequence

1. [Complete] Build and validate the pooled ML table and leakage-safe split
   manifest.
2. [Partial] Run leave-one-run-out checks within each circuit and the two
   cross-circuit stress tests; action-only and acceleration-conditioned
   baselines are complete, while the local-curve and archetype comparisons
   remain.
3. Freeze the circuit-C predictions and collection pack.
4. Collect circuit C, evaluate it, then repeat unchanged on circuit D.
5. Run the first meaningful leave-one-circuit-out benchmark and decide whether
   hierarchical partial pooling is justified.
