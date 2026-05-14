# LICOR Product Specification

## Purpose

LICOR is an offline telemetry analysis tool for Le Mans Ultimate. Its purpose is
to help a high-level endurance sim racing driver identify efficient
lift-and-coast opportunities: places where fuel can be saved with the smallest
possible lap time loss.

The first version is not meant to replace driver judgment. It should translate
expert racing intuition into repeatable telemetry metrics, visualizations, and
recommendations.

## Target User

The primary user is an advanced or professional-level sim racing driver who can
produce controlled telemetry sessions:

- full push reference laps;
- lift-and-coast laps;
- warm-up or out-lap data;
- repeated runs under similar fuel, tire, setup, and track conditions.

The user understands vehicle dynamics and racecraft. LICOR should therefore make
its assumptions visible and editable instead of hiding them behind unexplained
automation.

## Initial Scope

The MVP focuses on:

- Le Mans Ultimate;
- LMP2;
- Spa;
- recorded telemetry files;
- offline analysis after a driving session.

## Out Of Scope For The MVP

The following features are intentionally excluded from the first version:

- live telemetry;
- audio cues;
- race overlay;
- machine learning;
- automatic race strategy optimization;
- multi-car comparison;
- general support for every car and track combination.

These may become future features after the offline analysis pipeline is reliable.

## Inputs

The MVP should load recorded telemetry data containing, at minimum:

- time or sample index;
- lap identifier or enough information to infer laps;
- lap distance;
- speed;
- throttle position;
- brake position;
- fuel level;
- gear, if available;
- sector or lap time events, if available.

The data source may evolve. The code should separate raw LMU channel names from
LICOR's internal normalized schema.

## Outputs

The MVP should produce:

- a lap summary table;
- fuel used per valid lap;
- lap time per valid lap;
- detected braking zones;
- detected candidate lift-and-coast zones;
- comparison between push and LICO laps;
- a ranked list of recommended lift zones;
- pit stop and refill observations, when pit stop data is provided;
- race strategy estimates for whether fuel saving can avoid an extra stop;
- simple plots for throttle, brake, speed, fuel, and lap distance.

## Core Metrics

Initial metrics should include:

- fuel used per lap;
- lap time;
- fuel saved versus push reference;
- time lost versus push reference;
- fuel saved per second lost;
- zone-level fuel saved;
- zone-level local time lost;
- LICO start distance;
- LICO start distance before reference brake point;
- LICO duration;
- LICO end distance;
- distance from LICO start to braking point;
- minimum speed impact through the braking zone or corner entry.
- pit lane commitment time;
- refill duration;
- fuel added during a pit stop;
- observed refill rate;
- estimated value of avoiding an extra pit stop.

The exact interpretation of these metrics should be reviewed with the driver
after the first real dataset.

## Success Criteria

The MVP is successful when it can:

1. load one controlled LMU telemetry session;
2. separate valid laps from out-laps, in-laps, and warm-up laps;
3. compute plausible fuel usage and lap times;
4. identify the main braking zones at Spa;
5. identify candidate lift-and-coast zones before braking zones;
6. compare push and LICO behavior inside driver-reviewed track zones;
7. estimate pit stop/refill cost from pit stop telemetry;
8. produce a simple report that helps decide where to lift in a stint or race.

## Design Principles

- Keep the first version offline and reproducible.
- Prefer transparent heuristics before machine learning.
- Keep driver expertise central to the project.
- Make assumptions explicit in documentation and configuration.
- Prefer zone-level causal analysis over full-lap imitation.
- Treat LICO intensity as a continuous optimization problem, not as a
  classification problem over `none`, `low`, `medium`, and `high`.
- Evaluate LICO recommendations in the context of race length, tank capacity,
  and pit stop cost.
- Write small, testable analysis functions before building the app.
- Treat plots and reports as decision-support tools, not as final truth.
