# LICOR Roadmap

Use this roadmap as the main handoff document for future Codex sessions. Start
new work from the active priorities below, keep edits small, and update this
file whenever the strategy changes meaningfully.

## Active Priorities — 2026-10-01

Driver decision: **OCR is on hold, not discarded**. Preserve its scripts,
annotations and generated evidence for an optional later return. Use verified
native telemetry/session/scoring inputs for the active work; no screen capture
dependency and no Streamlit UI changes. Here the intended input is understood
as the telemetry stream, not a claim that Streamlit exposes extra game fields.

Driver clarification: reliable continual learning during ordinary driving is
the central capability. Cross-circuit transfer is the low-data starting point,
not the end product. A poor qualifying observation must not permanently exclude
a zone; unknown effectiveness is not observed ineffectiveness. Intentional live
exploration has not been authorized. See the staged learning loop in
`fuel_first_race_contract_2026-09-12.md`.

Refocused next milestone: an offline **short push qualification -> initial
cross-circuit plan -> sequential local learning** acceptance test. The simple transfer baseline and
response candidates already exist; do not restart those comparisons or require
another general collection campaign. Hold the destination circuit out of fitting,
use only its first usable push references (minimum three for current descriptors),
and exclude all destination LICO outcomes from the initial plan. Audit readiness,
available zones, physical action support, acceleration at the proposed lift,
predicted fuel/time and time-to-plan. Missing references must produce limited
coverage or abstention, not invented qualifying laps or extrapolated large lifts.
Also audit zone definitions, recovery windows and dose caps for destination
leakage: rebuild them from the push-only information available at startup, or
label the test explicitly as using pre-reviewed geometry. Excluding the circuit
from coefficient fitting alone does not establish autonomous unseen-track startup.

As the core acceptance test, evaluate chronological, bounded local updates only from prior qualified
executions, against the frozen transfer baseline. Score the fuel target and
decision quality, not only prediction MAE. Preserve the distinction between
observed whole plans and unexecuted mixed-zone counterfactuals. Zone-window fuel
savings are not automatically whole-lap savings; the budget bridge needs its own
validation. The first bounded predict-before-update response replay is now
implemented in `analysis/continual_learning.py` and
`scripts/replay_continual_learning.py`; it does not yet generate or execute a
revised plan. It preserves all 49 Sebring observations but learns only from the
12 existing `strict_retry` passages. Geometry and quality masks are retrospective,
and initial references are five dedicated push laps, not a short-qualification
startup test. See `docs/continual_learning_replay_2026-10-01.md` for the exact
scope, checks and development results. The end-to-end milestone remains open.
Freeze the candidate and protocol before a fresh circuit validation (Imola remains
an option; no circuit choice or simulator run is required now).

The completed race test supports native fuel accounting, session segmentation,
leader/player finish conventions and horizon diagnostics. It did **not** validate
zero-shot LICO on a new circuit or automatically add clean ML training rows.
The existing budget/scenario modules remain reusable supporting components;
native-only horizon/scenario integration is a separate gate, not a reason to
block cross-circuit model work on recovering the HUD.

### Completed evidence retained

Offline HUD OCR feasibility audit completed on the existing OBS video. Windows
OCR needs no new dependency. Frozen V2 reads exact race totals on9/14 visible
same-video evaluation frames and fuel autonomy on13/14; both on9/14, with no
wrong numeric candidates observed. Two HUD-absent controls abstain. Approximate
versus final status remains unknown on12/14 visible frames. This small correlated
sample is not a live reliability certificate. See `scripts/read_hud_frames.ps1`,
`scripts/audit_hud_ocr.py`, `notebooks/hud_ocr_feasibility.ipynb`, and the OCR
section of `docs/native_race_capture_protocol.md`. No live ingestion or ML change.

Native race capture completed and reconciled: Bahrain, six race laps, own finish
confirmed separately from leader finish (~19.69s earlier) and clock zero
(~64.67s earlier). See `notebooks/bahrain_native_race_audit.ipynb`,
`scripts/audit_bahrain_native_race.py`, and `docs/evidence/bahrain_race_hud_2026-10-01.json`.
Driver confirms accidents/spins on final two race laps; diagnostics only,
no training/refit. Offline race-context segmentation and a causal, constant-past-
pace boundary forecast are now implemented in `src/licor/analysis/race_context.py`
and `scripts/replay_native_race_context.py`. Bahrain replay distinguishes clock
expiry, leader finish, own finish and garage reset. It predicts 4/3/2/1 laps
remaining at completed laps2/3/4/5, but this is a diagnostic point forecast,
not a validated upper horizon or native HUD reconstruction.
HUD ~6.5 can fall to ~5.9 after clock zero before a six-lap finish: do not apply
an unconditional floor/ceil conversion. No live adaptive authority.

