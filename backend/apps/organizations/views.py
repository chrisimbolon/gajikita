# =============================================================================
# === backend/apps/organizations/views.py ===
# =============================================================================
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrganizationSerializer, OrganizationSettingsUpdateSerializer

NO_ORG = "Anda belum tergabung dalam perusahaan manapun."


def _membership(user):
    return user.memberships.filter(is_active=True).select_related("organization").order_by("id").first()


class MyOrganizationView(APIView):
    """GET/PATCH /api/organizations/mine/ — the current user's company. PATCH is owner-only."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = _membership(request.user)
        if not m:
            return Response({"success": False, "message": NO_ORG}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "organization": OrganizationSerializer(m.organization).data, "role": m.role})

    def patch(self, request):
        m = _membership(request.user)
        if not m:
            return Response({"success": False, "message": NO_ORG}, status=status.HTTP_404_NOT_FOUND)
        if m.role != "owner":
            return Response({"success": False, "message": "Hanya pemilik perusahaan yang bisa mengubah pengaturan ini."},
                            status=status.HTTP_403_FORBIDDEN)
        serializer = OrganizationSettingsUpdateSerializer(m.organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "organization": OrganizationSerializer(m.organization).data})
