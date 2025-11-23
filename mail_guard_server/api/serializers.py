
# api/serializer.py
from rest_framework import serializers
from .models import EmailRecord


class AttachmentSerializer(serializers.Serializer):
    """
    Serializer for handling raw binary attachments coming from the extension.
    We keep it flexible: each attachment has a filename + base64 content.
    """
    filename = serializers.CharField()
    content_b64 = serializers.CharField()


class AnalyzeEmailSerializer(serializers.Serializer):
    """
    Main serializer for the '/analyze_email/' endpoint.
    Validates emails sent from the Chrome extension before they enter the pipeline.
    """
    message_id = serializers.CharField()
    sender = serializers.CharField()

    subject = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    date = serializers.DateTimeField(required=False)

    # Optional binary attachments (base64)
    attachments = AttachmentSerializer(many=True, required=False)

    # Optional OCR output provided by the extension (already extracted text)
    attachments_text = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )

    # Small metadata block sent by the extension
    client_meta = serializers.DictField(
        required=False,
        child=serializers.CharField(),
        allow_empty=True,
    )

    def create(self, validated_data):
        """
        Persist a new EmailRecord into the database.

        If OCR text is passed (from attachment images),
        we merge it with the email body so the ML model and analysis pipeline
        have one combined text source.
        """
        attachments_text = validated_data.get("attachments_text") or []
        base_body = validated_data.get("body") or ""

        # Combine original body + OCR text (if present)
        if attachments_text:
            body_with_ocr = (
                base_body
                + "\n\n[OCR extraction from attachments]\n"
                + "\n\n---\n\n".join(attachments_text)
            )
        else:
            body_with_ocr = base_body

        # Create a database entry reflecting the incoming email
        record = EmailRecord.objects.create(
            message_id=validated_data["message_id"],
            sender=validated_data.get("sender", ""),
            subject=validated_data.get("subject", ""),
            body=base_body,
            body_with_ocr=body_with_ocr,
            attachments_text=attachments_text,
            ocr_used=bool(attachments_text),

            # These fields get filled after ML analysis
            verdict="unknown",
            score=None,
            reasons=[],
        )

        return record
