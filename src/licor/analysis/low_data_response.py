"""Small non-negative development models; no live or calibrated-risk authority."""

from __future__ import annotations

import math
from dataclasses import dataclass

from licor.analysis.cross_circuit_ml import _nonnegative_two_feature_slopes

MODELS = (
    "action_only",
    "action_acceleration",
    "action_quadratic",
    "action_accel_quadratic",
)


def interaction(action: float, acceleration: float, model: str) -> float:
    if model not in MODELS:
        raise ValueError("unknown response model")
    if not math.isfinite(action) or action < 0 or not math.isfinite(acceleration):
        raise ValueError("finite non-negative action and finite acceleration required")
    if model == "action_only":
        return 0.0
    if model == "action_acceleration":
        return action * max(acceleration, 0.0)
    if model == "action_quadratic":
        return action**2
    # Acceleration is scaled by a fixed 1 m/s², not a transform fitted on test.
    return action**2 * (1.0 + max(acceleration, 0.0))


@dataclass(frozen=True)
class ResponseFit:
    model: str
    linear: float
    second: float

    def predict(self, action: float, acceleration: float) -> float:
        return self.linear * action + self.second * interaction(
            action, acceleration, self.model
        )


def fit_response(
    actions: list[float],
    accelerations: list[float],
    outcomes: list[float],
    *,
    model: str,
) -> ResponseFit:
    if not actions or not len(actions) == len(accelerations) == len(outcomes):
        raise ValueError("nonempty aligned response arrays required")
    if not all(math.isfinite(y) for y in outcomes):
        raise ValueError("finite outcomes required")
    second = [
        interaction(x, a, model) for x, a in zip(actions, accelerations, strict=True)
    ]
    if not any(x > 0 for x in actions):
        raise ValueError("positive action support required")
    fitted = _nonnegative_two_feature_slopes(actions, second, outcomes)
    if fitted is None:
        raise ValueError("positive action support required")
    return ResponseFit(model, *fitted)