Exact HUD availability checked against the actual capture, DuckDB inventory and
installed SDK: 0/3899 `hud_total_laps` values present. `mEstimatedLapTime` is lap
duration for gap calculations; `mMaxLaps` is a configured cap (2147483647 here),
neither is the fractional total. No verified alternative WebUI route yet; do not
claim impossibility across all LMU interfaces.

Driver clarification supersedes automatically imposing a long horizon:
`analysis/race_scenarios.py` now compares two explicit adjacent player-lap fuel
budgets independently, preserving reserve and consumption allowance. No global
plan is selected without the driver's scenario choice. Target0.1L is a possible
late-race driver risk decision, not a default reserve or automatic15-lap switch.
Ignoring cues must not be learned as if the recommended action was executed.
Long races remain stint-feasible: no future refill credit before reaching it.

The native context replay now exports `leader_switch` at eligible boundaries:
adjacent leader totals around the nearest timer crossing and required mean pace
change over subsequent full laps, holding the next crossing fixed. Not HUD,
not probability, and not an automatic leader-to-player lap mapping. Original
`upper_remaining_laps` remains null until own finish; original conservative
controller remains abstaining. The separate fixed-branch comparator does not
claim a calibrated bound. No live adaptive authority or model refit.

OCR gate deferred by the driver: no further reader tuning or live capture work
without revisiting this choice. The local REST schema and official broadcast
WebSocket have now been inspected with LMU running; neither inspected payload
provided the two exact HUD estimates. This does not prove absence from every
LMU interface. No new driving run is needed for the next offline work.

### Prior handoff — 2026-09-12

Current handoff: read-only native race logger and bounded PowerShell launcher
are ready for an in-game diagnostic session. Follow
`docs/native_race_capture_protocol.md` on a familiar circuit. This supersedes
the older "no simulator run required" and Sebring collection instructions below.
No new LICO collection, exact HUD ingestion or live adaptation is enabled.

Latest: native LMU HUD identified; boundary-only causal fuel replay implemented
and tested on explicit synthetic scenarios. See
`docs/fuel_budget_shadow_replay_2026-09-12.md`. Next is read-only synchronized
session/player/leader logging and HUD convention verification, then short-qual
startup validation. No inferred conversion of the HUD fractional total, no
calibrated race guarantee and no live adaptive authority.

Fuel-first clarification: short qualifying on a new circuit -> initial prior
plan -> remaining-fuel/remaining-distance budget -> causal adaptation. See
`docs/fuel_first_race_contract_2026-09-12.md`. Fuel sufficiency is a constraint,
not a freely traded objective. A pure boundary-only budget calculator now
exists; HUD ingestion, race-context adaptation and calibrated safety margins
are not yet live features. No additional simulator run is required immediately.

Completed this lot: harmonized four-circuit acceleration, four response-model
forms, and planned-action fuel-first decision audit. See
`docs/fuel_first_development_review_2026-09-12.md`. Next: conservative margins
and chronological budget/adaptation replay, then a frozen short-qualifying
validation on a fresh circuit. Current point predictions do not guarantee fuel
sufficiency and the best time-cost form is not promoted to production.

Current decision: Sebring phase qualification and the compact four-circuit
low-data benchmark are complete. See
`docs/four_circuit_low_data_review_2026-09-12.md`. Fuel transfer is encouraging;
time-cost prediction and prospective decision quality remain the main gates.
Next: offline conservative adaptation, harmonized push-acceleration features,
and decision-level evaluation before a frozen new validation. No immediate
additional simulator run or live-model promotion. The operational updates below
are retained as history, not outstanding collection instructions.

Latest operational update (2026-09-12): the first Sebring LICO attempt was
interrupted during its final push lap (T1 error), with imperfect LICO execution
reported. Preserve it for localized review. Next collection is the separate
four-lap frozen A/B/A/B retry described in
[the retry run sheet](sebring_abab_retry_run_sheet.md). No dose changes or refit;
this familiarisation/repeat session does not replace the original held-out
schedule and contains no same-session scored push control.

Subsequent update: retry completed three scored laps A/B/A. Combined native
analysis now covers four A and three B laps across both attempts; see
`docs/sebring_combined_analysis_2026-09-12.md`. Existing-trace phase and
carryover qualification and low-data four-circuit evaluation are now complete.
Initial unresolved errors remain flagged; the
retry does not replace the original held-out cohort.

The [September restart plan](restart_plan_2026-09.md) is the current execution
plan. It supersedes the historical sequencing below. Historical completion
marks describe implemented artifacts, not proof of predictive performance.

