-- Run with DuckDB from the LICOR repository root. Read-only chart source.
WITH raw AS (
    SELECT * FROM read_json_auto(
        'data/processed/experimental/native_race_capture/race_20261002_011124_945002/samples.jsonl',
        format='newline_delimited'
    )
), bounds AS (
    SELECT
        arg_min(player.lap_start_s, capture_elapsed_s)
            FILTER (WHERE game_phase = 5 AND in_realtime) AS green_s,
        min(capture_elapsed_s)
            FILTER (WHERE player.finish_status = 1) AS finish_s
    FROM raw
), active AS (
    SELECT raw.*, bounds.green_s,
        row_number() OVER (ORDER BY capture_elapsed_s) - 1 AS sample_no
    FROM raw CROSS JOIN bounds
    WHERE in_realtime AND game_phase IN (3,5,8)
        AND capture_elapsed_s <= bounds.finish_s
)
SELECT round(player.telemetry_elapsed_s - green_s, 3) AS race_elapsed_s,
    player.fuel_l AS fuel_l,
    player.completed_laps AS completed_laps,
    game_phase AS phase,
    session_time_remaining_s AS remaining_time_s,
    player.finish_status AS finish_status
FROM active WHERE sample_no % 25 = 0
ORDER BY capture_elapsed_s;
