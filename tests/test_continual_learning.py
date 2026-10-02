import math
from dataclasses import FrozenInstanceError, replace

import pytest

from licor.analysis.continual_learning import LocalResponse, Support, observe
from licor.analysis.low_data_response import ResponseFit


def initial():
    return LocalResponse(
        ResponseFit("action_acceleration", 0.1, 0.02),
        Support(0.1, 1.5, 0.0, 5.0),
        "sebring:lmp2:dry:v1",
    )


def passage(state, **overrides):
    args = dict(
        context_id=state.context_id,
        action=0.5,
        acceleration=2.0,
        outcome=0.09,
        quality_ok=True,
    )
    args.update(overrides)
    return observe(state, **args)


def test_prediction_precedes_current_outcome_and_state_is_immutable():
    state = initial()
    low = passage(state, outcome=-50.0)
    high = passage(state, outcome=50.0)
    assert low.prediction == high.prediction == pytest.approx(0.07)
    assert low.after.scale == pytest.approx(0.9)
    assert high.after.scale == pytest.approx(1.1)
    assert state.accepted_count == 0
    with pytest.raises(FrozenInstanceError):
        state.scale = 2


def test_acceleration_changes_prior_and_action_zero_is_not_local_evidence():
    assert passage(initial(), acceleration=4).prediction > passage(initial()).prediction
    step = passage(initial(), action=0)
    assert step.prediction == 0
    assert step.reason == "zero_action"
    assert step.before == step.after


@pytest.mark.parametrize("outcome", [None, math.nan, math.inf, -math.inf])
def test_missing_target_never_updates(outcome):
    step = passage(initial(), outcome=outcome)
    assert step.reason == "missing_outcome"
    assert step.after == step.before


def test_quality_gate_blocks_even_finite_extreme_outcome():
    step = passage(initial(), outcome=1e100, quality_ok=False)
    assert step.reason == "quality_rejected"
    assert step.after == step.before
    assert step.prediction is not None


def test_targets_can_be_qualified_independently_without_sharing_state():
    fuel = passage(initial(), quality_ok=True)
    time = passage(initial(), quality_ok=False)
    assert fuel.after.accepted_count == 1
    assert time.after.accepted_count == 0


@pytest.mark.parametrize(
    "args,reason",
    [
        ({"action": 0.09}, "unsupported_action"),
        ({"action": 1.51}, "unsupported_action"),
        ({"acceleration": 5.1}, "unsupported_acceleration"),
    ],
)
def test_out_of_support_abstains_not_clips(args, reason):
    step = passage(initial(), **args)
    assert step.reason == reason
    assert step.prediction is None
    assert step.after == step.before


def test_context_change_requires_explicit_reset():
    with pytest.raises(ValueError, match="context changed"):
        passage(initial(), context_id="wet")
    assert passage(replace(initial(), context_id="wet")).before.accepted_count == 0


@pytest.mark.parametrize("outcome", [-1e100, 1e100])
def test_updates_bounded_and_replay_reproducible(outcome):
    state = initial()
    for _ in range(200):
        step = passage(state, outcome=outcome)
        assert abs(step.after.scale - state.scale) <= 0.100000000000001
        assert 0.5 <= step.after.scale <= 1.5
        assert step == passage(state, outcome=outcome)
        state = step.after
    assert state.accepted_count == 200


def test_zero_prior_remains_unknown_to_multiplicative_learner():
    step = passage(replace(initial(), prior=ResponseFit("action_only", 0, 0)))
    assert step.reason == "zero_prior"
    assert step.after.accepted_count == 0


@pytest.mark.parametrize(
    "args",
    [
        {"action": -1},
        {"action": math.nan},
        {"acceleration": math.inf},
        {"quality_ok": "yes"},
    ],
)
def test_invalid_passage_rejected(args):
    with pytest.raises(ValueError):
        passage(initial(), **args)


@pytest.mark.parametrize(
    "args",
    [
        {"accepted_count": -1},
        {"scale": 1.6},
        {"context_id": ""},
        {"accepted_count": 1.5},
    ],
)
def test_invalid_state_rejected(args):
    with pytest.raises(ValueError):
        replace(initial(), **args)


def test_invalid_support_and_prior_rejected():
    with pytest.raises(ValueError):
        Support(1, 0, 0, 5)
    with pytest.raises(ValueError):
        Support(0, 1, 5, 0)
    with pytest.raises(ValueError):
        Support(0, math.inf, 0, 5)
    with pytest.raises(ValueError):
        replace(initial(), prior=ResponseFit("action_only", -1, 0))


def test_adapted_prediction_overflow_rejected():
    state = replace(initial(), prior=ResponseFit("action_only", 1e308, 0), scale=1.5)
    with pytest.raises(ValueError, match="non-finite adapted"):
        passage(state, action=1.5)