1. Reconcile Paul Ricard zone boundaries and rebuild the pipeline from raw
   telemetry with dataset metadata and artifact provenance.
2. Prepare a frozen six-zone prediction-validation pack and a 5–7 clean-lap
   collection protocol, separate from race-strategy target optimization.
3. Preserve the finalized five-lap confirmation as held-out validation evidence
   rather than refitting it; the driver heard all 12 cues.
4. [Table/splits complete] Run the simple leakage-safe baselines on the pooled
   ML table. The action-only and first acceleration-conditioned baselines now
   exist; compare only on paired coverage. Treat the two Spa↔Paul folds as
   diagnostic stress tests only.
5. Collect two additional same-LMP2 circuits with a short frozen protocol, then
   run meaningful leave-one-circuit-out low-data benchmarks before considering
   a hierarchical model or adaptive live authority.

Circuit selection now has a driver-repeatability gate: clean-lap and brake/lift
repeatability are double-weighted against physical zone diversity. Bahrain is
selected as circuit C for its reported driver repeatability and clear
long-straight/heavy-braking LICO opportunities. On 2026-09-12 the driver selected
Sebring as circuit D for expected repeatability. Imola is an optional later test;
COTA is deferred because consistency, particularly in sector 3, is a concern.
The ready push-only launcher is documented in `docs/circuit_d_push_protocol.md`.

Sebring push run `sebring_push_20260912_114122` is now recorded and reviewed:
native laps 8–12 pass basic intake, and the driver reports no notable errors.
Use `config/datasets/sebring_lmp2_circuit_d_reviewed_2026-09-12.json`; the original
empty sidecar stays frozen with the collection pack. The seven-zone two-dose
pack is prepared: next is the simulator P/A/B/P/B/A/P block, not more push
collection. See `docs/sebring_lico_validation_run_sheet.md` for the launcher.
See `docs/sebring_push_intake_2026-09-12.md` for evidence and pending zone gates.

The Bahrain circuit-C push protocol is frozen in
`config/collection_protocols/bahrain_lmp2_circuit_c_v1.json`. Its first native
run, `bahrain_push_20260911_212732`, contains outlap 15 and five complete push
laps 16–20. Laps 18–20 have localized driver-reviewed exit errors: T15 exit on
18, T4 mid/exit on 19, and T15 apex/exit on 20. Their approach and brake-onset
signals remain usable, while contaminated local outcomes must be masked. The
seven-lap LICO validation is now complete. Its corrected native score is
`0.1719 L` over the common 100–5350 m interval for `0.400 s` on official lap
times. The first local analysis had a repeated-distance interpolation bug;
`analysis_v2_final` supersedes it, with the pre-run predictions preserved.
The three-circuit ML v2 table uses native timestamp interpolation for all
circuits. See `docs/bahrain_transfer_review_2026-09-11.md` for the score,
upstream capture audit, retrospective comparisons and remaining data gates.

Confirmed: T03 and T08-T09 starts have moved 75 m upstream, tire wear is disabled
for the pilot, and simulator time is the collection constraint. The first
two-zone run exposed an objective mismatch: the `0.05 L/lap` minimum-time
strategy plan was not an adequate validation roster. Paul artifacts have now
been rebuilt from the four raw recordings into a distinct six-zone
prediction-validation pack. The live runtime also projects between LMU's coarse
scoring-distance updates. Synthetic and recorded-telemetry replay checks pass.
The first seven-lap six-zone session, `paul_pilot_20260909_220534`, is now
recorded with push laps 13/16/19 and LICO laps 14/15/17/18. All 24 expected
audible cues were in tolerance; the maximum absolute trigger error was
`1.331 m`. Projection-aware bracketing-push analysis provisionally measures
`0.1584 L` saved and `0.3191 s` lost per LICO lap, versus the frozen plan's
`0.12855 L` and `0.37222 s`. The driver confirmed hearing all 24 cues, so the
operational cue/audio verdict passes. Telemetry recording was not active and
some unclean laps cannot now be identified; the fuel/time result is unscorable
and no refit is authorized. The next simulator step is a five-lap P/L/P/L/P
confirmation run with a native DuckDB and immediate lap-quality notes. The 24 beep-correlated
sampling gaps of `0.100` to `0.129 s` remain a limitation of this recording;
the beep has been moved to background emission for future runs. The two-zone
pack/session remain frozen as separate prospective history. See the
[pilot run sheet](paul_ricard_static_pilot_run_sheet.md) for the exact post-run
command and result contract.

