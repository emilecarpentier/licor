# Spa Adaptive Handoff Preview Playbook

This playbook is the exact operator procedure for the next adaptive data
collection step in Spa.

It is not true in-session automatic replanning yet.

It is a **frozen follow-up live block** built from the guarded adaptive
between-laps handoff derived from the validated baseline run
`recommendation_execution_selected_latency_v2_02`.

Use this playbook when the goal is:

- collect more live data about whether the guarded adaptive follow-up plan feels
  stable and readable;
- capture several clean laps plus operator notes;
- produce evidence strong enough to judge whether adaptive between-laps can
  leave pure shadow mode.

## Scope

This playbook is for:

- one short live run with the frozen guarded adaptive follow-up candidate;
- a real LMU session with LICOR beeping in the background;
- telemetry-enabled collection with cue logs, notes, and run metadata;
- operator-preview validation, not autonomous adaptive control.

Do **not** use the replay CLI for this session.

Use:

```powershell
scripts/run_lmu_live_cues.py
```

Do **not** use:

```powershell
scripts/run_live_cue_replay.py
```

## Pack And Plan

Folder:

```text
D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2_guarded_preview
```

Plan id:

```text
experimental_guarded_adaptive_handoff|selected_zones_latency_v2_baseline|adaptive_guarded|observed_execution:recommendation_execution_selected_latency_v2_02|lap_8_to_9
```

Recommended run nickname:

```text
recommendation_execution_selected_latency_v2_guarded_preview_01
```

Operator role:

```text
adaptive_guarded_operator_preview
```

Source reference:

```text
source_run_id = recommendation_execution_selected_latency_v2_02
source_handoff = lap 8 -> 9
```

LMU telemetry folder:

```text
C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry
```

## Session Rules

1. Telemetry in LMU must stay `on`.
2. One telemetry recording = one `plan_id`.
3. This is still a frozen plan for the duration of the run.
4. Do not change setup, weather, or tire-wear policy during this block.
5. Tire wear off, fuel usage on, dry stable weather.
6. Stop the LICOR runner manually with `Ctrl+C`.
7. Fill lap notes and zone signoff the same day.

## What To Judge

This session is not asking:

- whether adaptive is perfect;
- whether the final production controller exists;
- whether the model should already rewrite the next lap automatically.

It is asking:

- do the guarded adaptive changes remain readable live?
- do they still feel natural when promoted from shadow into a frozen follow-up
  plan?
- do any specific zones become noticeably too short, too long, or cognitively
  noisy?

Pay special attention to:

- `T08`: now shortened versus the baseline, but clamped by the guardrail;
- `T12-T13`: also shortened but intentionally bounded;
- `T18`: still the most timing-sensitive zone.

## Terminal Layout

Use two PowerShell windows.

### Terminal 1

LICOR runner terminal.

### Terminal 2

Helper terminal for telemetry file checks.

## Part 1: Pre-Session Setup

### 1. Go to repo root

In Terminal 1:

```powershell
Set-Location 'D:\OneDrive - UQAM\licor'
```

### 2. Define variables

Paste this block in Terminal 1:

```powershell
$pack = 'D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2_guarded_preview'
$run = 'recommendation_execution_selected_latency_v2_guarded_preview_01'
$telemetryDir = 'C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry'
$plan = Join-Path $pack 'plan.csv'
$manifest = Join-Path $pack 'pack_manifest.json'
$notes = Join-Path $pack "${run}_lap_notes.csv"
$signoff = Join-Path $pack "${run}_zone_signoff.csv"
$metadata = Join-Path $pack "${run}_run_metadata.json"
$events = Join-Path $pack "${run}_live_events.csv"
$accuracy = Join-Path $pack "${run}_live_events_accuracy.csv"
$stdout = Join-Path $pack "${run}_live_runner_stdout.log"
```

### 3. Make working copies of the operator templates

```powershell
Copy-Item -LiteralPath (Join-Path $pack 'lap_notes_template.csv') -Destination $notes -Force
Copy-Item -LiteralPath (Join-Path $pack 'zone_signoff_template.csv') -Destination $signoff -Force
Copy-Item -LiteralPath (Join-Path $pack 'run_metadata_template.json') -Destination $metadata -Force
```

### 4. Confirm the frozen plan hash

```powershell
$expectedHash = (Get-Content -Path $manifest | ConvertFrom-Json).plan_sha256
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $plan).Hash.ToLower()
"expected=$expectedHash"
"actual=$actualHash"
```

The two hashes must match.

### 5. Snapshot the newest telemetry file before the session

In Terminal 2:

```powershell
Get-ChildItem -Path $telemetryDir -Filter *.duckdb |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 FullName, LastWriteTime, Length
```

### 6. Run doctor and bench beep

In Terminal 1:

```powershell
uv run python scripts/run_lmu_live_cues.py --doctor
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
```

### 7. Pre-drive signoff

Open:

```text
$signoff
```

At minimum, set `pre_drive_signoff` for:

