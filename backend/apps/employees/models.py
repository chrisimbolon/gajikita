# =============================================================================
# === backend/apps/employees/models.py ===
# =============================================================================
"""
One Employee = one worker of a client company. GajiKita Design v0.1,
"Core concepts and data model".

Employment type (the contract) and pay type (how pay is calculated) are
separate on purpose: a PKWT contract worker can be paid daily.

NIK, NPWP and bank account numbers are plain text for now (test data only).
They get encrypted at rest before any real company's data goes in.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TenantScopedModel
from apps.sites.models import Site


class Employee(TenantScopedModel):
    class EmploymentType(models.TextChoices):
        PKWTT        = "pkwtt",        "PKWTT (tetap)"
        PKWT         = "pkwt",         "PKWT (kontrak)"
        HARIAN_LEPAS = "harian_lepas", "Harian lepas"
        BORONGAN     = "borongan",     "Borongan"

    class PayType(models.TextChoices):
        MONTHLY = "monthly", "Bulanan"
        DAILY   = "daily",   "Harian"
        PIECE   = "piece",   "Per pekerjaan"

    class PTKP(models.TextChoices):
        TK0 = "TK/0", "TK/0"
        TK1 = "TK/1", "TK/1"
        TK2 = "TK/2", "TK/2"
        TK3 = "TK/3", "TK/3"
        K0  = "K/0",  "K/0"
        K1  = "K/1",  "K/1"
        K2  = "K/2",  "K/2"
        K3  = "K/3",  "K/3"

    class Status(models.TextChoices):
        ACTIVE   = "active",   "Aktif"
        RESIGNED = "resigned", "Keluar"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee_no     = models.CharField(max_length=30, verbose_name="No. Karyawan")
    full_name       = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    nik             = models.CharField(max_length=16, blank=True, default="", verbose_name="NIK (KTP)")
    npwp            = models.CharField(max_length=20, blank=True, default="", verbose_name="NPWP")
    ptkp_status     = models.CharField(max_length=4, choices=PTKP.choices, default=PTKP.TK0, verbose_name="Status PTKP")
    join_date       = models.DateField(verbose_name="Tanggal Masuk")
    end_date        = models.DateField(null=True, blank=True, verbose_name="Tanggal Keluar")
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default=EmploymentType.PKWTT,
                                       verbose_name="Jenis Hubungan Kerja")
    pay_type        = models.CharField(max_length=20, choices=PayType.choices, default=PayType.MONTHLY,
                                       verbose_name="Jenis Upah")
    base_rate       = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                          verbose_name="Tarif Dasar",
                                          help_text="Bulanan: gaji pokok sebulan. Harian: upah per hari.")
    bank_name         = models.CharField(max_length=50, blank=True, default="", verbose_name="Bank")
    bank_account_no   = models.CharField(max_length=30, blank=True, default="", verbose_name="No. Rekening")
    bank_account_name = models.CharField(max_length=200, blank=True, default="", verbose_name="Nama Pemilik Rekening")
    bpjs_kesehatan_no = models.CharField(max_length=20, blank=True, default="", verbose_name="No. BPJS Kesehatan")
    bpjs_tk_no        = models.CharField(max_length=20, blank=True, default="", verbose_name="No. BPJS Ketenagakerjaan")
    phone             = models.CharField(max_length=20, blank=True, default="", verbose_name="No. HP")

    sites         = models.ManyToManyField(Site, blank=True, related_name="employees", verbose_name="Lokasi Kerja")
    default_site  = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+", verbose_name="Lokasi Utama")
    default_shift = models.ForeignKey("sites.Shift", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+", verbose_name="Shift Utama")
    mandor        = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="crew", verbose_name="Mandor")
    # The login this worker uses to clock in (phone + PIN login comes in G2).
    user          = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name="employee")
    # Phone + PIN login (G2a). One phone number logs in one worker.
    login_phone         = models.CharField(max_length=20, null=True, blank=True, unique=True,
                                           verbose_name="No. HP Login")
    must_change_pin     = models.BooleanField(default=False, verbose_name="Wajib Ganti PIN")
    pin_failed_attempts = models.PositiveSmallIntegerField(default=0)
    pin_locked_until    = models.DateTimeField(null=True, blank=True)
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Status")
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Karyawan"
        verbose_name_plural = "Karyawan"
        ordering            = ["full_name"]
        unique_together     = [("organization", "employee_no")]

    def __str__(self):
        return f"{self.employee_no} — {self.full_name}"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def candidate_sites(self):
        """
        The sites this worker may clock in at: the assigned sites plus the
        default site. A worker with none assigned may use any active site of
        their own company (small companies often don't bother assigning).
        """
        active = Site.objects.filter(organization_id=self.organization_id, is_active=True)
        ids = set(self.sites.values_list("id", flat=True))
        if self.default_site_id:
            ids.add(self.default_site_id)
        return list(active.filter(id__in=ids) if ids else active)
