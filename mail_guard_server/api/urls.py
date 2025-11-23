

from django.urls import path
from .views import AnalyzeEmailView

urlpatterns = [
    # 📩 Main API endpoint — used by Chrome extension to analyze emails in real-time
    path("analyze_email/", AnalyzeEmailView.as_view(), name="analyze_email"),

    # (Optional) You can later add endpoints like:
    # path("export_emails/", ExportEmailsView.as_view(), name="export_emails"),
    # path("stats/", StatsView.as_view(), name="stats"),
]
