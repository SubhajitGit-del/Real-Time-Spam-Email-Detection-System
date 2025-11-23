
# api/decision.py
"""
Decision logic for the ML-only mode.

Takes the raw ML probability score (0–1) and maps it into a final verdict:
    - spam
    - suspicious
    - benign

Also attaches simple confidence annotations so the UI/backend
understands *how* confident the model was.
"""

from typing import Any, Dict


def _clamp(value: float, low: float = 0.0, high: 1.0) -> float:
    """Ensure a number stays within the range [low, high]."""
    try:
        v = float(value)
    except Exception:
        return low
    return max(low, min(high, v))


def decide_ml_only(ml_score: float) -> Dict[str, Any]:
    """
    Convert a raw ML probability into:
        - final verdict: spam / suspicious / benign
        - rounded score
        - confidence reasons
        - a components dict for debugging/tracing

    Inputs:
        ml_score: probability that the email is spam (0.0–1.0)

    Returns:
        {
          "verdict": "...",
          "score": float,
          "reasons": [...],
          "components": {"ml_score": ...}
        }
    """
    score = _clamp(ml_score)
    reasons = []

    # Add simple confidence tags based on score ranges
    if score >= 0.98:
        reasons.append("ml_high_confidence")
    elif score >= 0.7:
        reasons.append("ml_strong")
    elif score >= 0.45:
        reasons.append("ml_weak")

    # Final label thresholds
    if score >= 0.7:
        verdict = "spam"
    elif score >= 0.4:
        verdict = "suspicious"
    else:
        verdict = "benign"

    return {
        "verdict": verdict,
        "score": round(score, 3),
        "reasons": reasons,
        "components": {"ml_score": round(score, 3)},
    }
