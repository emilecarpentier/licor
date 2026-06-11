# Cross-Circuit Transfer v1

This document defines the next design step after the frozen Spa live baseline
and the first guarded adaptive follow-up validation.

The goal is not to jump directly into a second-circuit implementation. The goal
is to define the smallest credible transfer workflow that LICOR can later
implement without smuggling Spa-only assumptions into the new-circuit path.

## Why This Is The Next Step

Spa has now given LICOR three useful things:

- a stable telemetry and review pipeline;
- a validated static live baseline with speed-aware cue timing;
- a first adaptive between-laps logic that is credible enough to study further.

That means the next major project risk is no longer "can Spa work at all?".
It is:

```text
Can Spa be turned into reusable priors and a low-data bootstrap workflow for a
new circuit?
```

## Deferred Live-Polish Backlog

The idea of adapting cue-latency compensation to the driver's effective
reaction time is valid and should stay visible for future live work.

It is not the next bottleneck.

For now:

- keep `selected_zones_latency_v2` as the frozen live baseline;
- keep zone-speed-aware cue timing as the default live behavior;
- treat reaction-time adaptation as a later session-level calibration layer.

When this backlog item is eventually implemented, it should:

- estimate effective cue-to-lift delay from reliable observed execution only;
- explicitly exclude missed-audio laps, obvious cue-perception failures, and
  other operator-noise outliers;
- adjust cue trigger timing only (`cue_distance_m`), while preserving
  `planned_lift_start_m` as the lift anchor;
- stay bounded and session-level before any attempt at aggressive per-zone or
  intra-session autonomy.

## Reusable Building Blocks Already In Repo

LICOR already has more circuit-agnostic infrastructure than the current Spa
focus might suggest.

- `src/licor/analysis/track_zones.py` already defines a generic reviewed-zone
  schema and validation layer.
- `src/licor/analysis/track_zone_proposals.py` can already assign braking zones
  and propose draft references once a circuit has an initial zone roster.
- `src/licor/reports/track_map.py` and
  `src/licor/reports/zone_validation_map.py` already provide generic map and
  proposal visualization support.
- The core modeling path is already mostly reusable once reviewed `zone_pass`
  rows exist:

  ```text
  zone_pass -> zone_curves -> zone_models -> zone_optimizer -> live_plan
  ```

- `src/licor/analysis/strategy_priors.py` and the experimental robust-optimizer
  path already provide the beginnings of a conservative prior-aware planning
  layer.

That means the next phase does not need to invent a second full stack. It needs
to connect a new-circuit bootstrap layer to the existing one.

## Objective

Define a transfer-ready methodology that can bootstrap a new circuit from a
small data budget while preserving:

- reviewability;
- uncertainty awareness;
- manual fallback when the circuit does not look "Spa-like";
- continuity with the current `zone_pass`, planning, replay, and live-review
  contracts.

## Out Of Scope

This phase does not yet:

- implement a new-circuit refit end to end;
- promise full automation on a new circuit;
- replace the current Spa live baseline;
- add reaction-time adaptation;
- add tire-wear or fuel-mass intelligence to the local LICO model;
- promote adaptive between-lap live handoff into autonomous in-session control.

## What Must Transfer From Spa

The first transfer attempt should reuse Spa in three layers.

### 1. Transferable zone descriptors

These are descriptors that should mean roughly the same thing on any circuit:

- approach speed;
- brake-start speed;
- braking severity;
- braking duration / area;
- straight-length proxy before the brake;
- corner-complex shape proxy;
- apex speed / exit speed deltas where available;
- local support / uncertainty / extrapolation signals;
- execution-sensitivity tags such as "stable", "timing-sensitive", or
  "micro-lico-only".

### 2. Transferable planning priors

These are Spa-learned expectations that can seed a new circuit:

- credible LICO distance ranges by zone type;
- initial fuel-saved-per-meter expectations;
- initial time-cost-per-meter expectations;
- expectations about which zone families are robust versus fragile;
- expectations about which zones should stay small even if mathematically
  attractive.

### 3. Transferable operator rules

These are process rules rather than model outputs:

