# Race Strategy And Pit Stops

## Current operational objective — 2026-09-12

The driver confirmed a fuel-first short-qualifying-to-race use case. Fuel
sufficiency to finish (or each explicitly planned refuel) is the constraint;
time loss is minimized only among admissible fuel-feasible plans within the
driver's chosen scenario. Parallel short/long hypotheses must expose the risk
without silently enforcing the longer race. Reserve and consumption uncertainty
remain separate, explicit inputs. No automatic 0.1L reserve or final-15-lap mode.
See `docs/fuel_first_race_contract_2026-09-12.md`.
The first pure offline budget calculator is `analysis/fuel_budget.py`; it does
not connect the HUD, certify uncertainty margins, or enable adaptive live cues.
Historical stop-count studies below remain separate, not an end-to-end race
controller or a guarantee that future refills are reachable.

LICOR's practical value comes from race-time optimization, not only lap-time or
fuel-per-lap reporting. The project should estimate where and how much to
lift-and-coast in order to improve the total race outcome.

For endurance racing, this means pit stops are central to the optimization.

## Core Strategic Question

The important question is not:

```text
How much time does LICO cost on one lap?
```

The important question is:

```text
Can LICO save enough fuel across a stint or race to avoid an extra pit stop, and
is the local time loss smaller than the pit time saved?
```

For the user's ELMS use case, races are 100 minutes. LMP2 cars cannot complete
the full race distance without stopping, and on some circuits full-push driving
may require two stops while a fuel-saving strategy may make one stop possible.

That is the main strategic purpose of LICOR.

## Strategy Layer

LICOR should eventually have two connected layers:

1. Zone-level LICO model.
   Estimate continuous fuel/time tradeoffs by track zone.

2. Race strategy model.
   Use those tradeoffs to choose a fuel target and determine whether the race can
   be completed with fewer stops.

The zone model answers:

```text
If I lift X meters before this brake zone, what local fuel/time tradeoff do I get?
```

The strategy model answers:

```text
Given race length, tank size, pit loss, refill rate, and stint constraints, what
fuel saving target is worth pursuing?
```

## Pit Stop Data

A dedicated Spa LMP2 pit stop telemetry file was recorded to estimate pit stop
behavior. The raw DuckDB file should remain outside Git.

Observed sequence:

- pit exit/out-lap;
- timed lap with pit entry before the end;
- pit stop with fuel refill from roughly 0.4 L to 75 L;
- no tire change;
- pit exit/out-lap to the finish line.

Observed telemetry events:

- `In Pits` entered at approximately `263.65 s` elapsed.
- `In Pits` exited at approximately `332.09 s` elapsed.
- `Speed Limiter` activated at approximately `262.20 s` elapsed.
- `Speed Limiter` deactivated at approximately `332.22 s` elapsed.
- Fuel refill started around `270.45 s` elapsed.
- Fuel refill ended around `310.25 s` elapsed.

Observed pit/refill metrics from this sample:

| Metric | Observed value |
| --- | ---: |
| Speed limiter duration | ~70.0 s |
| `In Pits` duration | ~68.4 s |
| Stationary duration around refill | ~43.3 s |
| Fuel added | ~74.6 L |
| Refill duration while fuel level increased | ~39.8 s |
| Average observed refill rate | ~1.87 L/s |

The observed refill rate should be treated as an empirical measurement from this
file, not a universal LMU rule. The user has noted that LMU refueling behavior
may be documented or understood elsewhere as approximately 3 L/s plus hose
attach/detach time and possible random variation. LICOR should allow these
parameters to be configured and compared against telemetry-derived estimates.

## Pit Stop Cost

Pit stop cost should not be represented only as stationary time. A useful race
model needs several components:

- pit entry loss;
- pit limiter time;
- stationary service time;
- refueling time;
- hose attach/detach overhead;
- pit exit loss;
- optional tire service time;
- possible random service variation.

For early LICOR versions, the most useful measured quantity may be the total
pit-lane commitment time from limiter on to limiter off. Later, LICOR can split
this into entry, stationary, refill, and exit components.

## Optimization Implication

Zone-level LICO optimization should provide a per-lap fuel saving curve:

```text
target fuel saving per lap -> expected local time loss per lap
```

Race strategy then compares:

```text
time lost by saving fuel across the race
vs
time saved by avoiding an extra pit stop
```

For example:

```text
If full push requires 2 stops but LICO can make 1 stop possible, LICOR should
estimate the required fuel saving per lap and decide whether the cumulative LICO
time loss is smaller than the avoided pit stop loss.
```

## Future Inputs

The strategy layer should eventually accept:

- race length in minutes;
- expected lap time range;
- fixed race-lap overrides when a championship result or regulation provides a
  better estimate than duration/lap-time arithmetic;
- tank capacity;
- starting fuel rules;
- fuel per lap at push baseline;
- fuel saved per lap from zone-level LICO plan;
- pit lane loss;
- refill rate;
- mandatory stop rules;
- tire change time, if relevant;
- stint constraints or driver swap constraints, if relevant.

## Current Implementation

`src/licor/analysis/race_strategy.py` now provides a first deterministic
strategy layer:

- estimate race laps from race duration and baseline lap time;
- compute required stop count from tank capacity and fuel per lap;
- compare full-push and LICO-style scenarios on total estimated time;
- compute fuel-saving targets needed for lower stop counts.

The first Spa strategy artifacts are generated locally under `data/processed/`:

