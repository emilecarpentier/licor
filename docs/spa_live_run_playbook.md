# Spa Live Run Playbook

This playbook is the exact operator procedure for the first true in-session
Spa live cue validation in LMU.

It is intentionally concrete. It is written to remove hesitation, not to be
elegant.

For the next adaptive follow-up collection step derived from the guarded
between-laps handoff, use:

```text
docs/spa_adaptive_handoff_preview_playbook.md
```

## Scope

This playbook is for:

- the first **static live** validation only;
- the frozen selected-zones latency v2 baseline first;
- Candidate B only if Candidate A passes;
- real LMU driving with LICOR beeping in the background;
- no adaptive in-session replanning yet.

Do **not** use the replay CLI for this session.

Use:

```powershell
scripts/run_lmu_live_cues.py
```

Do **not** use:

```powershell
scripts/run_live_cue_replay.py
```

## Files You Will Use

### Candidate A pack

Folder:

```text
D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2
```

Plan id:

```text
experimental_live_candidate_range_aware_selected_zones_latency_v2
```

Recommended run nickname:

```text
recommendation_execution_selected_latency_v2_01
```

Current role:

```text
official frozen static-live baseline
```

### Candidate B pack

Folder:

```text
D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\all_eligible_latency_v2
```

Plan id:

```text
experimental_live_candidate_range_aware_all_eligible_zones_latency_v2
```

Recommended run nickname:

```text
recommendation_execution_all_eligible_latency_v2_01
```

Current role:

```text
secondary comparison live variant
```

### LMU telemetry folder

```text
C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry
```

## Session Rules

1. One telemetry recording = one `plan_id`.
2. Candidate A and Candidate B must be separate LMU recordings.
3. No setup experiments during the session.
4. Tire wear off, fuel usage on.
5. Dry, stable weather.
6. Start with Candidate A.
7. Do not rely on auto-stop for the first live run. Stop the LICOR runner
   manually with `Ctrl+C` after the block is complete.
8. Treat older selected-zones packs as archived provenance unless a specific
   replay/comparison task asks for them.

## Terminal Layout

Use two PowerShell windows.

### Terminal 1

LICOR runner terminal.

This is where you will run:

- doctor
- bench beep
- the real live cue process

### Terminal 2

Optional helper terminal.

Use it for:

- checking telemetry files before and after the session
- quick file sanity checks
- anything you do not want to interrupt in Terminal 1

## Part 1: Pre-Session Setup

Run these commands **before** opening LMU.

### 1. Go to repo root

In Terminal 1:

```powershell
Set-Location 'D:\OneDrive - UQAM\licor'
```

### 2. Define Candidate A variables

Paste this block in Terminal 1:

