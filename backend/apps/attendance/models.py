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
    # G12f.1a: the machine a fingerprint tap came from; empty = the main machine (and every non-machine tap)
    machine       = models.ForeignKey("FingerprintMachine", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+", verbose_name="Mesin fingerprint")
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


class FingerprintMachine(TenantScopedModel):
    """
    A fingerprint machine besides the main one (G12f.1a). The main machine has no row: its IDs are
    Employee.fingerprint_id, so a company with one machine never needs this table.

    dept_labels lists the "Dept.:" values that belong to this machine in a combined report (DKCB's
    office machine: "Staf, Manager"). An import "Otomatis menurut Dept." sends each block there.
    A machine that has IDs or taps is never deleted, only turned off (is_active=False).
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=80, verbose_name="Nama mesin")
    site        = models.ForeignKey("sites.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                    verbose_name="Lokasi")
    dept_labels = models.CharField(max_length=200, blank=True, default="", verbose_name="Dept. di file",
                                   help_text="Isi kolom Dept. di laporan mesin, pisahkan dengan koma. Mis. Staf, Manager")
    is_active   = models.BooleanField(default=True, verbose_name="Aktif")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Mesin Fingerprint"
        verbose_name_plural = "Mesin Fingerprint"
        ordering            = ["name"]
        unique_together     = [("organization", "name")]

    def __str__(self):
        return self.name


class EmployeeMachineId(TenantScopedModel):
    """An employee's ID on a FingerprintMachine (G12f.1a). Unique per machine; one per employee per machine."""
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee       = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="machine_ids")
    machine        = models.ForeignKey(FingerprintMachine, on_delete=models.PROTECT, related_name="employee_ids")
    fingerprint_id = models.CharField(max_length=30, verbose_name="ID di mesin")
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "ID Mesin Karyawan"
        verbose_name_plural = "ID Mesin Karyawan"
        ordering            = ["machine__name"]
        unique_together     = [("machine", "fingerprint_id"), ("employee", "machine")]

    def __str__(self):
        return f"{self.employee} — {self.machine} {self.fingerprint_id}"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None


class DayNote(TenantScopedModel):
    """
    HR's reason for one employee's day, written outside SeeGaji (G12f.3, 10 Nov 2026): the Note column of
    DKCB's "ESR Edit" recap with its colour code ("Mati lampu", blue = Lain). Shown beside the day in the
    day panel, the rekap and Perlu Tinjau. It never changes status, lateness, overtime or pay.

    One per employee, date and source; importing the recap again updates it, never duplicates it.
    There is no AttendanceDay link on purpose: a note can stand on a day with no taps (UL, Libur).
    """
    class Source(models.TextChoices):
        IMPORT = "import", "Import file rekap"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee    = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="day_notes")
    date        = models.DateField()
    code        = models.CharField(max_length=20, blank=True, default="", verbose_name="Kode",
                                   help_text="Label warna dari legenda file, mis. UL, CT, Lain")
    color       = models.CharField(max_length=6, blank=True, default="", verbose_name="Warna",
                                   help_text="Warna sel di file, RRGGBB")
    text        = models.TextField(blank=True, default="", verbose_name="Catatan")
    source      = models.CharField(max_length=20, choices=Source.choices, default=Source.IMPORT)
    source_file = models.CharField(max_length=255, blank=True, default="")
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Catatan HR per hari"
        verbose_name_plural = "Catatan HR per hari"
        ordering            = ["date"]
        unique_together     = [("employee", "date", "source")]
        indexes             = [models.Index(fields=["organization", "date"], name="attendance_daynote_org_date")]

    def __str__(self):
        return f"{self.employee} {self.date}: {self.code or '-'} {self.text[:40]}"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None


class AttendanceExemption(TenantScopedModel):
    """
    "Tidak wajib absen" (G12i, 11 Nov 2026): from `start` to `end` (null = until further notice) this employee is
    paid for every scheduled working day without tapping: works off-site with no machine (DKCB: Marganda,
    "Kerja di Lobam") or in a role that doesn't tap (Kamarol, sales). Shown as DL; leave still counts; no late
    fines, automatic overtime or meals. A dated period, never a flag, so ending it never rewrites a paid month.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee   = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="attendance_exemptions")
    start      = models.DateField(verbose_name="Mulai")
    end        = models.DateField(null=True, blank=True, verbose_name="Sampai", help_text="Kosong = sampai diubah")
    reason     = models.CharField(max_length=200, verbose_name="Alasan", help_text="mis. Kerja di Lobam")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Tidak wajib absen"
        verbose_name_plural = "Tidak wajib absen"
        ordering            = ["employee", "start"]
        indexes             = [models.Index(fields=["organization", "start"], name="attendance_exempt_org_start")]

    def __str__(self):
        return f"{self.employee}: {self.start} - {self.end or '...'} ({self.reason})"

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None


class CompanyEvent(TenantScopedModel):
    """
    "Kejadian" (G17-2, 14 Nov 2026): a power cut or a holiday, entered ONCE for a date range and a group.
    gangguan = attendance disrupted (DKCB 12-14 Okt "Mati lampu"): working days count as worked, nothing is cut.
    libur    = holiday: working days become days off; working that day is paid the rest-day rate.
    Who: everyone, or the chosen locations (the employee's main location) and/or people.
    Rules in company_events.py; days of a locked payroll can't be touched (event_views.py).
    """
    class Kind(models.TextChoices):
        DISRUPTION = "gangguan", "Gangguan absen"
        HOLIDAY    = "libur",    "Libur"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    start      = models.DateField(verbose_name="Mulai")
    end        = models.DateField(verbose_name="Sampai")
    kind       = models.CharField(max_length=10, choices=Kind.choices, verbose_name="Jenis")
    reason     = models.CharField(max_length=200, verbose_name="Alasan", help_text="mis. Mati lampu")
    everyone   = models.BooleanField(default=True, verbose_name="Semua karyawan")
    sites      = models.ManyToManyField("sites.Site", blank=True, related_name="+", verbose_name="Lokasi")
    employees  = models.ManyToManyField("employees.Employee", blank=True, related_name="+", verbose_name="Karyawan")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Kejadian"
        verbose_name_plural = "Kejadian"
        ordering            = ["-start"]
        indexes             = [models.Index(fields=["organization", "start"], name="attendance_event_org_start")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.start} - {self.end} ({self.reason})"

    def as_rule(self):
        """The pure company_events.Event (uses prefetched sites / employees when present)."""
        from .company_events import Event
        return Event(self.start, self.end, self.kind, self.reason, self.everyone,
                     frozenset(s.pk for s in self.sites.all()), frozenset(e.pk for e in self.employees.all()))
