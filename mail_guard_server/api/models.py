
# api/models.py
from django.db import models


class EmailRecord(models.Model):
    """
    Represents one analyzed email in the system.

    We store:
      - Basic metadata (message_id, sender, subject)
      - The cleaned email body (`body`)
      - The body plus OCR-extracted text (`body_with_ocr`)
      - OCR text blocks from image attachments (`attachments_text`)
      - Saved attachment metadata (filenames, paths, or error)
      - Whether OCR contributed to the final body (`ocr_used`)
      - Final analysis output: verdict, score, reasons
      - Timestamp for when the record was created
    """

    # Unique Gmail message ID → ensures same email is not analyzed twice
    message_id = models.CharField(max_length=255, unique=True, db_index=True)

    # Basic metadata extracted from Gmail headers
    sender = models.TextField(blank=True)
    subject = models.TextField(blank=True)

    # Cleaned, plain-text version of the email (HTML stripped, etc.)
    body = models.TextField(blank=True)

    # Same as `body`, but with OCR text appended if images contained text
    body_with_ocr = models.TextField(blank=True)

    # List of OCR text blocks from attachments (JSON)
    attachments_text = models.JSONField(blank=True, null=True)

    # Details about saved attachments (e.g. filename, local path, errors)
    attachments_meta = models.JSONField(blank=True, null=True)

    # Whether OCR actually contributed content to body_with_ocr
    ocr_used = models.BooleanField(default=False)

    # Final analysis results after ML + blocklist logic
    verdict = models.CharField(max_length=50, default="unknown")
    score = models.FloatField(blank=True, null=True)
    reasons = models.JSONField(default=list, blank=True)

    # Creation timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.message_id} {self.subject[:60]}"