The five-lap confirmation `paul_pilot_20260909_232207` is complete on absolute
laps 22–26 with its native DuckDB. Lap23 is excluded from whole-lap scoring
after driver-reported T1 and probable T13 errors; T01–T02/23 and T14/23 are
excluded at zone level while its other zones remain available. The one clean
LICO lap saved `0.1823 L` for `0.6800 s`, compared with `0.12855 L` and
`0.37222 s` predicted. Ten zone observations remain included. Treat this as
authoritative but low-sample held-out evidence: no refit is authorized. All 12
cues were heard. Reconciliation against the full four-run Paul history rates
T03 and T11 robust for the tested profile, T01–T02 and T08–T09 promising, T12
unstable on time cost, and T14 insufficient. The next data budget therefore
targets circuit diversity rather than broad Paul repetition; see the
[2026-09-10 decision record](decision_record_2026-09-10_cross_circuit.md).

The initial generalization target is circuits within the same LMP2 vehicle.
Drivers and setups are later calibration dimensions; cross-vehicle/category
transfer needs additional vehicle-specific evidence.

## Historical Strategic Reset — May 2026

The following phases preserve the development history. Use the active
priorities above for ordering new work.

LICOR is no longer aiming for a simple sequence of:

```text
static offline optimizer -> live beep -> more data
```

The project has now reached a better architectural understanding:

```text
credible offline telemetry pipeline
-> robust optimizer
-> lap-by-lap adaptive replanning simulator
-> live cue execution
-> cross-circuit transfer with small calibration budgets
```

This shift matters because the final product cannot assume a race unfolds as the
initial plan expected. The system must eventually react to what the driver
actually does lap after lap: full-push openings, traffic, tire state changes,
under-executed lifts, and changing fuel targets.

Two rules now guide the project:

1. keep the current Spa v2 production-style pipeline stable;
2. test modeling and optimizer changes in isolated experimental files first.

The current experimental branch lives under:

```text
src/licor/analysis/experimental_*
src/licor/reports/experimental_*
scripts/*_experimental.py
data/processed/experimental/spa_dynamics_v1/
```

## Current Project State

As of 2026-05-28, LICOR has:

- a reproducible Spa telemetry pipeline from ingestion through static planning;
- reviewed Spa candidate zones and validated zone boundaries for the current
  optimization path;
- a first strategy layer tied to observed pit telemetry and a 48-lap ELMS Spa
  reference;
- a live-cue export and replay scaffold;
- a validated static LMU live cue loop with telemetry-linked cue logs;
- a frozen `selected_zones_latency_v2` speed-aware live baseline that now
  matches real pilot lift timing closely;
- an isolated experimental dynamics branch that explains many suspicious
  optimizer shapes better than the original one-dimensional view;
- an experimental reclassification branch where `T01`, `T08`, and `T12-T13`
  are promoted to experimental `model_ready`, `T14` is treated as
  `micro_lico_only`, and the static fuel target becomes reachable without
  depending on `T14`.

At that time, adaptive replanning was treated as the next bottleneck. The
September audit instead prioritizes reproducibility and held-out static
fuel/time validation before further adaptive development.

## Phase 0: Project Foundation

Status: complete.

- [x] Document the LMU DuckDB telemetry format.
- [x] Add the LMU telemetry reference config to the repo.
- [x] Implement read-only DuckDB ingestion.
- [x] Add a loader for the LMU telemetry reference config.
- [x] Validate observed DuckDB channels/events against the reference config.
- [x] Reconstruct timestamps for fixed-frequency channels.
- [x] Add tests with synthetic DuckDB files.
- [x] Define the normalized LICOR telemetry schema.

## Phase 1: First Controlled Spa Dataset

Status: complete.

- [x] Keep raw telemetry files outside Git.
- [x] Add a dataset log for controlled runs.
- [x] Convert `docs/dataset_log.md` into a machine-readable label file.
- [x] Load multiple LMU telemetry files from a local folder.
- [x] Extract lap intervals and filter out-laps/warm-up laps.
- [x] Produce a lap summary table with fuel usage and validation metrics.
- [x] Add tests for lap summary and valid-lap filtering.

## Phase 2: Braking And LICO Detection

Status: complete for the current optimization path.

- [x] Detect braking zones from `Brake Pos`.
- [x] Merge nearby braking segments into meaningful corners/zones.
- [x] Keep distinct Bus Stop-style brake presses as separate detected zones.
- [x] Define driver-reviewed Spa LICO candidate zones around approach, LICO,
  braking, corner/complex, and exit stabilization phases.
- [x] Detect throttle lift before braking zones.
- [x] Associate candidate LICO zones with lap distance and braking point.
- [x] Add tests for brake segment detection and segment merging.
- [x] Add an editable track-zone config schema and draft Spa zone file.
- [x] Add tests for track-zone loading and validation.
- [x] Add proposal logic for brake references and LICO window starts.
- [x] Build a zone-boundary visualization workflow for driver validation.
- [x] Add a Spa top-down map workflow from a local OpenStreetMap-derived trace.
- [x] Driver-review top-down alignment, zone starts, brake references, and
  validation endings for LICO candidate zones.
