# LMU Live Integration Notes

This note captures the current factual state of LICOR's live integration path
for the first static in-session cue validation.

## What We Verified Locally

On this machine, the LMU installation contains:

- `C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\Support\SharedMemoryInterface\SharedMemoryInterface.hpp`
- `C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\Support\SharedMemoryInterface\InternalsPlugin.hpp`
- `C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\player\Settings.JSON`

The local `Settings.JSON` currently shows:

- `Enable external plugins = true`
- `WebUI port = 6397`

That is enough evidence to treat LMU live cue support as a real integration
path rather than a hypothetical future branch.

## External References Used

- The local LMU shared-memory support headers in `Support\SharedMemoryInterface`.
- TinyPedal README, which states that on Windows, LMU can be accessed through
  its built-in API when plugins are enabled.
- TinyPedal wiki, which documents LMU shared-memory access plus optional Rest
  API access on `localhost:6397`.
- `goLMUSharedMemory`, whose package docs explicitly describe LMU's built-in
  Windows shared-memory interface and confirm the shared-memory object names
  `LMU_Data` and `LMU_Data_Event`.

## Scope Of The Current LICOR Runner

The current live runner is intentionally narrow:

- static plan only;
- no in-session adaptive replanning;
- Windows only;
- shared-memory driven;
- writes cue event logs in the same schema family as replay validation.

This is the smallest useful layer for true pilot-feel validation.

## CLI Entry Points

Environment check:

```powershell
uv run python scripts/run_lmu_live_cues.py --doctor
```

Bench beep:

```powershell
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
```

First static live run:

```powershell
uv run python scripts/run_lmu_live_cues.py `
  --plan data/processed/experimental/spa_dynamics_v1/live_validation_packs/selected_zones_v1/plan.csv `
  --event-log data/processed/experimental/spa_dynamics_v1/live_validation_packs/selected_zones_v1/live_events.csv `
  --run-id recommendation_execution_selected_01 `
  --file-name recommendation_execution_selected_01 `
  --emit-system-beep `
  --max-laps 6
```

## Current Risks

- The runner depends on LMU's shared-memory layout remaining compatible with the
  current local headers.
- The first live validation should still treat audio timing feel as primary and
  fuel/time outcome as secondary.
- Adaptive next-lap replanning is still an explicit next phase, not part of
  this first live loop.
