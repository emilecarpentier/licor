param(
    [ValidateRange(0,9999)][Nullable[int]]$FirstScoredLap = $null,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$RunId = ('sebring_lico_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [switch]$ConfirmTelemetryRecording,
    [string]$TelemetryDir = 'C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry'
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '__ROOT__')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not $ConfirmTelemetryRecording) {
        throw 'Start LMU telemetry recording, then relaunch with -ConfirmTelemetryRecording. This switch does not enable recording.'
    }
    if (-not (Test-Path -LiteralPath $TelemetryDir -PathType Container)) { throw "LMU telemetry directory not found: $TelemetryDir" }
    & $python scripts/build_sebring_lico_validation_pack.py --verify-only --pack-dir $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Pack preflight failed.' }
    Write-Host 'Remain stationary in the car during launcher setup, before crossing start/finish; otherwise the first scored lap may be missed.'
    $lapProbe = @(& $python scripts/run_lmu_live_cues.py --show-current-lap)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the current LMU lap. Enter the Sebring LMP2 car and retry.' }
    $lapProbeText = $lapProbe -join [Environment]::NewLine
    Write-Host $lapProbeText
    if ($lapProbeText -notmatch 'absolute_lap_number=(?<lap>-?[0-9]+) lap_distance_m=(?<distance>-?[0-9]+(?:[.][0-9]+)?)') {
        throw 'Could not parse the current absolute LMU lap.'
    }
    $nextLap = [int]$Matches['lap'] + 1
    if ($null -eq $FirstScoredLap) {
        $FirstScoredLap = $nextLap
        Write-Host "FirstScoredLap auto-detected as $FirstScoredLap. Start before the next start/finish crossing."
    } elseif ($FirstScoredLap -lt $nextLap) {
        throw "FirstScoredLap=$FirstScoredLap is already in the past; use $nextLap or omit it."
    }
    $roles = @('push','A','B','push','B','A','push')
    $schedule = @(for ($i = 0; $i -lt 7; $i++) {
        $planId = ''
        if ($roles[$i] -ne 'push') { $planId = 'sebring_lmp2_static_' + $roles[$i] + '_v1' }
        [pscustomobject]@{scored_index=$i+1;lap_number=$FirstScoredLap+$i;role=$roles[$i];plan_id=$planId;cue_enabled=($roles[$i] -ne 'push');fuel_start_l='';cue_missed='';traffic_or_error='';notes=''}
    })
    $cueLaps = @($schedule | Where-Object cue_enabled | ForEach-Object lap_number)
    $sessionDir = Join-Path (Split-Path $PSScriptRoot -Parent) ('sessions/' + $RunId)
    if (Test-Path -LiteralPath $sessionDir) { throw 'Run directory already exists; choose a new RunId.' }
    New-Item -ItemType Directory -Path $sessionDir | Out-Null
    Get-ChildItem -LiteralPath $PSScriptRoot -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $sessionDir
    }
    $schedule | Export-Csv -LiteralPath (Join-Path $sessionDir 'lap_schedule.csv') -NoTypeInformation -Encoding UTF8
    $schedule | Where-Object cue_enabled | Select-Object lap_number,plan_id |
        Export-Csv -LiteralPath (Join-Path $sessionDir 'lap_plan_schedule.csv') -NoTypeInformation -Encoding UTF8
    $metadataPath = Join-Path $sessionDir 'run_metadata_template.json'
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    $metadata.run_id = $RunId
    $metadata.status = 'session_started'
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    $resolvedConfig = @{run_id=$RunId;first_scored_lap=$FirstScoredLap;scored_laps=7;lap_pattern=$roles;cue_laps=$cueLaps;expected_cue_count=28;stop_after_lap=$FirstScoredLap+6;emit_system_beep=$true;plan='plan.csv';lap_plan_schedule='lap_plan_schedule.csv';telemetry_log='telemetry.csv';adaptive_mode='offline_after_run_only'}
    $resolvedConfig | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sessionDir 'session_config.json') -Encoding UTF8
    Write-Host "RunId: $RunId"
    Write-Host "Session files: $sessionDir"
    $schedule | Format-Table
    Write-Host 'Sebring, same Oreca LMP2, 55 L, zero tire wear. ConfirmTelemetryRecording does not enable LMU telemetry.'
    Write-Host 'Expected audio: 7 zones x 4 LICO laps = 28 beeps. Pattern: push / A / B / push / B / A / push.'
    Write-Host 'At every beep: fully release the throttle, coast toward your normal braking point, then drive the corner normally. Always brake earlier if needed for safety.'
    $telemetryStartedAt = Get-Date
    $liveArgs = @('scripts/run_lmu_live_cues.py','--plan',(Join-Path $sessionDir 'plan.csv'),'--lap-plan-schedule',(Join-Path $sessionDir 'lap_plan_schedule.csv'),'--event-log',(Join-Path $sessionDir 'events.csv'),'--accuracy-log',(Join-Path $sessionDir 'events_accuracy.csv'),'--telemetry-log',(Join-Path $sessionDir 'telemetry.csv'),'--run-id',$RunId,'--stop-after-lap',($FirstScoredLap+6),'--cue-laps') + $cueLaps + @('--emit-system-beep')
    & $python @liveArgs
    if ($LASTEXITCODE -ne 0) { throw 'Live session exited with an error; preserve all session logs.' }
    $sessionComplete = $false
    $lastLapNumber = 0
    $telemetryLogPath = Join-Path $sessionDir 'telemetry.csv'
    if (Test-Path -LiteralPath $telemetryLogPath -PathType Leaf) {
        $lastSample = Import-Csv -LiteralPath $telemetryLogPath | Select-Object -Last 1
        if ($null -ne $lastSample -and [int]::TryParse([string]$lastSample.lap_number, [ref]$lastLapNumber)) {
            $sessionComplete = $lastLapNumber -gt ($FirstScoredLap + 6)
        }
    }
    $resolvedConfig['scored_block_completion_confirmed'] = $sessionComplete
    $resolvedConfig['last_logged_lap_number'] = $lastLapNumber
    $resolvedConfig | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sessionDir 'session_config.json') -Encoding UTF8
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    if ($sessionComplete) {
        $metadata.status = 'session_recorded_telemetry_pending_manual_link'
    } else {
        $metadata.status = 'session_incomplete_telemetry_pending_manual_link'
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    if ($sessionComplete) {
        Read-Host 'The 7 scored laps are complete. Return to the pits, stop/export LMU telemetry, then press Enter'
    } else {
        Write-Warning 'The scored block was interrupted or completion could not be confirmed from telemetry. Preserve the partial run for review.'
        Read-Host 'Incomplete session: return to the pits, stop/export LMU telemetry, then press Enter to link the partial recording'
    }
    $newTelemetry = @(Get-ChildItem -LiteralPath $TelemetryDir -Filter '*Sebring*.duckdb' -File |
        Where-Object LastWriteTime -ge $telemetryStartedAt.AddSeconds(-5))
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    if ($newTelemetry.Count -ne 1) {
        Write-Warning "Found $($newTelemetry.Count) updated Sebring .duckdb files. Link the correct file manually before analysis; no automatic selection made."
    } else {
        $metadata.telemetry_duckdb = $newTelemetry[0].FullName
        if ($sessionComplete) {
            $metadata.status = 'session_recorded_pending_lap_review'
        } else {
            $metadata.status = 'session_incomplete_pending_lap_review'
        }
        Write-Host "Linked LMU telemetry: $($newTelemetry[0].FullName)"
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    Write-Host "RunId: $RunId"
    Write-Host 'Give Codex the RunId, beep count, and any errors by lap/turn. Original telemetry files remain untouched.'
} finally { Pop-Location }