- [ ] Decide whether to add complete validation-only boundaries for Spa T19.

Notes:

- Spa `T19` remains an intentional non-candidate in the current optimization
  pipeline.
- The unresolved `T19` boundary question is low priority relative to the
  modeling and optimizer work below.

## Phase 3: First Zone Cost/Benefit Pipeline

Status: complete for the first-generation static model.

- [x] Compare push and LICO behavior by track zone.
- [x] Estimate fuel saved and local time lost by zone.
- [x] Convert `none`, `low`, `medium`, and `high` collection labels into
  continuous telemetry measurements such as lift distance and lift duration.
- [x] Fit initial smooth zone-level cost/benefit curves.
- [x] Rank zones by fuel saved per second lost.
- [x] Let the driver review and correct zone interpretation.
- [x] Treat full-lap deltas as sanity checks, not objective functions.
- [x] Add a first `zone_pass` extraction table from driver-reviewed track
  zones.
- [x] Add synthetic tests for push, LICO, skipped zones, and incomplete zone
  coverage.
- [x] Add a first zone-level cost summary from `zone_pass` observations.
- [x] Add descriptive zone curve points and distance-binned curve tables before
  fitting a formal continuous model.
- [x] Add driver review annotations for lap-zone exclusions and zone signal
  tags.
- [x] Add targeted throttle/brake/speed zone telemetry reports for curve
  anomalies.
- [x] Add zone-start zero-throttle diagnostics and apply the T08
  driver-reviewed start adjustment.
- [x] Make zone-pass LICO start robust to isolated throttle artifacts before the
  true zero-input coast phase.
- [x] Add first piecewise-linear zone models from binned curve observations.
- [x] Add a full-lap sanity table comparing global lap deltas with summed
  observed zone deltas.

## Phase 4: Pit Stops And Static Race Strategy

Status: complete for the first-generation static strategy layer.

- [x] Load dedicated pit stop telemetry files.
- [x] Detect pit entry, pit exit, speed limiter on/off, stationary time, and
  refill windows.
- [x] Estimate observed refill rate and pit lane commitment time.
- [x] Compare telemetry-derived refill rate with configurable LMU/rules values.
- [x] Compare full-push stop count versus LICO-enabled stop count for a race
  length.
- [x] Compute the fuel saving target required to avoid an extra stop.
- [x] Add a first `pit_stop_observation` extraction table from dedicated pit
  stop telemetry.
- [x] Add synthetic tests for pit state intervals, limiter windows, stationary
  windows, refill windows, missing refill handling, and initial out-lap pit
  state filtering.
- [x] Add first race-strategy helpers for race lap count, stop count,
  fuel-saving targets, and full-push versus LICO scenario comparisons.
- [x] Generate first Spa strategy CSVs from observed full-lap fuel deltas and
  measured pit/refill telemetry.
- [x] Add a race-lap override for championship-observed distances such as the
  Spa ELMS split result of 48 laps.
- [x] Add a first conservative zone-level optimizer that uses only
  `model_ready` points and reports when the fuel target is unreachable.
- [x] Add editable driver strategy priors and a driver-prior optimizer mode for
  feasible-but-diagnostic LICO zones.
- [x] Generate Spa conservative and driver-prior zone-level plans for the
  48-lap one-stop fuel target.

## Phase 5: Reports, Metadata, And Execution Scaffolding

Status: mostly complete. This phase is no longer the main bottleneck.

- [x] Add marginal fuel/time efficiency diagnostics for each zone model.
- [x] Add sensitivity reports for optimizer plans, including best-ratio caps,
  stricter driver caps, diagnostic-zone exclusion, and fuel safety margins.
- [x] Define a Spa v2 data collection protocol with controlled-random LICO,
  targeted zone variation, and recommendation-execution runs.
- [x] Add Spa v2 data-readiness summaries for zone coverage and protocol
  coverage before refitting curves.
- [x] Persist current Spa zone-pass and Spa v2 readiness artifacts.
- [x] Add a Spa v2 run-metadata ingestion contract and validation layer so
  future non-labelled runs can link to collection protocols before telemetry
  processing.
- [x] Add a run/lap quality manifest v2 to gate future collection laps before
  zone readiness and curve updates.
- [x] Use four Spa v2 controlled-random runs as the first post-v1 coverage gate
  before deciding whether targeted-zone collection is still necessary.
- [x] Add an exportable LICO plan format suitable for live cues.
- [x] Add a replay-style execution schema for planned-versus-observed live cue
  validation.
