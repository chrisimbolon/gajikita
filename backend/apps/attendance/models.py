# =============================================================================
# === backend/apps/attendance/models.py ===
# =============================================================================
"""
AttendanceDay = one employee, one working day.
ClockEvent    = one tap (or kiosk scan, or fingerprint punch) on that day.

G1 records the taps and their flags. The day's status (on time, late,
no clock-out...) and HR's decisions are added in G3.
"""
import os
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantScopedModel

from .geofence import FLAG_LABELS


class AttendanceDay(TenantScopedModel):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee   = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="attendance_days")
    date       = models.DateField(verbose_name="Tanggal")
    shift      = models.ForeignKey("sites.Shift", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_locked  = models.BooleanField(default=False, verbose_name="Terkunci",
                                     help_text="Dikunci setelah pay run disetujui.")
    # HR's review (G3). hr_in / hr_out replace the taps when HR fixes the times.
    hr_in         = models.DateTimeField(null=True, blank=True, verbose_name="Jam Masuk (koreksi HR)")
    hr_out        = models.DateTimeField(null=True, blank=True, verbose_name="Jam Pulang (koreksi HR)")
    decision      = models.CharField(max_length=10, blank=True, default="", verbose_name="Keputusan HR",
                                     choices=[("approved", "Disetujui"), ("rejected", "Ditolak")])
    decision_note = models.TextField(blank=True, default="", verbose_name="Catatan HR")
    waive_late    = models.BooleanField(default=False, verbose_name="Terlambat dimaafkan")
    overtime_approved_minutes = models.PositiveIntegerField(null=True, blank=True, verbose_name="Lembur Disetujui (menit)")
    decided_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    decided_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Hari Absensi"
        verbose_name_plural = "Hari Absensi"
        ordering            = ["-date"]
        unique_together     = [("employee", "date")]

    def __str__(self):
        return f"{self.employee} — {self.date}"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None


def selfie_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"selfies/{instance.organization_id}/{instance.occurred_at:%Y/%m}/{uuid.uuid4().hex}{ext}"


class ClockEvent(TenantScopedModel):
    class Kind(models.TextChoices):
        IN     = "in",     "Masuk"
        SWITCH = "switch", "Pindah lokasi"
        OUT    = "out",    "Pulang"

    class Source(models.TextChoices):
        APP         = "app",         "Aplikasi HP"
        KIOSK       = "kiosk",       "Kiosk gerbang"
        FINGERPRINT = "fingerprint", "Mesin sidik jari"
        HR_EDIT     = "hr_edit",     "Koreksi HR"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    day           = models.ForeignKey(AttendanceDay, on_delete=models.CASCADE, related_name="events")
    employee      = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="clock_events")
    kind          = models.CharField(max_length=10, choices=Kind.choices, verbose_name="Jenis")
    source        = models.CharField(max_length=20, choices=Source.choices, default=Source.APP, verbose_name="Sumber")
    site          = models.ForeignKey("sites.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The exact pin the tap was measured against, so moving a site's pin later never rewrites history.
    site_location = models.ForeignKey("sites.SiteLocation", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    occurred_at   = models.DateTimeField(db_index=True, verbose_name="Waktu Absen")
    received_at   = models.DateTimeField(verbose_name="Diterima Server")
    phone_time    = models.DateTimeField(null=True, blank=True, verbose_name="Waktu di HP")
    latitude      = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude     = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m    = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, verbose_name="Akurasi (m)")
    distance_m    = models.PositiveIntegerField(null=True, blank=True, verbose_name="Jarak ke Lokasi (m)")
    selfie        = models.ImageField(upload_to=selfie_path, blank=True, verbose_name="Selfie")
    flags         = models.JSONField(default=list, blank=True, verbose_name="Tanda")
    # Sent by the phone with every tap; a retry after a dropped signal sends
    # the same id again and gets the first event back instead of a duplicate.
    client_id     = models.UUIDField(null=True, blank=True, editable=False)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Catatan Absen"
        verbose_name_plural = "Catatan Absen"
        ordering            = ["occurred_at"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "client_id"], condition=Q(client_id__isnull=False),
                                    name="uniq_clock_event_client_id"),
        ]

    def __str__(self):
        return f"{self.employee} {self.get_kind_display()} {self.occurred_at:%Y-%m-%d %H:%M}"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None

    @property
    def flag_labels(self):
        return [FLAG_LABELS.get(f, f) for f in self.flags]
