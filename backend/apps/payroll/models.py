# =============================================================================
# === backend/apps/payroll/models.py ===
# =============================================================================
"""
Payroll in the database (G8b part 1, 1 Nov 2026).

  PayrollSettings  one per company: period, overtime mode and rates, meal allowance,
                   late fine, BPJS JKK rate, UMK. Feeds engine.PayrollRules.
  PayRun           one pay period of one company: draft -> locked.
  PayRunLine       one employee in a run: the numbers taken from attendance and leave
                   ("auto"), HR's corrections ("override"), and the calculated slip.
  PayRunItem       an extra line on one employee's slip: per-m3 pay, an incentive, a loan
                   repayment, PPh 21, any deduction. "Recurring" items are copied into
                   the next run automatically (e.g. Insentif BPJS Kesehatan).
"""
import uuid
from datetime import time
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TenantScopedModel

from . import engine


class PayrollSettings(TenantScopedModel):
    class OvertimeMode(models.TextChoices):
        PP35 = engine.PP35, "Sesuai PP 35/2021"
        FLAT = engine.FLAT, "Tarif tetap perusahaan"

    class Rounding(models.TextChoices):
        EXACT        = engine.EXACT,        "Per menit"
        NEAREST_HALF = engine.NEAREST_HALF, "Dibulatkan ke 0,5 jam terdekat"
        DOWN_HALF    = engine.DOWN_HALF,    "Dibulatkan ke bawah per 0,5 jam"
        HALF_DOWN    = engine.HALF_DOWN,    "Blok 15/45 menit (1-15 = 0, 16-45 = 0,5, 46-60 = 1)"   # G12e

    class MealRule(models.TextChoices):
        NONE         = "none",         "Tidak ada"
        OVERTIME_DAY = "overtime_day", "Per hari lembur"
        PRESENT_DAY  = "present_day",  "Per hari hadir"
        LATE_OUT     = "late_out",     "Per hari pulang malam"          # G12d

    organization      = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE,
                                             related_name="payroll_settings")
    period_start_day  = models.PositiveSmallIntegerField(default=26, verbose_name="Periode mulai tanggal")
    pay_day           = models.PositiveSmallIntegerField(default=5, verbose_name="Tanggal gajian")
    daily_divisor     = models.PositiveSmallIntegerField(default=30, verbose_name="Pembagi gaji harian")
    overtime_mode     = models.CharField(max_length=10, choices=OvertimeMode.choices, default=OvertimeMode.PP35)
    overtime_rounding = models.CharField(max_length=15, choices=Rounding.choices, default=Rounding.EXACT)
    flat_overtime_hour = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    flat_rest_day     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    meal_rule         = models.CharField(max_length=15, choices=MealRule.choices, default=MealRule.NONE)
    meal_allowance    = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    meal_late_after   = models.TimeField(default=time(19, 0), verbose_name="Pulang malam mulai jam")   # G12d
    # G12e: DKCB's 'Note' sheet, each one a company setting
    meal_midnight_extra = models.BooleanField(default=False, verbose_name="Uang makan lagi jika lewat 00:00")
    breakfast_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"),
                                              verbose_name="Uang sarapan", help_text="0 = tidak ada")
    breakfast_before  = models.TimeField(default=time(7, 0), verbose_name="Sarapan jika masuk sebelum jam")
    overtime_min_minutes = models.PositiveSmallIntegerField(default=30, verbose_name="Lembur mulai dihitung (menit)")
    night_ot_rules    = models.JSONField(default=list, blank=True, verbose_name="Masuk siang setelah lembur malam",
                                         help_text='[{"until": "01:59", "start": "10:00"}, ...], see night_rules.py')
    late_fine_per_minute   = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    late_tolerance_minutes = models.PositiveSmallIntegerField(default=0)
    bpjs_base_includes_allowance = models.BooleanField(default=True)
    jkk_rate          = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0024"),
                                            help_text="0.0024 / 0.0054 / 0.0089 / 0.0127 / 0.0174 (kelompok risiko 1-5)")
    minimum_wage      = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                            verbose_name="UMK", help_text="0 = tidak dicek")
    # on the printed slip (G8b part 2)
    slip_address      = models.TextField(blank=True, default="", verbose_name="Alamat di slip")
    slip_place        = models.CharField(max_length=60, blank=True, default="", verbose_name="Tempat di slip")
    slip_signer       = models.CharField(max_length=60, blank=True, default="HRD", verbose_name="Penanda tangan slip")
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Pengaturan payroll"

    @classmethod
    def for_org(cls, organization):
        obj, _ = cls.objects.get_or_create(organization=organization)
        return obj

    def rules(self, working_days="123456"):
        return engine.PayrollRules(
            period_start_day=self.period_start_day, pay_day=self.pay_day, working_days=working_days,
            daily_divisor=self.daily_divisor, overtime_mode=self.overtime_mode,
            overtime_rounding=self.overtime_rounding, flat_overtime_hour=self.flat_overtime_hour,
            flat_rest_day=self.flat_rest_day, meal_allowance=self.meal_allowance,
            breakfast_allowance=self.breakfast_allowance,                                  # G12e
            late_fine_per_minute=self.late_fine_per_minute, late_tolerance_minutes=self.late_tolerance_minutes,
            bpjs_base_includes_allowance=self.bpjs_base_includes_allowance, jkk=self.jkk_rate,
            minimum_wage=self.minimum_wage,
        )


