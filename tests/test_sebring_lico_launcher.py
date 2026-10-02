from pathlib import Path


def test_launcher_preserves_schedule_and_checks_actual_completion():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/templates/sebring_lico_validation.ps1").read_text()
    assert "@('push','A','B','push','B','A','push')" in script
    assert "--lap-plan-schedule" in script
    assert "(Join-Path $sessionDir 'plan.csv')" in script
    assert "$lastLapNumber -gt ($FirstScoredLap + 6)" in script
    assert "session_incomplete_pending_lap_review" in script
    assert "if ($sessionComplete)" in script
    assert "$newTelemetry.Count -ne 1" in script
    assert "Remove-Item" not in script
