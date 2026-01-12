# api/decision.py
from typing import Dict, Any


def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """
    Keeps a number safely inside a given range.
    Default range = [0, 1]
    """
    try:
        value = float(value)
    except Exception:
        return min_val

    return max(min_val, min(value, max_val))


def decide_ml_only(ml_score: float) -> Dict[str, Any]:
    """
    Converts ML probability score into final verdict.

    Input:
        ml_score -> probability from ML model (0 to 1)

    Output:
        {
            verdict   : spam / benign
            score     : rounded ML score
            reasons   : confidence indicators
            components: raw score
        }
    """

    score = _clamp(ml_score)
    reasons = []

    # Decision thresholds
    if score >= 0.5:
        verdict = "spam"
    else:
        verdict = "benign"

    return {
        "verdict": verdict,
        "score": round(score, 3),
        "reasons": reasons,
        "components": {
            "ml_score": round(score, 3)
        },
    }


