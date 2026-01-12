
import os
import threading
import traceback
import joblib

# ---------------------------------------------------
# Debug info (runs once when file is imported)
# ---------------------------------------------------
print(f"[ml_engine] Imported from: {__file__}")
print(f"[ml_engine] MODEL PATH = {os.environ.get('MAILGUARD_MODEL_PATH')}")

# ---------------------------------------------------
# Global variables
# ---------------------------------------------------
MODEL_PATH = os.environ.get("MAILGUARD_MODEL_PATH")
_model = None                  # Cached model
_lock = threading.Lock()       # Thread safety


# ---------------------------------------------------
# Load model from disk
# ---------------------------------------------------
def _load_model_from_file(path: str):
    """
    Tries different loaders based on file type:
    - joblib (sklearn)
    - keras (.h5)
    - pytorch (.pt)
    """

    if not os.path.exists(path):
        print(f"[ml_engine] Model file not found: {path}")
        return None

    # Try joblib (sklearn pipeline)
    try:
        print(f"[ml_engine] Loading model using joblib: {path}")
        model = joblib.load(path)
        print(f"[ml_engine] Model loaded successfully: {type(model)}")
        return model
    except Exception as e:
        print("[ml_engine] joblib load failed")
        traceback.print_exc()

    # Try Keras model
    if path.endswith((".h5", ".keras")):
        try:
            from tensorflow.keras.models import load_model
            model = load_model(path)
            print("[ml_engine] Keras model loaded")
            return model
        except Exception:
            traceback.print_exc()

    # Try PyTorch model
    if path.endswith((".pt", ".pth")):
        try:
            import torch
            print("[ml_engine] PyTorch model detected (state dict only)")
            return {"pytorch_model_path": path}
        except Exception:
            traceback.print_exc()

    print("[ml_engine] No compatible loader found")
    return None


# Singleton model loader (thread safe)
def load_model():
    """
    Loads model once and reuses it for all requests.
    Prevents multiple loads using thread lock.
    """

    global _model

    with _lock:
        if _model is not None:
            print("[ml_engine] Using cached model")
            return _model

        if not MODEL_PATH:
            print("[ml_engine] MODEL PATH not set")
            return None

        try:
            _model = _load_model_from_file(MODEL_PATH)
            print(f"[ml_engine] Model ready: {type(_model)}")
        except Exception:
            traceback.print_exc()
            _model = None

        return _model


# ---------------------------------------------------
# Prediction API
# ---------------------------------------------------
def predict(text: str):
    """
    Main prediction function.

    Input:
        text -> email body (string)

    Output:
        {
          verdict: spam / benign 
          score: probability
          reasons: []
          model: sklearn / keras / stub
        }
    """

    print("[ml_engine] predict() called")

    model = _model or load_model()

    # ------------------------------------------------
    # Fallback logic (if model not loaded)
    # ------------------------------------------------
    if model is None:
        body = (text or "").lower()
        score = 0.0
        reasons = []

        if "click here" in body or "verify your account" in body:
            score += 0.5
            reasons.append("suspicious_phrases")

        if "http://" in body and "https://" not in body:
            score += 0.3
            reasons.append("insecure_link")

        if score > 0.5:
            verdict = "spam"
        else:
            verdict = "benign"

        return {
            "verdict": verdict,
            "score": round(score, 3),
            "reasons": reasons,
            "model": "rule_based"
        }

    # ------------------------------------------------
    # ML prediction
    # ------------------------------------------------
    try:

        # Case 1: Sklearn pipeline
        if hasattr(model, "predict_proba"):
            X = [text]
            probs = model.predict_proba(X)
            score = float(probs[0][-1])

            label = model.predict(X)[0]

            verdict = "spam" if int(label) == 1 else "benign"

            return {
                "verdict": verdict,
                "score": round(score, 3),
                "reasons": [],
                "model": "sklearn"
            }

        # Case 2: Keras model
        if hasattr(model, "predict"):
            X = [text]
            score = float(model.predict(X)[0])
            verdict = "spam" if score > 0.5 else "benign"

            return {
                "verdict": verdict,
                "score": round(score, 3),
                "reasons": [],
                "model": "keras"
            }

        # Unsupported model
        return {
            "verdict": "unknown",
            "score": 0.0,
            "reasons": ["unsupported_model"],
            "model": "unknown"
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "verdict": "benign",
            "score": 0.0,
            "reasons": ["model_runtime_error"],
            "model": "error_fallback"
        }
