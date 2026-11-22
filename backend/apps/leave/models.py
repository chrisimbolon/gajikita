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
        MATERNITY = rules.MATERNITY, rules.KIND_LABELS[rules.MATERNITY]      # G14-2
        MISCARRY  = rules.MISCARRY,  rules.KIND_LABELS[rules.MISCARRY]
        LONG_REST = rules.LONG_REST, rules.KIND_LABELS[rules.LONG_REST]

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


class LeaveSettings(TenantScopedModel):
    """
    G14-1 (20 Nov 2026): a company's leave rules, one row per company (made on first use). The defaults are
    UU No. 27 Tahun 2026; a company may choose otherwise and "Aturan perusahaan vs UU" shows the difference.
    """
    organization = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE,
                                        related_name="leave_settings")
    collective_leave_reduces_annual = models.BooleanField(default=False,
                                                          verbose_name="Cuti bersama mengurangi cuti tahunan")
    paternity_extra_days = models.PositiveSmallIntegerField(default=rules.PATERNITY_EXTRA_MAX,
                                                            verbose_name="Tambahan cuti istri melahirkan (hari)")
    menstrual_leave = models.BooleanField(default=True, verbose_name="Cuti haid")
    # G14-2: UU 27/2026 Pasal 123 ayat 3 and 118 ayat 2 c
    maternity_extension_pay = models.PositiveSmallIntegerField(
        default=rules.MATERNITY_LAW_PAY, verbose_name="Upah perpanjangan cuti melahirkan bulan ke-5 dan ke-6 (%)")
    long_rest = models.BooleanField(default=True, verbose_name="Istirahat panjang")
    long_leave_keeps_attendance_bonus = models.BooleanField(
        default=False, verbose_name="Tunjangan kehadiran tetap dibayar saat cuti melahirkan / istirahat")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Pengaturan cuti"

    @classmethod
    def for_org(cls, organization):
        obj, _ = cls.objects.get_or_create(organization=organization)
        return obj
