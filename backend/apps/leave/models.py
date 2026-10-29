# =============================================================================
# === backend/apps/leave/models.py ===
# =============================================================================
"""
One leave request (cuti / sakit / izin), G7, 28 Oct 2026.

Made by the worker on the phone (waits for the site manager = the worker's
"Mandor / atasan", or HR) or recorded by HR from the paper form (approved at
once). Approved leave turns those working days from "Tidak hadir" into the
leave on the attendance pages; payroll reads `paid` later.
"""
import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TenantScopedModel

from . import rules


def attachment_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:6] or ".jpg"
    return f"leave/{instance.organization_id}/{instance.start_date:%Y/%m}/{uuid.uuid4().hex}{ext}"


class LeaveRequest(TenantScopedModel):
    class Kind(models.TextChoices):
        ANNUAL  = rules.ANNUAL,  rules.KIND_LABELS[rules.ANNUAL]
        SICK    = rules.SICK,    rules.KIND_LABELS[rules.SICK]
        SPECIAL = rules.SPECIAL, rules.KIND_LABELS[rules.SPECIAL]
        UNPAID  = rules.UNPAID,  rules.KIND_LABELS[rules.UNPAID]

    class Status(models.TextChoices):
        PENDING   = "pending",   "Menunggu persetujuan"
        APPROVED  = "approved",  "Disetujui"
        REJECTED  = "rejected",  "Ditolak"
        CANCELLED = "cancelled", "Dibatalkan"

    class Source(models.TextChoices):
        PHONE = "phone", "Dari HP karyawan"
        FORM  = "form",  "Formulir kertas (dicatat HR)"

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee       = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="leave_requests",
                                       verbose_name="Karyawan")
    kind           = models.CharField(max_length=10, choices=Kind.choices, verbose_name="Jenis")
    special_reason = models.CharField(max_length=30, blank=True, default="", verbose_name="Alasan cuti khusus")
    start_date     = models.DateField(verbose_name="Mulai")
    end_date       = models.DateField(verbose_name="Sampai")
    days           = models.PositiveSmallIntegerField(default=0, verbose_name="Hari kerja")
    reason         = models.CharField(max_length=500, blank=True, default="", verbose_name="Keterangan")
    attachment     = models.FileField(upload_to=attachment_path, blank=True, verbose_name="Lampiran (surat dokter)")
    status         = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name="Status")
    source         = models.CharField(max_length=10, choices=Source.choices, default=Source.PHONE, verbose_name="Sumber")
    requested_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+")
    decided_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+")
    decided_at     = models.DateTimeField(null=True, blank=True)
    decision_note  = models.CharField(max_length=255, blank=True, default="")
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Cuti / izin"
        verbose_name_plural = "Cuti / izin"
        ordering            = ["-start_date", "-created_at"]
        indexes             = [models.Index(fields=["organization", "status"]),
                               models.Index(fields=["employee", "start_date"])]

    def __str__(self):
        return f"{self.employee} {self.label} {self.start_date}–{self.end_date}"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None

    @property
    def label(self):
        return rules.label_of(self.kind, self.special_reason)

    @property
    def paid(self):
        return rules.PAID.get(self.kind, True)