- freeze a static baseline before live adaptive experiments;
- separate replay validation from real-session feel validation;
- keep human review for ambiguous or out-of-distribution zones;
- avoid giving live authority to weakly supported adaptive changes.

## Phase 10a Deliverables

The next implementation block should produce four concrete things.

### A. Transferable prior schema

Define a schema that can express, per zone or zone-family:

- descriptors that come from mostly push laps;
- Spa-derived prior expectations;
- support / confidence fields;
- manual review flags;
- execution-sensitivity annotations.

This schema should be explicit about what is:

- observed locally on the new circuit;
- inherited from Spa;
- inferred by heuristics.

### B. New-circuit bootstrap workflow

Define the minimal bootstrap path:

1. collect mostly push baseline laps;
2. auto-propose candidate braking / LICO zones;
3. assign initial prior classes from Spa-like descriptors;
4. collect a small varied-LICO calibration budget;
5. promote, cap, or reject zones based on evidence and uncertainty;
6. export a first static candidate plan;
7. use replay/live validation only after the static candidate is credible.

### C. Metadata and artifact contract

Define what must survive a transfer run so the data can later be audited:

- source of the prior;
- source of the candidate-zone proposal;
- local versus transferred descriptors;
- local calibration status;
- uncertainty flags;
- manual review decisions.

This should stay compatible with:

- `zone_pass`;
- plan exports;
- replay review;
- live recommendation-execution review.

The first lightweight implementation of that contract now exists in code:

- a conservative transferable-archetype layer can materialize a
  `StrategyPriorTable` from a reviewed `TrackZoneTable`;
- a `TransferBootstrapProvenanceTable` can record where each zone prior came
  from and whether manual review is still required;
- a transfer-bootstrap evaluation checklist can say whether the current
  bootstrap artifacts are ready enough that the next real dependency is a new
  circuit dataset.

### D. Evaluation protocol

Define how the first transfer pilot will be judged.

At minimum, compare:

- transfer-assisted bootstrap;
- no-prior bootstrap;
- manual-from-scratch review fallback.

And evaluate:

- number of zones needing human rescue;
- fuel-target reachability;
- predicted local time credibility;
- live/replay readability of the first static plan.

## Suggested Sequencing

This is the order I recommend.

1. Define the transferable prior schema on paper first.
2. Define the bootstrap workflow and metadata contract.
3. Only then implement the first export/artifact layer from current Spa data.
4. After that, build the new-circuit proposal path.
5. Only then plan the first second-circuit collection block.

That sequencing matters because it prevents LICOR from baking Spa-only logic
into code before the transfer contract is clear.

## Immediate Next 3 Steps

The next concrete work should be:

1. add a small transferable-prior schema and artifact spec;
2. materialize those priors into a circuit-local `StrategyPriorTable` from a
   reviewed `TrackZoneTable`;
3. define the bootstrap metadata / provenance contract and evaluation
   checklist.

That is enough to start implementation without needing new telemetry today.

Those three items now exist in first-pass form. The next dependency is no
longer an internal contract gap; it is the eventual choice and collection of a
new circuit dataset.

## Smallest Sensible Implementation Slice

The smallest real code step after this design work should be:

```text
new circuit reviewed TrackZoneTable
-> transferable archetype/prior assignment
-> circuit-local StrategyPriorTable
-> existing optimizer path
```

This is intentionally smaller than full automatic zone discovery.

That first slice now exists in the codebase as a conservative transferable
archetype layer that can map a reviewed `TrackZoneTable` into a circuit-local
`StrategyPriorTable` for the existing optimizer path.

Why start here:

- it plugs into the current optimizer contract with minimal disruption;
- it gives immediate multi-circuit value without pretending the zone-roster
  discovery problem is solved;
- it keeps the first implementation slice testable with synthetic or manually
  seeded non-Spa zone tables.

## Exit Criteria For This Design Phase

Phase 10a is done when:

- the prior schema is specific enough to implement;
- the bootstrap workflow is concrete enough to run on a new circuit later;
- the metadata contract is explicit enough to keep provenance intact;
- the evaluation protocol is clear enough that "worked" versus "did not work"
  will not be hand-wavy.
