
from django.contrib import admin
from .models import EmailRecord

@admin.register(EmailRecord)
class EmailRecordAdmin(admin.ModelAdmin):
    list_display = ("message_id", "sender", "subject", "verdict", "score", "created_at")
    search_fields = ("message_id", "sender", "subject")
    list_filter = ("verdict",)
