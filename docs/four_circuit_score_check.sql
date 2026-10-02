-- Run from the repository root. Independent recomputation from predictions,
-- not a SELECT from the builder's precomputed metric tables.
SELECT held_out_circuit AS circuit, target, model, count(*) AS n,
       avg(abs(predicted - actual)) AS mae,
       sqrt(avg(pow(predicted - actual, 2))) AS rmse,
       avg(predicted - actual) AS bias,
       avg(abs(actual)) AS zero_mae
FROM read_csv_auto('data/processed/experimental/four_circuit_low_data_v1/loco_strict_predictions.csv')
GROUP BY ALL ORDER BY target, model, circuit;

SELECT target, budget_laps, model, count(*) AS n,
       avg(abs(predicted - actual)) AS mae,
       sqrt(avg(pow(predicted - actual, 2))) AS rmse,
       avg(predicted - actual) AS bias
FROM read_csv_auto('data/processed/experimental/four_circuit_low_data_v1/few_lap_predictions.csv')
GROUP BY ALL ORDER BY target, budget_laps, model;
