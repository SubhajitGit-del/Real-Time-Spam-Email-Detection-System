"""
MailGuard ML Engine
-------------------
Responsible for loading the trained model (TF-IDF + scaler + classifier)
and exposing a single, simple interface:

    predict(text) -> { verdict, score, reasons }

The Chrome extension and Django view only interact with this module.
"""

import os
import threading
import traceback
import joblib

# Debug info on import
print(f"[ml_engine] Loaded from: {__file__}")
print(f"[ml_engine] Model path env = {os.environ.get('MAILGUARD_MODEL_PATH')}")

# ---------------------------------------------------------------------
# Global model pointer + thread-safe lock
# ---------------------------------------------------------------------
MODEL_PATH = os.environ.get("MAILGUARD_MODEL_PATH")
_model = None
_lock = threading.Lock()


# ---------------------------------------------------------------------
# File loader with fallbacks
# ---------------------------------------------------------------------
def _load_model_from_file(path: str):
    """Try loading the model using joblib, then optionally Keras, then PyTorch."""
    if not os.path.exists(path):
        print(f"[ml_engine] Path does not exist: {path}")
        return None

    # Try joblib first (main format for sklearn pipelines)
    try:
        print(f"[ml_engine] Attempting joblib.load({path})")
        model = joblib.load(path)
        print(f"[ml_engine] joblib load OK: {type(model)}")
        return model
    except Exception as exc:
        print(f"[ml_engine] joblib failed: {exc}")
        traceback.print_exc()

    # Optional: TensorFlow/Keras format
    if path.endswith((".h5", ".keras")):
        try:
            from tensorflow.keras.models import load_model
            model = load_model(path)
            print("[ml_engine] Loaded Keras model")
            return model
        except Exception as exc:
            print(f"[ml_engine] Keras load failed: {exc}")

    # Optional: PyTorch checkpoint
    if path.endswith((".pt", ".pth")):
        try:
            print("[ml_engine] Treating file as PyTorch state dict reference only.")
            return {"pytorch_state_dict_path": path}
        except Exception as exc:
            print(f"[ml_engine] PyTorch load failed: {exc}")

    print("[ml_engine] No loader succeeded.")
    return None


# ---------------------------------------------------------------------
# One-time model loader (thread-safe)
# ---------------------------------------------------------------------
def load_model():
    global _model

    with _lock:
        print(f"[ml_engine] load_model() called. MODEL_PATH = {MODEL_PATH}")

        if _model is not None:
            print("[ml_engine] Using cached model instance.")
            return _model

        if not MODEL_PATH:
            print("[ml_engine] Warning: MAILGUARD_MODEL_PATH not configured.")
            return None

        if not os.path.exists(MODEL_PATH):
            print(f"[ml_engine] File not found: {MODEL_PATH}")
            return None

        try:
            _model = _load_model_from_file(MODEL_PATH)
            print(f"[ml_engine] Model loaded successfully: {type(_model)}")
        except Exception:
            traceback.print_exc()
            _model = None

        return _model


# ---------------------------------------------------------------------
# Public prediction API
# ---------------------------------------------------------------------
def predict(text):
    """
    Accepts a raw email body string and returns a dict:

        {
           "verdict": "spam" | "benign" | "suspicious",
           "score": float,
           "reasons": [...],
           "model": "sklearn" | "keras" | "stub"
        }

    If no model is available, we fall back to a simple rule-based heuristic.
    """
    print(f"[ml_engine] predict() invoked. Current model = {type(_model)}")

    model = _model or load_model()
    print(f"[ml_engine] After ensuring load: {type(model)}")

    # -----------------------------------------------------------------
    # Fallback heuristic (if model missing / load failed)
    # -----------------------------------------------------------------
    if model is None:
        body = (text or "").lower()
        reasons = []
        score = 0.0

        # Very rough heuristic using spam keywords
        if "click here" in body or "verify your account" in body or "password" in body:
            reasons.append("suspicious_phrases")
            score += 0.5

        # Unsecured HTTP links
        if "http://" in body and "https://" not in body:
            reasons.append("insecure_http_link")
            score += 0.3

        verdict = "benign"
        if score > 0.6:
            verdict = "spam"
        elif score > 0.25:
            verdict = "suspicious"

        print(f"[ml_engine] Using fallback rule: verdict={verdict}, score={score}")
        return {
            "verdict": verdict,
            "score": round(score, 3),
            "reasons": reasons,
            "model": "stub",
        }

    # -----------------------------------------------------------------
    # Sklearn / Pipeline case
    # -----------------------------------------------------------------
    try:
        if hasattr(model, "predict_proba"):
            X = [text]
            probs = model.predict_proba(X)
            score = float(probs[0][-1])  # spam probability

            # Try to get predicted label
            try:
                label = model.predict(X)[0]
            except Exception:
                label = None

            # Normalise label types
            if isinstance(label, (int, float)) or str(label).isdigit():
                label = int(label)
                verdict = "spam" if label == 1 else "benign"
            else:
                verdict = str(label).lower()
                if verdict not in {"spam", "benign", "suspicious"}:
                    verdict = "spam" if score > 0.5 else "benign"

            print(f"[ml_engine] sklearn predict_proba → verdict={verdict}, score={score}")
            return {
                "verdict": verdict,
                "score": round(score, 3),
                "reasons": [],
                "model": "sklearn",
            }

        # -----------------------------------------------------------------
        # Keras-like model
        # -----------------------------------------------------------------
        if hasattr(model, "predict"):
            X = [text]
            score = float(model.predict(X)[0].squeeze())
            verdict = "spam" if score > 0.5 else "benign"

            print(f"[ml_engine] Keras predict → verdict={verdict}, score={score}")
            return {
                "verdict": verdict,
                "score": round(score, 3),
                "reasons": [],
                "model": "keras",
            }

        # -----------------------------------------------------------------
        # Unknown model interface
        # -----------------------------------------------------------------
        print("[ml_engine] Warning: model loaded but unsupported predict interface.")
        return {
            "verdict": "unknown",
            "score": 0.0,
            "reasons": ["model_loaded_but_unhandled"],
            "model": "unknown",
        }

    except Exception as exc:
        print(f"[ml_engine] Prediction error: {exc}")
        traceback.print_exc()
        return {
            "verdict": "benign",
            "score": 0.0,
            "reasons": [f"model_error:{str(exc)[:200]}"],
            "model": "error_fallback",
        }
