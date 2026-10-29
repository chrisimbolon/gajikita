# =============================================================================
# === backend/apps/organizations/permissions.py ===
# =============================================================================
"""
Who may use HR's office screens (G2b, 27 Oct 2026): an active member of a
company whose role is owner, admin or hr. Workers (phone + PIN logins) have
no membership at all, so they never get in.

The permission also pins the acting company onto the request as
request.hr_org, so every HR view filters by it in one obvious place.
"""
from rest_framework.permissions import BasePermission

HR_ROLES = ("owner", "admin", "hr")


def active_membership(user):
    return (user.memberships.filter(is_active=True).select_related("organization")
            .order_by("id").first())


class IsCompanyHR(BasePermission):
    message = "Hanya pemilik atau HR perusahaan yang bisa membuka halaman ini."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        membership = active_membership(user)
        if membership is None or membership.role not in HR_ROLES:
            return False
        request.hr_org = membership.organization
        return True
