import pytest

from scripts.audit_hud_ocr import evaluate, parse_hud


def raw(race="1 / ~6.4", fuel="55.OL (19.8 laps)"):
    return {"race_lines": [race, "Tour", "Dernier"], "fuel_text": fuel}


def test_development_numeric_candidates_do_not_repair_ambiguous_context():
    result = parse_hud(raw("I / --6.4"))
    assert result["total_display"] == 6.4
    assert result["fuel_laps"] == 19.8
    assert result["lap_display"] is None
    assert result["estimated"] is None
    assert result["race_status"] == "candidate_ambiguous_context"
    assert not result["live_authorized"]


def test_clear_race_and_finish_formats():
    assert parse_hud(raw())["estimated"] is True
    result = parse_hud(raw("Tour 6 / 6"))
    assert result["total_display"] == 6
    assert result["lap_display"] == 6
    assert result["estimated"] is False


@pytest.mark.parametrize(
    "race", ["1 / ~64", "1 / --64", "1 / ~6.O", "6.4", "1 / 6.45", "1 / -6.4", "1 / 0"]
)
def test_bad_race_text_abstains(race):
    assert parse_hud(raw(race))["total_display"] is None


@pytest.mark.parametrize(
    "fuel",
    [
        "55.0L (198 laps)",
        "55.0L (19.O laps)",
        "19.8",
        "55.0L (19.8)",
        "55.0L (19.8 laps) 12.7",
        "",
    ],
)
def test_bad_fuel_text_abstains(fuel):
    assert parse_hud(raw(fuel=fuel))["fuel_laps"] is None


def test_missing_label_or_duplicate_race_candidates_abstain():
    assert parse_hud({"race_lines": ["1 / ~6.4"]})["total_display"] is None
    row = raw()
    row["race_lines"].append("2 / ~6.5")
    assert parse_hud(row)["total_display"] is None


def test_no_cross_frame_fill_or_future_repair():
    assert parse_hud(raw())["fuel_laps"] == 19.8
    assert parse_hud({})["fuel_laps"] is None
    assert parse_hud(raw(fuel="55.0L (18.4 laps)"))["fuel_laps"] == 18.4


def test_metrics_exclude_development_and_count_wrong_separately():
    labels = [
        dict(
            video_s=t,
            context="test",
            total_display=6.4,
            fuel_laps=19.8,
            lap_display=1,
            estimated=True,
        )
        for t in (35, 135, 246)
    ]
    readings = [
        dict(raw(), video_s=35),
        dict(raw(fuel="55.0L (19.7 laps)"), video_s=135),
        dict(video_s=246),
    ]
    _, summary = evaluate(readings, labels)
    assert summary["evaluation_frames"] == 2
    assert summary["fields"]["fuel_laps"]["correct"] == 0
    assert summary["fields"]["fuel_laps"]["wrong"] == 1
    assert summary["fields"]["fuel_laps"]["missing"] == 1
    assert summary["both_targets_correct"] == 0


def test_incomplete_or_duplicate_evaluation_fails():
    with pytest.raises(ValueError, match="match exactly"):
        evaluate([], [{"video_s": 135}])
    with pytest.raises(ValueError, match="Duplicate OCR"):
        evaluate([{"video_s": 35}, {"video_s": 35}], [])
    with pytest.raises(ValueError, match="Duplicate reference"):
        evaluate([], [{"video_s": 35}, {"video_s": 35}])


def test_v2_ignores_liters_but_never_repairs_target_digits():
    row = dict(raw("Tour 1 / -6.4", "S3.8L (19.4 laps)"), reader="windows_ocr_en-US_v2")
    result = parse_hud(row)
    assert result["total_display"] == 6.4
    assert result["estimated"] is None
    assert result["fuel_laps"] == 19.4
    row["fuel_text"] = "45.21 (1 s.8 laps)"
    assert parse_hud(row)["fuel_laps"] is None


@pytest.mark.parametrize("marker", ["—", "&", "*0"])
def test_v2_keeps_frozen_abstention_for_unseen_markers(marker):
    row = dict(raw(f"Tour 1 / {marker}6.4"), reader="windows_ocr_en-US_v2")
    assert parse_hud(row)["total_display"] is None


def test_absent_controls_not_counted_as_visible_read_accuracy():
    labels = [
        dict(
            video_s=1,
            context="absent",
            total_display=None,
            fuel_laps=None,
            lap_display=None,
            estimated=None,
        )
    ]
    _, summary = evaluate([dict(video_s=1)], labels)
    assert summary["fields"]["fuel_laps"]["correct_absent"] == 1
    assert summary["fields"]["fuel_laps"]["visible_frames"] == 0
    assert summary["both_targets_correct"] == 0
    _, summary = evaluate([dict(raw(), video_s=1)], labels)
    assert summary["fields"]["fuel_laps"]["false_positive"] == 1
