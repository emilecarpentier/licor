-- Frozen V2, same-video evaluation only. Absent controls excluded from visible denominator.
WITH evidence AS (
    SELECT * FROM read_json_auto('data/processed/experimental/hud_ocr_v2/audit/rows.json')
    WHERE split = 'evaluation_same_video'
)
SELECT 'Total de course' AS champ,
    count(*) FILTER (WHERE total_display_result = 'correct') AS correct,
    count(*) FILTER (WHERE total_display_result = 'missing') AS missing,
    count(*) FILTER (WHERE total_display_result = 'wrong') AS wrong,
    count(expected_total_display) AS visible,
    count(*) FILTER (WHERE expected_total_display IS NULL) AS absent_controls,
    count(*) FILTER (WHERE total_display_result = 'false_positive') AS false_positive,
    'v2' AS reader, 'same_video_holdout' AS split
FROM evidence
UNION ALL
SELECT 'Autonomie en tours',
    count(*) FILTER (WHERE fuel_laps_result = 'correct'),
    count(*) FILTER (WHERE fuel_laps_result = 'missing'),
    count(*) FILTER (WHERE fuel_laps_result = 'wrong'),
    count(expected_fuel_laps),
    count(*) FILTER (WHERE expected_fuel_laps IS NULL),
    count(*) FILTER (WHERE fuel_laps_result = 'false_positive'),
    'v2', 'same_video_holdout'
FROM evidence;
