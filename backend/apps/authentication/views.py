# =============================================================================
# === backend/apps/authentication/views.py ===
# =============================================================================
from apps.organizations.models import Organization, OrganizationMembership
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CustomUser
from .passwords import password_problems, set_password
from .serializers import RegisterSerializer, UserSerializer


class RegisterView(APIView):
    """
    POST /api/auth/register/
    Wrapped in one atomic transaction on purpose — a user existing
    without an organization (or vice versa) is a broken account, not
    a partial success. Either all three rows get created, or none do.

    permission_classes = [AllowAny] is REQUIRED here, not optional —
    without it, this silently inherits the project's global default
    (IsAuthenticated), which would mean you'd have to already be
    logged in to register a new account. Discovered via a real 401
    failure across every RegisterViewTests case — this is exactly
    why that test gap mattered.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        with transaction.atomic():
            user = CustomUser.objects.create_user(
                email=data["email"], password=data["password"],
                full_name=data["full_name"], phone=data.get("phone", ""),
                role=CustomUser.Role.OWNER,
            )
            org = Organization.objects.create(name=data["organization_name"])
            OrganizationMembership.objects.create(
                organization=org, user=user, role="owner", is_active=True,
            )

            # GajiKita: the chart of accounts and first accounting
            # period are seeded here once the accounting engine is ported.

        refresh = RefreshToken.for_user(user)
        return Response({
            "success": True,
            "user":    UserSerializer(user).data,
            "tokens":  {"access": str(refresh.access_token), "refresh": str(refresh)},
        }, status=status.HTTP_201_CREATED)


class ChangePasswordView(APIView):
    """
    POST /api/auth/password/ {old_password, new_password} — G22-1 "Akun saya → Ubah password".
    Every other session of this user is signed out; this one gets fresh tokens. Clears "wajib ganti password".
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old, new = request.data.get("old_password") or "", request.data.get("new_password") or ""
        if not user.check_password(old):
            return Response({"success": False, "errors": {"old_password": ["Password lama salah."]}},
                            status=status.HTTP_400_BAD_REQUEST)
        problems = password_problems(user, new, old)
        if problems:
            return Response({"success": False, "errors": {"new_password": problems}}, status=status.HTTP_400_BAD_REQUEST)
        set_password(user, new, temporary=False)
        membership = user.memberships.filter(is_active=True).select_related("organization").order_by("id").first()
        if membership:
            from apps.core.audit import record_audit
            record_audit(organization=membership.organization, actor=user, action="user.password_change", target=user,
                         summary=f"{user.full_name} mengganti password sendiri")
        refresh = RefreshToken.for_user(user)
        return Response({"success": True, "user": UserSerializer(user).data,
                         "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)}})


class MeView(APIView):
    """GET /api/auth/me/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "user": UserSerializer(request.user).data})

