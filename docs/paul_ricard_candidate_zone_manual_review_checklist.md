# Paul Ricard Candidate Zone Manual Review Checklist

Use this checklist before the first `controlled_random` block on Paul Ricard.

Goal:

- sanity-check that the current bootstrap draft matches the real track flow;
- catch any obviously bad zone boundary before varied-LICO collection;
- avoid doing a heavy Spa-style review too early.

This is a **light review**, not a final zone signoff.

## How To Use It

For each candidate zone, answer only these three questions:

1. **Start OK?**
   - Is the zone start clearly early enough that a realistic LICO could begin
     there without already being late?
2. **Brake OK?**
   - Does the brake reference point to the correct braking event for that zone?
3. **End OK?**
   - Does the zone end before the next phase becomes confusing or polluted by a
     different braking event?

Use one of these outcomes:

- `OK`: no obvious issue, keep as-is
- `EARLIER`: zone should start earlier
- `LATER`: zone should start later
- `SHORTER`: zone should end earlier
- `LONGER`: zone should end later
- `WRONG_BRAKE`: brake reference is tied to the wrong event
- `DROP`: remove from candidate roster for now
- `VALIDATION_ONLY`: keep visible, but not as a first-pass optimization target

If you are unsure, prefer `OK` and move on. We are trying to catch only the
big misses.

## Candidate Roster

### 1. `pr_t01_t02` - `T01-T02`

- Current start: `369.14 m`
- Current brake reference: `489.14 m`
- Current end: `749.14 m`
- Why it is here:
  big first braking event after the start/finish straight.

Quick review question:

- Does this feel like one coherent LICO context into the first major braking
  event, or does the current end run too far into the next phase?
  - ANSWER : ITS OK

Verdict:

- Outcome:EARLIER (ANOTHER 120M EARLIER THAN BRAKE REF TO BE SAFE)
- Note:

### 2. `pr_t03` - `T03`

- Current start: `1069.95 m`
- Current brake reference: `1189.95 m`
- Current end: `1269.95 m`
- Why it is here:
  first brake of the `T03-T07` sequence.

Important existing note:

- Lap 13 baseline push had a known braking mistake here.
- Future data review should allow a **zone-only exclusion on T03** rather than
  punishing the whole lap.

Quick review question:

- Is this clearly the right first braking event of the sequence, and is the
  current end short enough to avoid smearing into the rest of the complex?

Verdict:

- Outcome: EARLIER START, LATER END (ADD EXTRA 50M).
- Note:

### 3. `pr_t08_t09` - `T08-T09`

- Current start: `2686.66 m`
- Current brake reference: `2806.66 m`
- Current end: `3066.66 m`
- Why it is here:
  Mistral chicane, very clear heavy braking event at high speed.

Quick review question:

- Does this zone cleanly capture the chicane entry opportunity, without
  extending into a second distinct phase that should later be separated?

Verdict:

- Outcome: EARLIER (START), END = OK
- Note:

### 4. `pr_t11` - `T11`

- Current start: `4067.26 m`
- Current brake reference: `4187.26 m`
- Current end: `4447.26 m`
- Why it is here:
  high-speed technical braking event entering the Beausset section.

Quick review question:

- Does this feel like a real local LICO candidate, or is it too sensitive /
  too loaded to trust as a first-pass target?

Verdict:

- Outcome: OK
- Note:

### 5. `pr_t12` - `T12`

- Current start: `4562.94 m`
- Current brake reference: `4682.94 m`
- Current end: `4942.94 m`
- Why it is here:
  follow-on braking event after `T11`.

Quick review question:

- Does this deserve to stay separate from `T11`, or does it already feel like
  the same broader section in practice? ANSWER = SEPARATE FROM T11

Verdict:

- Outcome: START = LATER (100M INSTEAD OF 120M), END = EARLIER (200M AFTER BRAKE POINT)
- Note:

### 6. `pr_t14` - `T14`

- Current start: `5072.52 m`
- Current brake reference: `5192.52 m`
- Current end: `5272.52 m`
- Why it is here:
  distinct short late-lap braking event.

Quick review question:

- Is this a real standalone opportunity, or does it feel too short / too minor
  to justify first-pass candidate status?

Verdict:

- Outcome: OK
- Note:

### 7. `pr_t15` - `T15`

- Current start: `5296.63 m`
- Current brake reference: `5416.63 m`
- Current end: `5676.63 m`
- Why it is here:
  final-corner braking event before the run onto the front straight.

Quick review question:

- Does this feel like a valid last-corner LICO context, or does the straight
  after it make the local tradeoff obviously too dangerous for early testing?

Verdict:

- Outcome:
- Note: T15 shouldn't have any LICO, the T14-T15 section is quite connected, and it's a bit of a weird passage. we shouldn't let the model try to put lico on T15, only T14.

## Zones Held Out For Now

These are intentionally **not** in the first controlled-random candidate set:

- `pr_t05` / `T05`
- `pr_t07` / `T07`

Default stance:

- leave them alone unless the manual review strongly suggests one of them is an
  obvious missed opportunity.

## Decision Rule After Review

If you finish this checklist and:

- everything is mostly `OK`:
  proceed directly to `controlled_random_01` and `controlled_random_02`
- one or two zones need only small boundary nudges:
  adjust the draft, then proceed
- a zone feels fundamentally wrong:
  demote it to `validation_only` before collecting varied-LICO data

Do not try to solve:

- optimal LICO distance,
- final strategy role,
- or final live-cue timing

in this checklist. Those belong to later steps.