```powershell
$pack = 'D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2'
$run = 'recommendation_execution_selected_latency_v2_01'
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

Paste:

```powershell
Copy-Item -LiteralPath (Join-Path $pack 'lap_notes_template.csv') -Destination $notes -Force
Copy-Item -LiteralPath (Join-Path $pack 'zone_signoff_template.csv') -Destination $signoff -Force
Copy-Item -LiteralPath (Join-Path $pack 'run_metadata_template.json') -Destination $metadata -Force
```

### 4. Confirm the frozen plan hash

Paste:

```powershell
$expectedHash = (Get-Content -Path $manifest | ConvertFrom-Json).plan_sha256
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $plan).Hash.ToLower()
"expected=$expectedHash"
"actual=$actualHash"
```

The two hashes must match.

If they do not match, stop and do not run the session.

### 5. Snapshot the newest telemetry file before the session

In Terminal 2:

```powershell
Get-ChildItem -Path $telemetryDir -Filter *.duckdb |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 FullName, LastWriteTime, Length
```

This gives you a baseline so you can identify the new file after the run.

### 6. Run LICOR doctor

In Terminal 1:

```powershell
uv run python scripts/run_lmu_live_cues.py --doctor
```

Expected now:

- `status_flags=ok`
- `shared_memory_probe=False`

That is **fine before LMU is open**.

### 7. Run bench beep

In Terminal 1:

```powershell
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
```

If the beep is too quiet, fix volume **before** driving.

### 8. Fill the pre-drive signoff file

Open:

```text
$signoff
```

At minimum, fill `pre_drive_signoff` for:

- `T05-T06`
- `T12-T13`
- `T18`

Short values are enough:

- `ok`
- `watch timing`
- `watch workload`

### 9. Prepare the note-taking method

Do **not** plan to type notes while driving.

Use one of these:

- a paper sheet
- a phone note
- a voice memo

Then transcribe into:

```text
$notes
```

immediately after the session.

## Part 2: Open LMU And Load The Session

### 10. Open LMU

Open LMU normally.

### 11. Configure the session

Use:

- Spa-Francorchamps
- same LMP2 setup as the current Spa work
- dry, stable weather
- tire wear off
- fuel usage on
- start fuel 45 to 55 L
- low or zero traffic if possible

### 12. Start the Candidate A session

Enter the session and get to the garage.

### 13. Wait until the car and session are fully loaded

Important:

The LICOR runner must attach only after LMU is truly alive enough to expose its
shared memory.

If you launch LICOR too early, you may get:

```text
Could not open LMU shared memory 'LMU_Data': WinError 2
```

That simply means LMU is not ready yet. It is not a model failure.

## Part 3: Launch The Live Cue Runner

### 14. Start transcript logging in Terminal 1

```powershell
Start-Transcript -Path $stdout -Force
```

### 15. Launch the real live cue runner

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

Expected behavior:

- the process attaches and then mostly stays quiet;
- beeps happen only when cues fire;
- the process continues running until you stop it with `Ctrl+C`.

If you get `WinError 2` here:

1. Alt-tab back to LMU.
2. Make sure the car is fully loaded and the session is really active.
3. Return to Terminal 1.
4. Run the same command again.

## Part 4: Drive Candidate A

### 16. Use this lap structure

For Candidate A:

1. out lap: not scored
2. lap 1: familiarization, not scored
3. lap 2: first interaction, not scored by default
4. laps 3 to 5: scored clean laps
5. lap 6: optional confirmation lap if exactly one key zone remains unclear

### 17. Focus zones

Priority zones:

- `T05-T06`
- `T12-T13`
- `T18`

Secondary but important:

- `T01`
- `T08`
- `T10-T11`

### 18. Lap note codes

Use:

- `N` = natural
- `E` = too early
- `L` = too late
- `A` = awkward but manageable
- `S` = unsafe or unacceptable
- `X` = invalid for that lap due to traffic/mistake/loss of focus

### 19. Abort rules during the drive

Abort Candidate A immediately if:

- any cue in `T01`, `T05-T06`, or `T18` feels unsafe;
- the same important zone feels clearly wrong twice in a row;
- cue audibility becomes unreliable;
- you start compensating for the system instead of driving the car.

## Part 5: Stop The Runner And Capture Files

### 20. End the driving block

When Candidate A is complete:

- finish the lap safely
- return to a safe state in LMU

### 21. Stop the LICOR runner manually

In Terminal 1:

- press `Ctrl+C`

Then run:

```powershell
Stop-Transcript
```

### 22. Confirm the expected output files exist

In Terminal 1:

```powershell
Get-Item -LiteralPath $events, $accuracy, $stdout, $notes, $signoff, $metadata |
  Select-Object FullName, Length, LastWriteTime
