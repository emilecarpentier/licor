WITH passes AS (
 SELECT * FROM read_csv_auto('data/processed/experimental/sebring_lmp2_transfer_2026_09/combined_lico_analysis_final/zone_passes.csv')
), reference AS (
 SELECT zone_id, median(fuel_used_l) AS push_fuel_l, median(elapsed_time_s) AS push_time_s
 FROM passes WHERE cohort = 'prior_push' AND role = 'push' AND quality_ok GROUP BY zone_id
)
SELECT p.run_id, p.lap_number, p.role, p.cohort, p.zone_id, p.display_label,
 p.driver_review_pending, p.start_driver_throttle_pct,
 r.push_fuel_l - p.fuel_used_l AS fuel_saved_l,
 p.elapsed_time_s - r.push_time_s AS time_lost_s
FROM passes p JOIN reference r USING (zone_id)
WHERE p.role IN ('A','B') AND p.quality_ok
ORDER BY p.run_id, p.lap_number, p.zone_id