class PayRun(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT  = "draft",  "Draft"
        LOCKED = "locked", "Dikunci"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=60, verbose_name="Nama")          # "Payroll Oktober 2026"
    period_start = models.DateField()
    period_end   = models.DateField()
    pay_date     = models.DateField(null=True, blank=True)
    status       = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    calculated_at = models.DateTimeField(null=True, blank=True)
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    locked_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    locked_at    = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "Pay run"
        ordering = ["-period_start"]
        unique_together = [("organization", "period_start")]

    def __str__(self):
        return f"{self.name} ({self.period_start} - {self.period_end})"

    @property
    def is_locked(self):
        return self.status == self.Status.LOCKED


class PayRunLine(TenantScopedModel):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run       = models.ForeignKey(PayRun, on_delete=models.CASCADE, related_name="lines")
    employee  = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="pay_lines")
    auto      = models.JSONField(default=dict, blank=True)       # numbers from attendance and leave
    override  = models.JSONField(default=dict, blank=True)       # HR's corrections of those numbers
    note      = models.CharField(max_length=255, blank=True, default="")
    result    = models.JSONField(default=dict, blank=True)       # the calculated slip
    gross     = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    net       = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    employer_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    warning_count = models.PositiveSmallIntegerField(default=0)
    loan_balance  = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                        verbose_name="Sisa pinjaman (di slip)")       # until the loan module (G8b part 2)

    class Meta:
        verbose_name = verbose_name_plural = "Baris pay run"
        ordering = ["employee__full_name"]
        unique_together = [("run", "employee")]

    def _resolve_organization(self):
        return self.run.organization if self.run_id else None


class PayRunItem(TenantScopedModel):
    class Kind(models.TextChoices):
        EARNING   = "earning",   "Penghasilan"
        DEDUCTION = "deduction", "Potongan"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line      = models.ForeignKey(PayRunLine, on_delete=models.CASCADE, related_name="items")
    kind      = models.CharField(max_length=10, choices=Kind.choices)
    code      = models.SlugField(max_length=40)                  # "kubikasi_tm", "loan", "pph21"...
    label     = models.CharField(max_length=80)
    amount    = models.DecimalField(max_digits=14, decimal_places=2)
    quantity  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit      = models.CharField(max_length=15, blank=True, default="")
    recurring = models.BooleanField(default=False, verbose_name="Ulangi tiap bulan")
    note      = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "Item pay run"
        ordering = ["kind", "created_at"]

    def _resolve_organization(self):
        return self.line.organization if self.line_id else None
