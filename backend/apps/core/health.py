# =============================================================================
# === backend/apps/core/health.py ===
# =============================================================================
"""GET /api/health/ — open to anyone; used to check the backend is up."""
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return Response({"status": "ok"})