- `T08`
- `T12-T13`
- `T18`

Suggested short values:

- `ok`
- `watch timing`
- `watch readability`

## Part 2: Open LMU And Load The Session

1. Open LMU.
2. Confirm telemetry recording is enabled.
3. Load the same Spa / LMP2 / stable dry session style used for the validated
   baseline.
4. Leave LICOR stopped until the car/session is actually loaded.

## Part 3: Start The Runner

### 8. Start the LICOR transcript

In Terminal 1:

```powershell
Start-Transcript -Path $stdout -Force
```

### 9. Launch the guarded adaptive follow-up runner

In Terminal 1:

```powershell
uv run python scripts/run_lmu_live_cues.py `
  --plan $plan `
  --event-log $events `
  --accuracy-log $accuracy `
  --run-id $run `
  --file-name $run `
  --emit-system-beep
```

If you get `FileExistsError`, stop and switch to a new run nickname such as
`..._02` instead of overwriting the previous attempt.

## Part 4: Driving Block

Recommended structure:

1. out lap: not scored
2. lap 1: familiarization / settle into the new cue set
3. laps 2-5: scored laps if clean
4. optional lap 6: only if one primary zone remains unclear

The minimum useful session is:

- 1 familiarization lap
- 3 clean scored laps

## Part 5: Immediate Post-Run

### 10. Stop the LICOR runner manually

In Terminal 1:

- press `Ctrl+C`

Then:

```powershell
Stop-Transcript
```

### 11. Confirm output files exist

```powershell
Get-Item -LiteralPath $events, $accuracy, $stdout, $notes, $signoff, $metadata |
  Select-Object FullName, Length, LastWriteTime
```

### 12. Identify the new LMU telemetry file

In Terminal 2:

```powershell
$latestTelemetry = Get-ChildItem -Path $telemetryDir -Filter *.duckdb |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
$latestTelemetry | Select-Object FullName, LastWriteTime, Length
```

## Part 6: Metadata And Notes

### 13. Write telemetry path into metadata

In Terminal 1:

```powershell
$telemetryFile = $latestTelemetry.FullName
$meta = Get-Content -Path $metadata | ConvertFrom-Json
$meta.run_id = $run
$meta.file = $telemetryFile
$meta.car = 'Oreca 07 ELMS Custom Team 2025 #397'
$meta.driver_notes = 'Guarded adaptive operator-preview follow-up candidate. Fill lap and zone notes immediately after the run.'
$meta | ConvertTo-Json -Depth 8 | Set-Content -Path $metadata -Encoding UTF8
```

### 14. Fill lap notes

Open:

```text
$notes
```

For each scored lap, note plainly:

- `natural`
- `too_early`
- `too_late`
- `awkward`
- `busy`
- `unknown`

If you want the shortest convention:

- `N` = natural
- `E` = too early
- `L` = too late
- `A` = awkward
- `B` = busy
- `U` = unknown

### 15. Fill post-run zone signoff

Open:

```text
$signoff
```

Set:

- `post_run_status`
- `notes`

Suggested statuses:

- `provisionally_ok`
- `too_early`
- `too_late`
- `awkward`
- `too_busy`
- `unknown`

## Exact Command Set Summary

```powershell
Set-Location 'D:\OneDrive - UQAM\licor'
$pack = 'D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2_guarded_preview'
$run = 'recommendation_execution_selected_latency_v2_guarded_preview_01'
$telemetryDir = 'C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry'
$plan = Join-Path $pack 'plan.csv'
$manifest = Join-Path $pack 'pack_manifest.json'
$notes = Join-Path $pack "${run}_lap_notes.csv"
$signoff = Join-Path $pack "${run}_zone_signoff.csv"
$metadata = Join-Path $pack "${run}_run_metadata.json"
$events = Join-Path $pack "${run}_live_events.csv"
$accuracy = Join-Path $pack "${run}_live_events_accuracy.csv"
$stdout = Join-Path $pack "${run}_live_runner_stdout.log"
Copy-Item -LiteralPath (Join-Path $pack 'lap_notes_template.csv') -Destination $notes -Force
Copy-Item -LiteralPath (Join-Path $pack 'zone_signoff_template.csv') -Destination $signoff -Force
Copy-Item -LiteralPath (Join-Path $pack 'run_metadata_template.json') -Destination $metadata -Force
$expectedHash = (Get-Content -Path $manifest | ConvertFrom-Json).plan_sha256
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $plan).Hash.ToLower()
"expected=$expectedHash"
"actual=$actualHash"
uv run python scripts/run_lmu_live_cues.py --doctor
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
Start-Transcript -Path $stdout -Force
uv run python scripts/run_lmu_live_cues.py --plan $plan --event-log $events --accuracy-log $accuracy --run-id $run --file-name $run --emit-system-beep
```

Then:

- drive the block;
- press `Ctrl+C`;
- run `Stop-Transcript`;
- identify the newest `.duckdb`;
- update `$metadata`;
- fill `$notes` and `$signoff`.
