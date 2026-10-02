param([double]$DurationMinutes = 30, [switch]$Doctor)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python LICOR introuvable : $Python"
}
Push-Location $ProjectRoot
try {
    if ($Doctor) {
        & $Python 'scripts\run_lmu_live_cues.py' --doctor
    } else {
        & $Python 'scripts\capture_lmu_race.py' --duration-minutes $DurationMinutes
    }
    $CaptureExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $CaptureExitCode