```

### 23. Identify the new LMU telemetry file

In Terminal 2:

```powershell
$latestTelemetry = Get-ChildItem -Path $telemetryDir -Filter *.duckdb |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
$latestTelemetry | Select-Object FullName, LastWriteTime, Length
```

If the newest file is clearly the run you just completed, keep its full path.

## Part 6: Update The Run Metadata File

### 24. Write the telemetry file path and run id into metadata

In Terminal 1:

```powershell
$telemetryFile = $latestTelemetry.FullName
$meta = Get-Content -Path $metadata | ConvertFrom-Json
$meta.run_id = $run
$meta.file = $telemetryFile
$meta.car = 'Oreca 07 ELMS Custom Team 2025 #397'
$meta.driver_notes = 'Candidate A static live cue pilot. Fill detailed notes after transcribing lap sheet.'
$meta | ConvertTo-Json -Depth 8 | Set-Content -Path $metadata -Encoding UTF8
```

If the car string differs in-game, edit it manually after this command.

### 25. Transcribe lap notes into the CSV

Open:

```text
$notes
```

Fill each lap row honestly.

Do not force a judgment if a zone remained unclear.

### 26. Update post-run zone signoff

Open:

```text
$signoff
```

Fill:

- `post_run_status`
- `notes`

Suggested status values:

- `provisionally_ok`
- `too_early`
- `too_late`
- `awkward`
- `unsafe`
- `unknown`

## Part 7: Decide Whether Candidate B Is Allowed

Candidate B is allowed only if Candidate A passes your real feel check.

Candidate A passes if:

- you got at least 3 clean scored laps;
- nothing felt unsafe;
- the cues did not create overload;
- you would willingly run another short block with the same cue set.

If Candidate A fails, stop here and do not run Candidate B.

## Part 8: Candidate B Procedure

Only do this if Candidate A passed.

### 27. Reset variables for Candidate B

In Terminal 1:

```powershell
$pack = 'D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\all_eligible_latency_v2'
$run = 'recommendation_execution_all_eligible_latency_v2_01'
$plan = Join-Path $pack 'plan.csv'
$manifest = Join-Path $pack 'pack_manifest.json'
$notes = Join-Path $pack "${run}_lap_notes.csv"
$signoff = Join-Path $pack "${run}_zone_signoff.csv"
$metadata = Join-Path $pack "${run}_run_metadata.json"
$events = Join-Path $pack "${run}_live_events.csv"
$accuracy = Join-Path $pack "${run}_live_events_accuracy.csv"
$stdout = Join-Path $pack "${run}_live_runner_stdout.log"
```

Then repeat the exact same preparation steps:

- copy templates
- confirm plan hash
- start transcript
- launch LICOR runner

### 28. Candidate B launch command

```powershell
Start-Transcript -Path $stdout -Force
uv run python scripts/run_lmu_live_cues.py `
  --plan $plan `
  --event-log $events `
  --accuracy-log $accuracy `
  --run-id $run `
  --file-name $run `
  --emit-system-beep
```

### 29. Candidate B driving block

Use:

1. one reset lap
2. three scored clean laps

Main questions:

- does `T14 = 20 m` stay invisible and non-distracting?
- does `T01 = 60 m` feel better than `70 m`?
- does `T10-T11 = 40 m` still feel worth it?

### 30. Stop Candidate B exactly like Candidate A

- `Ctrl+C`
- `Stop-Transcript`
- identify the new `.duckdb`
- update metadata
- transcribe notes

## Part 9: Final Post-Run Checklist

At the end of the day, Candidate A should leave you with:

- one raw LMU `.duckdb`
- one live event log CSV
- one live accuracy CSV
- one runner stdout log
- one lap notes CSV
- one zone signoff CSV
- one filled metadata JSON

Run this final check in Terminal 1:

```powershell
Get-ChildItem -LiteralPath $pack |
  Where-Object { $_.Name -like "${run}*" -or $_.Name -eq 'plan.csv' -or $_.Name -eq 'pack_manifest.json' } |
  Select-Object Name, Length, LastWriteTime
```

## Exact Candidate A Command Set Summary

If you want the shortest copy-paste version for Candidate A, it is this:

```powershell
Set-Location 'D:\OneDrive - UQAM\licor'
$pack = 'D:\OneDrive - UQAM\licor\data\processed\experimental\spa_dynamics_v1\live_validation_packs\selected_zones_latency_v2'
$run = 'recommendation_execution_selected_latency_v2_01'
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
