# =============================================================================
# === backend/apps/organizations/models.py ===
# =============================================================================
"""
One Organization = one company using GajiKita (the tenant).
Slimmed from Arthasee: the workshop-only fields (appointment capacity,
period-closing rule, logo, onboarding gate) are left out until needed.
"""
import re
import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=200, verbose_name="Nama Perusahaan")
    plan         = models.CharField(max_length=50, default="free", verbose_name="Paket")
    is_active    = models.BooleanField(default=True, verbose_name="Aktif")
    invoice_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name="Kode Invoice",
        help_text="Kode singkat untuk penomoran dokumen, mis. 'MK'. Diisi otomatis dari nama perusahaan.",
    )
    phone      = models.CharField(max_length=30, blank=True, default="", verbose_name="Telepon")
    address    = models.TextField(blank=True, default="", verbose_name="Alamat")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Organization"
        verbose_name_plural = "Organizations"

    def __str__(self):
        return self.name

    _LEGAL_PREFIX_RE = re.compile(r"^\s*(CV|PT|UD)\.?\s+", re.IGNORECASE)

    def save(self, *args, **kwargs):
        if self._state.adding and not self.invoice_code:
            self.invoice_code = self._generate_invoice_code()
        super().save(*args, **kwargs)

    def _generate_invoice_code(self):
        """Same rule as Arthasee: drop CV/PT/UD, then initials of the first words."""
        cleaned = self._LEGAL_PREFIX_RE.sub("", self.name or "").strip()
        words = re.findall(r"[A-Za-z]+", cleaned)
        if not words:
            return "ORG"
        code = words[0][:3].upper() if len(words) == 1 else "".join(w[0] for w in words[:4]).upper()
        return code[:10] or "ORG"


class OrganizationMembership(models.Model):
    """Who belongs to which company, and with what role. TenantScopedAPIView
    reads this to decide which rows a request may touch."""
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role         = models.CharField(max_length=50, default="member", verbose_name="Peran")
    is_active    = models.BooleanField(default=True, verbose_name="Aktif")
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Organization Membership"
        verbose_name_plural = "Organization Memberships"
        unique_together     = [("organization", "user")]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"