- `spa_lmp2_race_strategy_scenarios.csv`;
- `spa_lmp2_fuel_saving_targets.csv`.

For Spa ELMS, the driver supplied a championship-observed distance of `48` laps.
The push baseline needs `2` stops, and a `1`-stop strategy requires roughly
`0.321 L/lap` saved versus push baseline. Current global `medium` and `high`
LICO laps meet that target in aggregate, but they should be treated as
feasibility evidence rather than final recommendations.

The first conservative zone-level optimizer uses only `model_ready` zone model
points. With the current Spa models, `T05-T06`, `T10-T11`, and `T18` together
reach approximately `0.307 L/lap`, leaving a shortfall of roughly `0.014 L/lap`
against the 1-stop target. The current plan is therefore marked
`target_unreachable` unless diagnostic-only zones are explicitly allowed or new
targeted data improves the model-ready set.

Driver strategy priors now provide that explicit allowance. The current Spa
driver-prior file rates LICO feasibility as:

- `5/5`: T05-T06, T18;
- `4/5`: T12-T13, T08, T01;
- `2/5`: T10-T11, T14;
- `0/5`: T19, T09.

Using those priors, the prudent optimizer can include feasible diagnostic zones
without altering the model-predicted time loss. Driver ratings are treated as
feasibility/capping metadata, not as time penalties. The current prudent plan
reaches the 48-lap one-stop target with a small fuel surplus and distributes
LICO across T01, T05-T06, T08, T10-T11, T12-T13, and T18 while leaving T14 at
`0 m`. This should be reviewed visually before being promoted to a
recommendation.

The current visual validation artifact is
`data/processed/spa_lmp2_zone_lico_plan_driver_priors_prudent_report.html`. It
places the selected optimizer points directly on the zone fuel, time, and ratio
curves so the driver can judge whether each chosen LICO distance is credible.

## Recommendation Validation Direction

The plan report is a diagnostic tool, not the final empirical validation method.
The driver can identify impossible zones, contaminated curves, and weak signals,
but should not be expected to confirm that an exact lift distance such as
`70 m` is optimal by visual inspection.

The next validation loop should be:

1. Use offline models and strategy targets to export a LICO plan.
2. Execute the plan with a minimal live audio cue that tells the driver when to
   lift.
3. Log the actual lift start, brake start, fuel use, local time, and full-lap
   sanity metrics.
4. Compare planned versus executed LICO and update the model.

This means Streamlit remains a reporting and review tool. The practical driving
validation layer is a small live telemetry/audio-cue runner that consumes a
tested plan format and writes execution telemetry for later analysis.

`src/licor/analysis/live_plan.py` now provides the first code-level contract for
that bridge. It exports selected optimizer rows into a versioned `live_cue_plan`
table and computes:

```text
planned_lift_start_m = brake_reference_m - selected_lico_distance_m
```

The exported `cue_distance_m` currently matches `planned_lift_start_m`. A later
runner can apply audio latency or anticipation offsets while keeping the plan's
driver reference point stable. The same module also defines a replay execution
schema that joins an exported plan to observed `zone_pass` telemetry, producing
planned-vs-executed rows before any live audio integration is attempted.

`src/licor/analysis/live_cue_runner.py` adds the first deterministic trigger and
logging layer for that plan. It replays telemetry samples through the same
distance-crossing logic the future live runner should use, handles lap wrap, and
produces cue timing accuracy logs. The actual audio adapter remains separate so
the strategy and telemetry contracts can be tested before driving with sound.

`src/licor/live/` now wraps that deterministic layer with file I/O and injectable
audio adapters. Replay sessions can load a plan CSV plus telemetry sample CSV,
write the primary cue event log, write a derived accuracy summary, and call a
fake or real audio adapter per triggered cue. Automated tests use the recording
adapter only; real sound remains an explicit driving-session validation step.
Logs are written before audio is emitted, and existing logs require an explicit
overwrite flag.

## Data Collection Direction

The initial Spa dataset used labeled global `none`, `low`, `medium`, and `high`
LICO runs to establish the first relationships. Future data should shift toward
more informative variation:

- controlled-random LICO runs, where lift distances vary enough to fill the
  continuous curves;
- targeted zone runs, where only a small number of zones are emphasized so the
  model can separate one zone's effect from another;
- recommendation-execution runs, where the model exports a plan and live cues
  help the driver follow it.

More data is useful only if it improves identification. Pure global LICO laps
can still be valuable, but if every zone is changed together the model may learn
correlations rather than causal zone costs.

## Cross-Circuit Strategy

For future circuits, LICOR should not require a full Spa-style manual rebuild if
the learned structure transfers well. The intended workflow is:

- collect mostly push laps to identify braking zones, approach speeds, brake
  severity, baseline fuel, and baseline lap time;
- automatically propose candidate LICO zones and first boundaries from braking
  and approach telemetry;
- use Spa-learned priors to estimate initial feasibility and curve shapes based
  on zone features;
- collect a small number of varied LICO laps to update those priors for the new
  circuit;
- require manual review only for out-of-distribution zones, weak telemetry
  signals, or zones whose recommendation would materially affect race strategy.

Machine learning is useful here as a transfer layer: it can learn that zones
with similar approach speed, braking demand, straight length, and corner
complexity tend to have similar fuel/time behavior. It should reduce the number
of laps and manual adjustments needed on a new circuit, not eliminate all
calibration or driver review.