- [x] Build a minimal live-cue trigger/logging prototype that consumes an
  exported plan and logs cue timing accuracy.
- [x] Add an injectable replay/audio wrapper around the tested live-cue runner.
- [x] Generate Plotly charts for speed, throttle, brake, fuel, and lap
  distance.
- [x] Generate zone-level comparison reports.
- [x] Validate the real audio adapter against LMU telemetry during a driving
  session.
- [x] Add a first Windows LMU shared-memory static cue runner plus a local
  preflight doctor/bench CLI.
- [ ] Build a simple Streamlit dashboard around the tested analysis functions
  after the adaptive recommendation loop is credible.
- [ ] Keep analysis logic out of the app layer.

Notes:

- Real audio validation is now intentionally blocked by the next phases.
- Streamlit remains deferred on purpose.

## Phase 6: Experimental Spa Dynamics Branch

Status: complete for the first experimental dynamics branch.

Goal: explain suspicious optimizer behavior by modeling the causal chain between
LICO distance, entry dynamics, corner adaptation, and local time cost.

- [x] Build an isolated experimental zone dynamics table with braking, apex,
  exit, brake-shape, stint, and tire-context features.
- [x] Compare direct 1D local-time models versus dynamics-aware models.
- [x] Generate a technical dynamics report plus a simplified driver-review
  report.
- [x] Add an experimental reclassification layer that preserves both the base
  and experimental zone status.
- [x] Promote `T01`, `T08`, and `T12-T13` to experimental `model_ready`.
- [x] Reclassify `T14` as `micro_lico_only` with an explicit distance cap.
- [x] Show that the static fuel target can be reached in the experimental branch
  without requiring `T14`.

Deliverable of this phase:

```text
A robust offline optimizer artifact that prefers credible, well-supported
recommendations over fragile mathematical edge optima.
```

## Phase 7: Robust Optimization

Status: complete for the first robust optimizer artifact.

Goal: replace fragile single-point selection with a support-aware optimizer.

- [x] Define optimizer-facing support metrics per zone point, such as local data
  density, distance to nearest observed point, residual variance, and
  disagreement between simple and dynamics-aware views.
- [x] Add robust scoring that penalizes edge-of-surface points and weak support.
- [x] Output heuristic recommended LICO ranges; statistical interval calibration
  remains unimplemented.
- [x] Compare static naive plans against robust plans on Spa.
- [x] Preserve rollback by keeping the robust optimizer experimental until it is
  clearly better.

Success criteria:

- extreme points like `T12-T13 = 150 m` lose attractiveness naturally when
  support is weak;
- the optimizer still reaches the fuel target without collapsing into overly
  conservative behavior;
- the output is more interpretable for a human driver than a single brittle
  optimum.

Notes:

- The robust artifact now includes `selected_zones` and `all_eligible_zones`
  range-aware variants.
- Stable-pipeline migration is still deferred; experimental adoption remains a
  separate decision after more adaptive validation.

## Phase 8: Adaptive Lap-By-Lap Replanning Simulator

Status: experimental implementation exists; further development is deferred
until the static predictive validation gates in the restart plan are met.

Goal: simulate a race that diverges from the initial plan and update the next
lap's LICO demand accordingly.

- [x] Define a first race-state representation with remaining laps, remaining
  fuel target, recent execution quality, recent fuel delta, and scenario-event
  context.
- [x] Build a first lap-by-lap simulator that consumes an experimental plan plus
  simulated execution history.
- [x] Reuse the replay/live `planned vs executed` schema in an offline observed
  execution mode, so replanning can be audited against real run history before
  a live telemetry loop is introduced.
- [x] Add a first lap-level race-state context from existing telemetry, with
  fuel-load bands, stint phase, and coarse tire-regime labels.
- [x] Prototype a first bounded `fuel_load_band` conditioning layer, then park
  it as audit-only until stronger evidence exists.
- [x] Export an observed context-effects summary by fuel-load band and thermal
  regime so those priors can be checked against replayed execution residuals.
- [x] Add a first execution-calibration layer so adaptive replanning can react
  to recent `planned vs executed` fuel/time outcomes from the driver.
- [x] Refine execution calibration with recent zone-specific memory so adaptive
  replanning can distinguish between globally weak execution and a specific
  zone that the driver is consistently missing or over-performing.
- [x] Export a validation-oriented next-lap handoff preview so the adaptive
  controller can be reviewed in a live-cue-shaped table before true live
  validation.
- [x] Convert adaptive next-lap handoffs back into replay-ready `live_cue_plan`
  rows and validate them against recorded next-lap telemetry.
