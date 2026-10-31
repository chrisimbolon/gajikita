# =============================================================================
# === backend/apps/sites/models.py ===
# =============================================================================
"""
Where people work (Site), where each site is over time (SiteLocation),
and planned working hours (Shift). GajiKita Design v0.1, "Attendance
with geofence".

A site's pin is never edited in place. Moving a road project's pin adds
a new SiteLocation row with its own valid_from, so a clock-in from last
month is still measured against the pin that was valid last month.
"""
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TenantScopedModel


class Site(TenantScopedModel):
    class Kind(models.TextChoices):
        FIXED  = "fixed",  "Tetap"
        MOVING = "moving", "Berpindah"
        VESSEL = "vessel", "Kapal"
        NONE   = "none",   "Tanpa lokasi"

    # Only these kinds get a distance check. A vessel moves with the crew on
    # board and a driver has no site at all: their position is recorded, never judged.
    FENCED_KINDS = (Kind.FIXED, Kind.MOVING)

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=150, verbose_name="Nama Lokasi")
    kind         = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FIXED, verbose_name="Jenis")
    project_code = models.CharField(max_length=30, blank=True, default="", verbose_name="Kode Proyek")
    is_active    = models.BooleanField(default=True, verbose_name="Aktif")
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Lokasi"
        verbose_name_plural = "Lokasi"
        ordering            = ["name"]
        unique_together     = [("organization", "name")]

    def __str__(self):
        return self.name

    @property
    def is_fenced(self):
        return self.kind in self.FENCED_KINDS

    def location_at(self, when=None):
        """The pin that was valid at `when` (default: now), or None if the site has no pin yet."""
        when = when or timezone.now()
        return self.locations.filter(valid_from__lte=when).order_by("-valid_from").first()

    def move_pin(self, latitude, longitude, radius_m=None, valid_from=None):
        """Add a new pin from `valid_from` (default: now). Older pins stay for history."""
        valid_from = valid_from or timezone.now()
        current = self.location_at(valid_from)
        if radius_m is None:
            radius_m = current.radius_m if current else SiteLocation.DEFAULT_RADIUS_M
        loc = SiteLocation(
            organization=self.organization, site=self,
            latitude=latitude, longitude=longitude, radius_m=radius_m, valid_from=valid_from,
        )
        loc.full_clean()
        loc.save()
        return loc


class SiteLocation(TenantScopedModel):
    DEFAULT_RADIUS_M = 150

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site       = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="locations")
    latitude   = models.DecimalField(
        max_digits=9, decimal_places=6, verbose_name="Lintang",
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude  = models.DecimalField(
        max_digits=9, decimal_places=6, verbose_name="Bujur",
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    radius_m   = models.PositiveIntegerField(
        default=DEFAULT_RADIUS_M, verbose_name="Radius (m)",
        validators=[MinValueValidator(20), MaxValueValidator(5000)],
    )
    valid_from = models.DateTimeField(default=timezone.now, verbose_name="Berlaku Sejak")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Titik Lokasi"
        verbose_name_plural = "Titik Lokasi"
        ordering            = ["-valid_from"]

    def __str__(self):
        return f"{self.site} @ {self.latitude},{self.longitude} r={self.radius_m}m"

    def _resolve_organization(self):
        return self.site.organization if self.site_id else None


class Shift(TenantScopedModel):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name          = models.CharField(max_length=100, verbose_name="Nama Shift")
    start_time    = models.TimeField(verbose_name="Jam Mulai")
    end_time      = models.TimeField(verbose_name="Jam Selesai")
    grace_minutes = models.PositiveSmallIntegerField(default=10, verbose_name="Toleransi Terlambat (menit)")
    working_days  = models.CharField(
        max_length=7, default="12345", verbose_name="Hari Kerja",
        help_text="Angka hari: 1=Senin ... 7=Minggu. Contoh 6 hari kerja: 123456",
    )
    is_active     = models.BooleanField(default=True, verbose_name="Aktif")
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Shift"
        verbose_name_plural = "Shift"
        ordering            = ["start_time", "name"]
        unique_together     = [("organization", "name")]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    @property
    def crosses_midnight(self):
        """A night shift, e.g. 22:00-06:00, ends on the next calendar day."""
        return self.end_time <= self.start_time

    def is_working_day(self, day):
        return str(day.isoweekday()) in self.working_days

    def clean(self):
        days = self.working_days or ""
        if not days or any(c not in "1234567" for c in days) or len(set(days)) != len(days):
            raise ValidationError({"working_days": "Isi dengan angka 1-7 tanpa pengulangan, mis. 123456."})
        if self.start_time is not None and self.start_time == self.end_time:
            raise ValidationError({"end_time": "Jam selesai tidak boleh sama dengan jam mulai."})
