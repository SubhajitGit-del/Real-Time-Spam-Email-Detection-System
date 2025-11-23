'''
# api/management/commands/export_emails.py
import csv
from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import EmailRecord

class Command(BaseCommand):
    help = "Export EmailRecord rows to a CSV file for ML/training/backup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            "-o",
            dest="out",
            required=False,
            default="export_emails.csv",
            help="Output CSV filename (default: export_emails.csv)",
        )
        parser.add_argument(
            "--limit",
            dest="limit",
            type=int,
            required=False,
            help="Limit number of rows exported (for sampling)",
        )
        parser.add_argument(
            "--since",
            dest="since",
            required=False,
            help="Only export records created after this ISO datetime (e.g. 2025-10-01T00:00:00)",
        )

    def handle(self, *args, **options):
        out = options["out"]
        limit = options.get("limit")
        since = options.get("since")

        fields = [
            "message_id",
            "sender",
            "subject",
            "body",
            "verdict",
            "score",
            "reasons",
            "created_at",
        ]

        qs = EmailRecord.objects.all().order_by("-created_at")
        if since:
            try:
                since_dt = timezone.datetime.fromisoformat(since)
                if timezone.is_naive(since_dt):
                    since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
                qs = qs.filter(created_at__gte=since_dt)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Invalid --since value: {e}"))
                return

        if limit:
            qs = qs[:limit]

        self.stdout.write(self.style.SUCCESS(f"Exporting {qs.count()} rows → {out}"))

        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(fields)
            for obj in qs:
                row = []
                for f in fields:
                    val = getattr(obj, f, "")
                    if isinstance(val, (list, dict)):
                        import json
                        val = json.dumps(val, ensure_ascii=False)
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    row.append(val)
                writer.writerow(row)

        self.stdout.write(self.style.SUCCESS("✅ Export complete!"))

        '''

# api/management/commands/export_emails.py
import csv
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import EmailRecord

class Command(BaseCommand):
    help = "Export EmailRecord rows to a CSV file for ML/training/backup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            "-o",
            dest="out",
            required=False,
            default="export_emails.csv",
            help="Output CSV filename (default: export_emails.csv)",
        )
        parser.add_argument(
            "--limit",
            dest="limit",
            type=int,
            required=False,
            help="Limit number of rows exported (for sampling)",
        )
        parser.add_argument(
            "--since",
            dest="since",
            required=False,
            help="Only export records created after this ISO datetime (e.g. 2025-10-01T00:00:00)",
        )

    def handle(self, *args, **options):
        out = options["out"]
        limit = options.get("limit")
        since = options.get("since")

        # include the new fields body_with_ocr and attachments_text
        fields = [
            "message_id",
            "sender",
            "subject",
            "body",
            "body_with_ocr",     # NEW: merged body (body + OCR)
            "attachments_text",  # NEW: list of OCR strings (JSON)
            "verdict",
            "score",
            "reasons",
            "created_at",
        ]

        qs = EmailRecord.objects.all().order_by("-created_at")
        if since:
            try:
                since_dt = timezone.datetime.fromisoformat(since)
                if timezone.is_naive(since_dt):
                    since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
                qs = qs.filter(created_at__gte=since_dt)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Invalid --since value: {e}"))
                return

        if limit:
            qs = qs[:limit]

        total = qs.count() if hasattr(qs, "count") else len(list(qs))
        self.stdout.write(self.style.SUCCESS(f"Exporting {total} rows → {out}"))

        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(fields)
            for obj in qs:
                row = []
                for f in fields:
                    val = getattr(obj, f, "")
                    # ensure JSON fields are dumped to valid JSON text
                    if isinstance(val, (list, dict)):
                        val = json.dumps(val, ensure_ascii=False)
                    # datetimes
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    # protect against None
                    if val is None:
                        val = ""
                    row.append(val)
                writer.writerow(row)

        self.stdout.write(self.style.SUCCESS("✅ Export complete!"))

