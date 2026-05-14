# Race Strategy And Pit Stops

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
- tank capacity;
- starting fuel rules;
- fuel per lap at push baseline;
- fuel saved per lap from zone-level LICO plan;
- pit lane loss;
- refill rate;
- mandatory stop rules;
- tire change time, if relevant;
- stint constraints or driver swap constraints, if relevant.