- [x] Recompute the next-lap target after each lap.
- [ ] Support scenarios such as:
  - [x] opening laps full push for position;
  - [x] under-executed or missed LICO cues;
  - [x] over-executed LICO;
  - [ ] hotter or cooler tire-state regimes;
  - [x] traffic or non-ideal laps.
- [x] Export per-lap recommended zone usage from the replanner.
- [x] Compare static-plan outcomes against adaptive outcomes on Spa.

Deliverable of this phase:

```text
An offline controller-like simulator that can say what the next lap should do
after the previous laps changed the fuel/time situation, first from scripted
disturbances, then from observed planned-vs-executed replay logs, while also
surfacing first-order race-state context such as fuel load and tire regime.
```

Notes:

- Fuel-load context is currently exported and audited, but no longer has
  default decision authority in the replanner.
- Adaptive authority now comes first from recent `planned vs executed`
  calibration rather than from weak fuel/tire priors.
- The execution-calibration layer now has a v2 zone-memory path in the
  experimental branch, so future live validation can inspect both global and
  per-zone adaptation signals.
- The observed replanner now exports both a zone-calibration summary and a
  next-lap handoff preview to support a cleaner transition into live testing.
- The experimental branch now also emits a concrete replay-validation loop:
  adaptive next-lap handoffs become `live_cue_plan` rows, are replayed through
  the existing cue runner on the recorded next lap, and are summarized at both
  handoff and zone level.
- Replay handoffs now follow the actual next observed lap in sequence, not only
  `lap_number + 1`, so runs with excluded or missing laps stay connected.
- Tire regime is still exported and reviewed, but without tire-wear telemetry
  it remains an audit variable rather than a decision authority in the
  replanner.

## Phase 9: Adaptive Live Cue Validation

Status: in progress for the static live baseline and the first guarded
operator-preview adaptive follow-up; true adaptive between-lap live handoff
still pending.

Goal: validate the real execution loop only after the offline planner and
replanner are trustworthy enough to deserve track-time validation.

- [x] Freeze `selected_zones_latency_v2` as the current static-live baseline
  after telemetry-enabled validation.
- [x] Publish the first Spa pilot live-validation protocol and export frozen
  candidate plan CSVs for `range_aware_selected_zones` and
  `range_aware_all_eligible_zones`.
- [x] Add an operator-facing pack generator plus a replay/beep CLI so the
  first pilot session can start from frozen artifacts instead of ad hoc file
  handling.
- [x] Add a first static LMU live-session runner that consumes a frozen plan and
  writes cue event logs during real driving.
- [x] Feed adaptive next-lap plans, not only static plans, into the live cue
  replay layer.
- [x] Log planned versus executed lift points, misses, and late/early cues.
- [x] Connect replay validation and real-session validation to the same schema.
- [ ] Use execution logs as new evidence for later model updates.
- [x] Run adaptive between-lap recommendations in shadow mode during a real
  static baseline session before letting them change the next live lap.
- [x] Export the first guarded operator-preview adaptive follow-up plan from the
  validated static live baseline session.
- [x] Publish an operator-facing adaptive handoff preview playbook for the next
  live data-collection block.
- [ ] Promote the shadow adaptive controller into a true between-lap live
  handoff only after it stays stable and readable.

Notes:

- Live cue is now a validation layer for the adaptive system, not the center of
  the methodology.
- `selected_zones_latency_v2` is the frozen operator baseline.
- `all_eligible_latency_v2` remains a comparison-only variant until adaptive
  evidence proves it is worth carrying in live use.
- The branch now emits a dedicated shadow adaptive artifact set from the frozen
  baseline session, including static-versus-adaptive next-lap deltas and a
  replay check on the actual next observed lap.
- The first operator-facing protocol lives in
  `docs/spa_adaptive_live_validation_protocol.md`.
- The first guarded operator-preview follow-up playbook lives in
  `docs/spa_adaptive_handoff_preview_playbook.md`.
- Generated pilot packs live under
  `data/processed/experimental/spa_dynamics_v1/live_validation_packs/`.
- The project should avoid spending large data-collection effort on live testing
  before the adaptive offline logic behaves credibly.
- Session-level cue-latency adaptation remains a documented future live-polish
  idea, not the next project bottleneck. The current `selected_zones_latency_v2`
  speed-aware baseline is good enough to support the next transfer-oriented
  phase.
- Future latency calibration should learn only from reliable observed
  cue-to-lift timing, explicitly excluding missed-audio laps, obvious cue
  perception failures, and other operator-noise outliers.
- That future layer should adjust `cue_distance_m` only on top of the current
  speed-aware baseline. It should not rewrite `planned_lift_start_m`, zone
  selection, or the between-lap adaptive fuel/time recommendation.

## Phase 10: Cross-Circuit Transfer And Low-Data Adaptation

