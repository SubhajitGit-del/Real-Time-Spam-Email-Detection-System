# api/predictor.py
"""
MailGuard predictor utilities.

This module handles:
- Cleaning and normalising raw email text
- Tokenising + lemmatising using NLTK
- Building both TF-IDF features (text) and simple numeric features
- Wrapping a trained model into a convenient `MailGuardPredictor` class
"""

import re
from html import unescape

import numpy as np
from scipy.sparse import csr_matrix, hstack

# NLTK imports
import nltk  # noqa: F401  # imported to ensure resources are available
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

# Pre-load NLTK assets
STOPWORDS = set(stopwords.words("english"))
LEMMATIZER = WordNetLemmatizer()

# -------------------------------------------------------------------------
# Text normalisation helpers
# -------------------------------------------------------------------------

# Handle bad encodings / mojibake often seen in email bodies
MOJIBAKE_REPLACEMENTS = {
    "ΓÇó": "-",
    "ΓÇô": "-",
    "ΓÇ£": '"',
    "ΓÇ¥": '"',
    "ΓÇÖ": "'",
    "ΓÇü": "u",
    "â": "-",
    "â": "-",
    "â": '"',
    "â": "'",
    "â¢": "-",
    "Ã©": "e",
    "\ufeff": "",
}
MOJIBAKE_REGEX = re.compile(
    "|".join(re.escape(k) for k in MOJIBAKE_REPLACEMENTS.keys())
)

# Simple regexes for common email patterns
URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{7,}\d)")
IMAGE_PLACEHOLDER_RE = re.compile(r"\[image:[^\]]*\]", flags=re.IGNORECASE)

# Markers that often indicate forwarded/quoted content
FORWARD_MARKERS = [
    "forwarded message",
    "---------- forwarded message",
    "from:",
]


def fix_mojibake(text: str) -> str:
    """Replace common mojibake artefacts with more readable characters."""
    if not text:
        return text
    return MOJIBAKE_REGEX.sub(
        lambda m: MOJIBAKE_REPLACEMENTS[m.group(0)], text
    )


def clean_text(raw: str) -> str:
    """
    Normalise raw email text into a cleaner, lower-cased version.

    Steps:
      - Fix mojibake
      - Decode HTML entities
      - Strip forwarded/quoted sections after common markers
      - Replace URLs/emails/phones/images with generic tokens
      - Remove leftover HTML tags and collapse whitespace
    """
    if raw is None:
        return ""

    text = str(raw)

    # Fix encoding artefacts and HTML entities
    text = fix_mojibake(text)
    text = unescape(text)

    # Remove forwarded/quoted portion (keep only the top part)
    lower = text.lower()
    for marker in FORWARD_MARKERS:
        idx = lower.find(marker)
        if idx != -1:
            text = text[:idx]
            lower = text.lower()
            break

    # Replace common patterns with placeholders
    text = URL_RE.sub(" <URL> ", text)
    text = EMAIL_RE.sub(" <EMAIL> ", text)
    text = PHONE_RE.sub(" <PHONE> ", text)
    text = IMAGE_PLACEHOLDER_RE.sub(" <IMAGE> ", text)

    # Drop any remaining HTML tags and tidy whitespace
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text.lower()


def tokenize_and_lemmatize(text: str) -> str:
    """
    Tokenise text, remove stopwords and non-alphabetic tokens,
    and lemmatise the remaining words.
    """
    tokens = word_tokenize(text)
    processed = [
        LEMMATIZER.lemmatize(tok)
        for tok in tokens
        if tok.isalpha() and tok not in STOPWORDS
    ]
    return " ".join(processed)


def extract_structured_features_from_texts(texts):
    """
    Build simple numeric features from text, such as:
      - number of URLs
      - number of email addresses
      - presence of image markers
      - text length

    Returns a dense numpy array of shape (n_samples, n_features).
    """
    import pandas as pd

    series = pd.Series(texts).fillna("")

    n_urls = series.str.count(URL_RE.pattern).fillna(0).astype(int)
    n_emails = series.str.count(EMAIL_RE.pattern).fillna(0).astype(int)
    has_image = (
        series.str.contains(r"\[image:|<image>", case=False, regex=True)
        .fillna(False)
        .astype(int)
    )
    text_len = series.map(len).astype(int)

    features = np.vstack(
        [n_urls.values, n_emails.values, has_image.values, text_len.values]
    ).T

    return features


# -------------------------------------------------------------------------
# Model wrapper
# -------------------------------------------------------------------------


class MailGuardPredictor:
    """
    Lightweight wrapper around the trained pipeline.

    It accepts raw email texts and:
      - Cleans and lemmatises them
      - Builds TF-IDF features for text
      - Builds and scales numeric features
      - Concatenates both into a single feature matrix
      - Delegates to the underlying model's predict / predict_proba
    """

    def __init__(self, tfidf, scaler, model, metadata=None):
        self.tfidf = tfidf
        self.scaler = scaler
        self.model = model
        self.metadata = metadata or {}

    def _prepare(self, raw_texts):
        """Internal helper: full preprocessing pipeline."""
        cleaned = [clean_text(text) for text in raw_texts]
        lemmatised = [tokenize_and_lemmatize(text) for text in cleaned]

        # Text features
        X_text = self.tfidf.transform(lemmatised)

        # Simple numeric features
        X_num = extract_structured_features_from_texts(cleaned)
        X_num_scaled = self.scaler.transform(X_num)
        X_num_sparse = csr_matrix(X_num_scaled)

        # Final feature matrix: [TF-IDF | numeric]
        X_final = hstack([X_text, X_num_sparse])

        return X_final, cleaned, lemmatised

    def predict_proba(self, raw_texts):
        """
        Return probabilities for each class, similar to sklearn's predict_proba.
        Assumes column 1 (or the last column) corresponds to "spam".
        """
        X_final, _, _ = self._prepare(raw_texts)

        # If the underlying model exposes predict_proba, just use it
        if hasattr(self.model, "predict_proba"):
            return self.model.predict_proba(X_final)

        # Fallback: handle models that only implement predict()
        preds = self.model.predict(X_final)
        try:
            # Interpret preds as 0/1 and build a 2-column probability array
            preds = preds.astype(float)
            return np.vstack([1 - preds, preds]).T
        except Exception:
            # As a very last resort, return zeros
            return np.zeros((len(preds), 2))

    def predict(self, raw_texts):
        """
        Return a 0/1 prediction by thresholding spam probability at 0.5.
        """
        probs = self.predict_proba(raw_texts)
        # Take the last column as "spam" probability
        return (probs[:, -1] >= 0.5).astype(int)

