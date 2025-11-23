

# api/views.py
import os
import base64

from django.conf import settings
from django.utils import timezone
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import AnalyzeEmailSerializer
from .models import EmailRecord
from . import ml_engine
from .url_blocklist import assess_urls

print("[views.py] MailGuard API loaded (ML + URL blocklist)")

# Where we store any downloaded attachments (if provided)
ATTACH_DIR = getattr(
    settings,
    "ATTACH_DIR",
    os.path.join(settings.BASE_DIR, "attachments"),
)


class AnalyzeEmailView(APIView):
  """
  Simple REST endpoint used by the Chrome extension.

  It combines:
    - URL blocklist checks (malicious/benign domains)
    - Text-based ML model for spam scoring

  High-level logic:
    1) If any URL host is clearly malicious -> mark as spam, skip ML.
    2) If any URL host is known benign -> still run ML but discount the risk.
    3) Otherwise -> rely fully on the ML score.

  Final verdict from a single score:
    score >= 0.7  -> "spam"
    0.4 <= score < 0.7 -> "suspicious"
    score < 0.4  -> "benign"
  """

  authentication_classes = []
  permission_classes = []

  def post(self, request):
    # Validate incoming JSON with DRF serializer
    serializer = AnalyzeEmailSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    message_id = data["message_id"]
    force_recompute = bool(data.get("force_recompute", False))

    # ------------------------------------------------------------------
    # 1) Fast path: check if we already analyzed this message
    # ------------------------------------------------------------------
    existing = None if force_recompute else EmailRecord.objects.filter(
      message_id=message_id
    ).first()

    if existing:
      return Response(
        {
          "message_id": existing.message_id,
          "verdict": existing.verdict,
          "score": existing.score,
          "reasons": existing.reasons,
          "cached": True,
          "timestamp": existing.created_at.isoformat(),
        },
        status=status.HTTP_200_OK,
      )

    # ------------------------------------------------------------------
    # 2) Not cached: handle attachments (if any) and run full pipeline
    # ------------------------------------------------------------------

    # Save base64 attachments to disk (optional feature)
    saved_meta = []
    for att in data.get("attachments", []) or []:
      os.makedirs(ATTACH_DIR, exist_ok=True)
      safe_name = f"{timezone.now().strftime('%Y%m%d%H%M%S')}_{att['filename']}"
      path = os.path.join(ATTACH_DIR, safe_name)

      try:
        with open(path, "wb") as f:
          f.write(base64.b64decode(att["content_b64"]))
        saved_meta.append({"filename": att["filename"], "path": path})
      except Exception as exc:
        saved_meta.append({"filename": att["filename"], "error": str(exc)})

    # Use a transaction so DB state is consistent if something fails later
    with transaction.atomic():
      # Store a record of this email in the database
      rec = EmailRecord.objects.create(
        message_id=message_id,
        sender=data.get("sender", ""),
        subject=data.get("subject", ""),
        body=data.get("body", ""),
        attachments_meta=saved_meta,
      )

      # Combine subject + body (already includes OCR text from extension)
      body_for_analysis = f"{rec.subject or ''} {rec.body or ''}".strip()
      print("[AnalyzeEmailView] body_for_analysis:", body_for_analysis[:200])

      # --------------------------------------------------------------
      # 2a) URL blocklist pass
      # --------------------------------------------------------------
      url_info = assess_urls(rec.sender, body_for_analysis)
      status_block = url_info["status"]               # "malicious", "benign", or "unknown"
      malicious_hosts = url_info["malicious_hosts"]   # list of domains
      benign_hosts = url_info["benign_hosts"]

      print(
        f"[AnalyzeEmailView] URL blocklist status={status_block}, "
        f"malicious={malicious_hosts}, benign={benign_hosts}"
      )

      reasons: list[str] = []

      # Case A: direct hit on malicious domain -> spam, ML not needed
      if status_block == "malicious" and malicious_hosts:
        verdict = "spam"
        final_score = 1.0  # hard flag as spam

        reasons.append("blocklist_malicious_hit")
        for host in malicious_hosts:
          reasons.append(f"blocklist_malicious_domain:{host}")

        rec.analysis = {
          "blocklist_status": status_block,
          "blocklist_malicious_hosts": malicious_hosts,
          "blocklist_benign_hosts": benign_hosts,
          "used_ml": False,
          "final_score": final_score,
        }
        rec.verdict = verdict
        rec.score = final_score
        rec.reasons = reasons
        rec.save()

      else:
        # Case B/C: benign or unknown URLs -> run text ML model
        prediction = ml_engine.predict(body_for_analysis)
        print("[AnalyzeEmailView] ML prediction:", prediction)

        ml_score = float(prediction.get("score", 0.0) or 0.0)
        ml_verdict = prediction.get("verdict", "unknown")
        reasons = list(prediction.get("reasons", []))

        final_score = ml_score

        # If we saw a benign domain, discount the ML risk a bit
        if status_block == "benign" and benign_hosts:
          final_score = 0.7 * ml_score
          reasons.append("blocklist_benign_hit")
          for host in benign_hosts:
            reasons.append(f"blocklist_benign_domain:{host}")

        # Map single final_score into a discrete verdict
        if final_score >= 0.7:
          verdict = "spam"
        elif final_score >= 0.4:
          verdict = "suspicious"
        else:
          verdict = "benign"

        rec.analysis = {
          "blocklist_status": status_block,
          "blocklist_malicious_hosts": malicious_hosts,
          "blocklist_benign_hosts": benign_hosts,
          "ml_verdict": ml_verdict,
          "ml_score": ml_score,
          "final_score": final_score,
        }
        rec.verdict = verdict
        rec.score = round(final_score, 3)
        rec.reasons = reasons
        rec.save()

    # ------------------------------------------------------------------
    # 3) Build JSON response for the extension
    # ------------------------------------------------------------------
    response_data = {
      "message_id": rec.message_id,
      "verdict": rec.verdict,
      "score": rec.score,
      "reasons": rec.reasons,
      "cached": False,
      "timestamp": rec.created_at.isoformat(),
    }

    return Response(response_data, status=status.HTTP_200_OK)