Status: three-circuit pooled table, grouped evaluations and corrected circuit-C
prospective score complete; circuit D selection pending driver repeatability.

Goal: move from Spa-specific methodology to a reusable cross-circuit system that
can bootstrap from very small circuit-specific samples.

- [ ] Use Spa as the first calibration and methodology dataset.
- [ ] Replace first piecewise curves with more robust continuous models only
  after the optimizer and replanner objectives are well specified.
- [ ] Model uncertainty so recommendations distinguish high-confidence zones
  from weakly supported or extrapolated ones.
- [ ] Learn reusable zone priors from Spa, such as relationships between
  approach speed, braking severity, straight length, corner type, LICO
  distance, fuel saved, local time lost, and adaptation sensitivity.
- [ ] Add automatic candidate-zone proposal for new circuits from mostly push
  laps, using braking events, approach geometry/proxies, and reusable priors.
- [ ] Support small calibration budgets on new circuits: mostly push laps plus
  a limited number of varied LICO laps, not a full manual rebuild.
- [ ] Let the online replanner adapt those priors quickly from the driver's real
  execution and race context.
- [ ] Keep a manual review fallback for zones whose telemetry shape is outside
  the Spa-learned distribution.
- [ ] Add lightweight statistical or Bayesian models only after the heuristic
  and experimental outputs are credible.

### Phase 10a: Transfer Pilot Design

Status: in progress.

Goal: define the smallest believable workflow for a first non-Spa bootstrap
attempt before implementing new-circuit code paths.

- [x] Decide that future live reaction-time adaptation should stay deferred and
  documented, rather than delaying the transfer-oriented work.
- [x] Define a transferable zone-prior schema that separates:
  - geometry and approach descriptors that can travel across circuits;
  - Spa-derived expectation ranges for fuel, time, and execution sensitivity;
  - uncertainty/support signals that determine when manual review is still
    required.
- [x] Add the first conservative transferable-archetype layer that can
  materialize a circuit-local `StrategyPriorTable` from a reviewed
  `TrackZoneTable` without changing the optimizer contract.
- [x] Define the first new-circuit bootstrap workflow:
  - push-baseline laps;
  - automatic candidate-zone proposal;
  - low-budget varied-LICO calibration;
  - human review only on ambiguous or out-of-distribution zones.
- [x] Define the metadata and artifact contract for transfer runs so provenance
  survives through `zone_pass`, planning, replay, and live review outputs.
- [x] Add the first transfer-bootstrap provenance table and readiness checklist
  so circuit-local priors can be audited before any new-circuit collection.
- [ ] Define the first evaluation protocol comparing:
  - transfer-assisted bootstrap;
  - no-prior bootstrap;
  - manual-from-scratch fallback.

Notes:

- The project should not promise that `2-5` laps are always enough on every new
  circuit. The target is fast adaptation, not magic.
- The long-term goal is to reduce circuit-by-circuit manual review to a small
  number of ambiguous zones rather than remove human validation entirely.
- The concrete design for this phase now lives in
  `docs/cross_circuit_transfer_v1.md`.

## Current Data Readiness

Current local telemetry assets:

- `none`: initial push baseline;
- `low`: low LICO sample;
- `medium`: medium LICO sample;
- `high`: high LICO sample;
- `pitstop`: pit/refill sample;
- `baseline` refresh: two metadata-linked Spa v2 push-baseline runs;
- `controlled_random`: four metadata-linked Spa v2 runs.

Current interpretation:

- the stable Spa pipeline is good enough for first-generation static planning;
- the experimental branch is good enough to justify deeper optimizer work;
- new targeted data is no longer the automatic next step;
- future data collection should be driven by robust-optimizer and replanning
  diagnostics, not by broad intuition alone.

## Recommended Next Codex Task

```text
OCR is parked; preserve its evidence and do not resume screen capture work.
Start from the completed four-circuit and fuel-first development reviews.
Continue from the bounded Sebring response replay (do not rebuild it).
Build the offline short-qualification-to-initial-plan acceptance test using
native push data only at startup, destination-circuit-held-out coefficient fits,
and provenance checks for geometry, windows, caps and planned-lift acceleration.
Measure end-to-end readiness and compute time; abstain on insufficient coverage.
Then bridge the already bounded local response updates to a shadow-only next-plan
calculation. Retain the frozen transfer baseline and distinguish observed plans
from hypothetical recombinations. Validate the zone-to-whole-lap fuel bridge
separately; zone response accuracy alone cannot prove race feasibility.
Do not repeat the completed Sebring collection or claim the recent race is a
new ML transfer validation. Freeze the candidate and protocol before requesting
a fresh circuit run. No simulator session or Streamlit UI change is needed now.
```
