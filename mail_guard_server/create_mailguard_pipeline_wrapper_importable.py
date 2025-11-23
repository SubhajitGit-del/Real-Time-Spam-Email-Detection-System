# create_mailguard_pipeline_wrapper_importable.py
"""
This script bundles the TF-IDF vectorizer, the numeric-feature scaler,
and the trained classifier into a single importable predictor object.
The result is saved as `mailguard_pipeline.joblib` so the Django backend
can load everything with one joblib.load() call.
"""

from pathlib import Path
import json
import joblib

from api.predictor import MailGuardPredictor

# Path to the directory where all training artifacts were saved
ARTIFACTS_DIR = Path(
    r"F:\Projects\MailGuard_Research_notebooks\mailguard\model\artifacts"
)

# Load each part of the ML pipeline
tfidf = joblib.load(ARTIFACTS_DIR / "tfidf.joblib")
scaler = joblib.load(ARTIFACTS_DIR / "scaler.joblib")
model = joblib.load(ARTIFACTS_DIR / "model_logreg.joblib")

# Metadata file is optional (e.g., training stats, parameters)
try:
    meta = json.loads((ARTIFACTS_DIR / "metadata.json").read_text("utf-8"))
except Exception:
    meta = {}

# Wrap everything into a single predictor object
predictor = MailGuardPredictor(
    tfidf=tfidf,
    scaler=scaler,
    model=model,
    metadata=meta,
)

# Save as a single importable pipeline file
output_path = ARTIFACTS_DIR / "mailguard_pipeline.joblib"
joblib.dump(predictor, output_path)

print("Created unified ML pipeline:", output_path)
