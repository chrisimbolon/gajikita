# =============================================================================
# === backend/apps/employees/views.py ===
# =============================================================================
"""
The worker's login (G2a):

  POST /api/worker/login/  {phone, pin}           -> access + refresh tokens
  POST /api/worker/pin/    {current_pin, new_pin} -> change PIN (required after HR sets one)

HR's employee screens come in G2b.
"""
from datetime import timedelta

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Employee
from .worker_login import LoginError, change_pin, check_login

# Workers shouldn't have to log in again every week: their refresh token lasts 30 days.
WORKER_REFRESH_DAYS = 30


class WorkerLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        try:
            emp = check_login(request.data.get("phone", ""), request.data.get("pin", ""))
        except LoginError as err:
            code = status.HTTP_423_LOCKED if err.locked_minutes else status.HTTP_400_BAD_REQUEST
            return Response({"success": False, "message": err.message, "locked_minutes": err.locked_minutes},
                            status=code)
        refresh = RefreshToken.for_user(emp.user)
        refresh.set_exp(lifetime=timedelta(days=WORKER_REFRESH_DAYS))
        return Response({
            "success": True,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "must_change_pin": emp.must_change_pin,
            "employee": {"id": str(emp.id), "employee_no": emp.employee_no, "full_name": emp.full_name,
                         "organization": emp.organization.name},
        })


class WorkerPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        emp = Employee.objects.filter(user=request.user, status=Employee.Status.ACTIVE).select_related("user").first()
        if emp is None:
            return Response({"success": False, "message": "Akun ini belum terhubung ke data karyawan aktif."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            change_pin(emp, request.data.get("current_pin", ""), request.data.get("new_pin", ""))
        except ValueError as err:
            return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"success": True, "message": "PIN berhasil diganti."})
