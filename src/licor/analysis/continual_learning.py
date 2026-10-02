"""Bounded local response updates for offline, predict-before-update replays.

This is not a cue controller or a calibrated uncertainty model. Context changes
require a fresh state; snapshots are immutable so an update can be rolled back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from licor.analysis.low_data_response import ResponseFit

PRIOR_EQUIVALENT_PASSES = 2.0
MAX_RATIO_RESIDUAL = 0.5
MAX_SCALE_STEP = 0.1
MIN_SCALE = 0.5
MAX_SCALE = 1.5


@dataclass(frozen=True)
class Support:
    """Marginal training bounds, not evidence of joint or local coverage."""

    action_min: float
    action_max: float
    acceleration_min: float
    acceleration_max: float

    def __post_init__(self) -> None:
        values = (
            self.action_min,
            self.action_max,
            self.acceleration_min,
            self.acceleration_max,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("finite support bounds required")
        if not 0 <= self.action_min <= self.action_max:
            raise ValueError("ordered non-negative action bounds required")
        if self.acceleration_min > self.acceleration_max:
            raise ValueError("ordered acceleration bounds required")


@dataclass(frozen=True)
class LocalResponse:
    prior: ResponseFit
    support: Support
    context_id: str
    scale: float = 1.0
    accepted_count: int = 0

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("explicit context identity required")
        if not math.isfinite(self.scale) or not MIN_SCALE <= self.scale <= MAX_SCALE:
            raise ValueError("local scale outside fixed bounds")
        if type(self.accepted_count) is not int or self.accepted_count < 0:
            raise ValueError("non-negative integer evidence count required")
        if not all(
            math.isfinite(value) and value >= 0
            for value in (self.prior.linear, self.prior.second)
        ):
            raise ValueError("finite non-negative prior coefficients required")
        self.prior.predict(0.0, 0.0)  # Validate the prior's model name.


@dataclass(frozen=True)
class Update:
    prior_prediction: float | None
    prediction: float | None
    reason: str
    before: LocalResponse
    after: LocalResponse


def observe(
    state: LocalResponse,
    *,
    context_id: str,
    action: float,
    acceleration: float,
    outcome: float | None,
    quality_ok: bool,
) -> Update:
    """Predict with old state, then learn from one independently qualified target.

    Keep separate states for fuel and time, and for each zone. The action is the
    executed action in a retrospective replay, NOT a pre-cue prediction. Negative
    outcomes are retained as observations; only their influence is bounded.
    Evidence counts are passages, not independent laps or confidence levels.
    """
    if context_id != state.context_id:
        raise ValueError("context changed: initialize a fresh local state")
    if not math.isfinite(action) or action < 0 or not math.isfinite(acceleration):
        raise ValueError("finite non-negative action and finite acceleration required")
    if type(quality_ok) is not bool:
        raise ValueError("explicit boolean quality gate required")

    def unchanged(reason: str, prior: float | None = None) -> Update:
        prediction = None if prior is None else state.scale * prior
        if prediction is not None and not math.isfinite(prediction):
            raise ValueError("non-finite adapted prediction")
        return Update(prior, prediction, reason, state, state)

    if action == 0:
        return unchanged("zero_action", 0.0)
    if not state.support.action_min <= action <= state.support.action_max:
        return unchanged("unsupported_action")
    if not (
        state.support.acceleration_min <= acceleration <= state.support.acceleration_max
    ):
        return unchanged("unsupported_acceleration")
    prior = state.prior.predict(action, acceleration)
    if not math.isfinite(prior):
        raise ValueError("non-finite prior prediction")
    if prior == 0:
        return unchanged("zero_prior", prior)
    # These predictions cannot depend on the outcome supplied below.
    prediction = state.scale * prior
    if not math.isfinite(prediction):
        raise ValueError("non-finite adapted prediction")
    if not quality_ok:
        return unchanged("quality_rejected", prior)
    if outcome is None or not math.isfinite(outcome):
        return unchanged("missing_outcome", prior)
    residual = max(
        -MAX_RATIO_RESIDUAL,
        min(MAX_RATIO_RESIDUAL, outcome / prior - state.scale),
    )
    step = residual / (PRIOR_EQUIVALENT_PASSES + state.accepted_count + 1)
    step = max(-MAX_SCALE_STEP, min(MAX_SCALE_STEP, step))
    scale = max(MIN_SCALE, min(MAX_SCALE, state.scale + step))
    after = replace(state, scale=scale, accepted_count=state.accepted_count + 1)
    return Update(prior, prediction, "updated", state, after)
