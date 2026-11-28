"""
G22-1 (28 Nov 2026) — "Pengguna": the company's office users (owner, admin, HR), managed inside SeeGaji.

  GET   /api/organizations/members/              the list + which roles I may give
  POST  /api/organizations/members/              {email, full_name, phone?, role} -> a temporary password, shown once
  PATCH /api/organizations/members/<id>/         {action: deactivate | activate | reset_password | set_role, role?}

Who: an active owner or admin. An owner may add or change admin and hr; an admin only hr. Nobody changes or
switches off themselves or the owner here. A new user or a reset gets a temporary password that must be changed at
first login; switching someone off or resetting them signs them out of every device. Every change goes to the audit log.
"""
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import CustomUser
from apps.authentication.passwords import set_password, sign_out_everywhere, temp_password
from apps.core.audit import record_audit

from .models import OrganizationMembership

ROLE_LABELS = {"owner": "Pemilik", "admin": "Admin", "hr": "HR"}
ASSIGNABLE = {"owner": ("admin", "hr"), "admin": ("hr",)}


def _manager(user):
    m = (user.memberships.filter(is_active=True).select_related("organization").order_by("id").first()
         if user.is_authenticated else None)
    return m if m and m.role in ASSIGNABLE and not user.must_change_password else None


def _row(m, me):
    u = m.user
    return {"id": str(m.pk), "role": m.role, "role_label": ROLE_LABELS.get(m.role, m.role), "is_active": m.is_active,
            "is_me": u.pk == me.pk,
            "user": {"id": str(u.pk), "email": u.email, "full_name": u.full_name, "phone": u.phone,
                     "last_login": u.last_login.isoformat() if u.last_login else None,
                     "must_change_password": u.must_change_password}}


def _denied():
    return Response({"success": False, "message": "Hanya pemilik atau admin perusahaan yang bisa mengatur pengguna."},
                    status=status.HTTP_403_FORBIDDEN)


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "message": message}, status=code)


class MembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = _manager(request.user)
        if not me:
            return _denied()
        rows = (OrganizationMembership.objects.filter(organization=me.organization).select_related("user")
                .exclude(user__role=CustomUser.Role.EMPLOYEE).order_by("-is_active", "user__full_name"))
        return Response({"success": True, "my_role": me.role, "can_assign": list(ASSIGNABLE[me.role]),
                         "members": [_row(m, request.user) for m in rows]})

    def post(self, request):
        me = _manager(request.user)
        if not me:
            return _denied()
        email = (request.data.get("email") or "").strip().lower()
        name = (request.data.get("full_name") or "").strip()
        role = request.data.get("role") or "hr"
        if "@" not in email or "." not in email.split("@")[-1]:
            return _bad("Email belum benar.")
        if not name:
            return _bad("Nama wajib diisi.")
        if role not in ASSIGNABLE[me.role]:
            return _bad(f"Peran {ROLE_LABELS.get(role, role)} tidak bisa diberikan oleh {ROLE_LABELS[me.role]}.")
        if CustomUser.objects.filter(email__iexact=email).exists():
            return _bad("Email ini sudah dipakai akun lain. Pakai email lain.")
        password = temp_password()
        with transaction.atomic():
            # CustomUser.role is the platform-level kind of login: "owner" = an office user (not a phone/PIN worker).
            user = CustomUser.objects.create_user(email=email, password=password, full_name=name,
                                                  phone=(request.data.get("phone") or "").strip(),
                                                  role=CustomUser.Role.OWNER, must_change_password=True)
            m = OrganizationMembership.objects.create(organization=me.organization, user=user, role=role, is_active=True)
            record_audit(organization=me.organization, actor=request.user, action="user.add", target=m,
                         summary=f"Pengguna baru {name} ({ROLE_LABELS[role]}), {email}")
        return Response({"success": True, "member": _row(m, request.user), "temp_password": password},
                        status=status.HTTP_201_CREATED)


class MemberView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        me = _manager(request.user)
        if not me:
            return _denied()
        m = (OrganizationMembership.objects.filter(organization=me.organization, pk=pk).select_related("user").first())
        if m is None:
            return _bad("Pengguna tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        if m.user_id == request.user.pk:
            return _bad("Akun sendiri diatur di Akun saya.")
        if m.role not in ASSIGNABLE[me.role]:
            return _bad(f"{ROLE_LABELS[me.role]} tidak bisa mengubah pengguna dengan peran {ROLE_LABELS.get(m.role, m.role)}.",
                        status.HTTP_403_FORBIDDEN)
        action, user = request.data.get("action"), m.user
        out = {}
        with transaction.atomic():
            if action == "deactivate":
                m.is_active = False
                m.save(update_fields=["is_active"])
                if not user.memberships.filter(is_active=True).exists():
                    user.is_active = False                                   # cannot log in any more
                    user.save(update_fields=["is_active"])
                sign_out_everywhere(user)
                summary = f"{user.full_name} dinonaktifkan"
            elif action == "activate":
                m.is_active = True
                m.save(update_fields=["is_active"])
                user.is_active = True
                user.save(update_fields=["is_active"])
                summary = f"{user.full_name} diaktifkan lagi"
            elif action == "reset_password":
                out["temp_password"] = temp_password()
                set_password(user, out["temp_password"], temporary=True)    # also signs them out everywhere
                summary = f"Password {user.full_name} direset (password sementara)"
            elif action == "set_role":
                role = request.data.get("role")
                if role not in ASSIGNABLE[me.role]:
                    return _bad(f"Peran {ROLE_LABELS.get(role, role)} tidak bisa diberikan oleh {ROLE_LABELS[me.role]}.")
                before = m.role
                m.role = role
                m.save(update_fields=["role"])
                summary = f"Peran {user.full_name}: {ROLE_LABELS[before]} → {ROLE_LABELS[role]}"
            else:
                return _bad("Aksi tidak dikenal.")
            record_audit(organization=me.organization, actor=request.user, action=f"user.{action}", target=m,
                         summary=summary)
        m.refresh_from_db()
        m.user.refresh_from_db()
        return Response({"success": True, "member": _row(m, request.user), **out})
