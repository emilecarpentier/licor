import math

import pytest

from licor.analysis.low_data_response import MODELS, fit_response, interaction


@pytest.mark.parametrize("model", MODELS)
def test_nonnegative_zero_origin_and_monotone_at_fixed_acceleration(model):
    fit = fit_response(
        [0.1, 0.2, 0.4, 0.6], [1, 2, 1, 2], [-0.02, 0.03, 0.1, 0.2], model=model
    )
    predictions = [fit.predict(i / 100, 1.5) for i in range(101)]
    assert fit.linear >= 0 and fit.second >= 0
    assert predictions[0] == 0
    assert predictions == sorted(predictions)


def test_quadratic_recovers_known_curve():
    x = [0.1, 0.2, 0.4, 0.6]
    fit = fit_response(
        x, [1] * 4, [0.2 * v + 0.4 * v**2 for v in x], model="action_quadratic"
    )
    assert fit.linear == pytest.approx(0.2)
    assert fit.second == pytest.approx(0.4)


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1])
def test_invalid_action_rejected(value):
    with pytest.raises(ValueError):
        interaction(value, 1, "action_only")


def test_invalid_alignment_and_outcome_rejected():
    with pytest.raises(ValueError, match="positive action support"):
        fit_response([0.0], [1.0], [2.0], model="action_only")
    with pytest.raises(ValueError):
        fit_response([1], [], [1], model="action_only")
    with pytest.raises(ValueError):
        fit_response([1], [1], [math.nan], model="action_only")
