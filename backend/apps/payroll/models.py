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
  EmployeeLoan     G13 part 2: a loan or kasbon entered once; every draft run deducts it (loans.py).
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
    meal_late_after   = models.TimeField(default=time(19, 0), verbose_name="Pulang malam setelah jam")  # G12d; G12h.1: at or after (label kept: no migration)
    # G12e: DKCB's 'Note' sheet, each one a company setting
    meal_midnight_extra = models.BooleanField(default=False, verbose_name="Uang makan lagi jika lewat 00:00")
    breakfast_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"),
                                              verbose_name="Uang sarapan", help_text="0 = tidak ada")
    breakfast_before  = models.TimeField(default=time(7, 0), verbose_name="Sarapan jika masuk sebelum jam")
    overtime_min_minutes = models.PositiveSmallIntegerField(default=30, verbose_name="Lembur mulai dihitung (menit)")
    overtime_daily_cap_minutes = models.PositiveSmallIntegerField(                                      # G12g
        null=True, blank=True, default=None, verbose_name="Batas lembur per hari kerja saat setujui massal (menit)",
        help_text="Kosong = tanpa batas: lembur disetujui sesuai jam absen.")
    night_ot_rules    = models.JSONField(default=list, blank=True, verbose_name="Masuk siang setelah lembur malam",
                                         help_text='[{"until": "01:59", "start": "10:00"}, ...], see night_rules.py')
    late_fine_per_minute   = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    late_tolerance_minutes = models.PositiveSmallIntegerField(default=0)
    # G17-1: DKCB Note sheet "tidak clock out tp ada clock in / tidak clock in tp ada clock out: potong 1/2 hari"
    single_tap_half_day = models.BooleanField(default=False, verbose_name="Tap sekali = potong ½ hari")
    # G13-4 (Anthony, 18 Nov 2026): "lebih dari 2 jam telat atau pulang cepat, langsung potong ½ hari"
    long_late_half_day_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True, default=None, verbose_name="Terlambat / pulang cepat lebih dari (menit) = potong ½ hari",
        help_text="Kosong = tidak dipakai. Menggantikan denda per menit untuk keterlambatan itu.")
    # G13-4: "sarapan dibayar jika masuk sebelum jam 7 pagi dan ada SPL" (SPL = overtime HR paid that day)
    breakfast_needs_overtime = models.BooleanField(default=False, verbose_name="Sarapan hanya jika hari itu ada lembur (SPL)")
    bpjs_base_includes_allowance = models.BooleanField(default=True)
    jkk_rate          = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0024"),
                                            help_text="0.0024 / 0.0054 / 0.0089 / 0.0127 / 0.0174 (kelompok risiko 1-5)")
    minimum_wage      = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                            verbose_name="UMK", help_text="0 = tidak dicek")
    # G16-1: Jaminan Pensiun, for employees ticked "Ikut JP"
    jp_employee_rate  = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0100"))
    jp_company_rate   = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0200"))
    jp_wage_cap       = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                            verbose_name="Batas upah JP",
                                            help_text="Dari surat BPJS Ketenagakerjaan, berubah tiap tahun. 0 = belum diisi")
    jp_employee_by_company = models.BooleanField(default=False, verbose_name="JP 1% karyawan ditanggung perusahaan")
    # G16-1: PPh 21 (Pak Holan, 20 Nov 2026); used by pph21_preview now, by the slip when PPh 21 is switched on
    pph21_late_reduces_bruto = models.BooleanField(default=True,
                                                   verbose_name="Potongan keterlambatan mengurangi bruto PPh 21")
    pph21_company_jht_in_bruto = models.BooleanField(
        default=True, verbose_name="JHT 2% karyawan yang ditanggung perusahaan masuk bruto PPh 21")
    pph21_company_jp_in_bruto = models.BooleanField(                                   # G16-5a (D78)
        default=True, verbose_name="JP 1% karyawan yang ditanggung perusahaan masuk bruto PPh 21")
    # G16-3: PPh 21 on the slip (off until the company is ready; locked payrolls never change)
    pph21_enabled = models.BooleanField(default=False, verbose_name="Hitung PPh 21 di slip")
    # G16-2: which month a payroll belongs to for PPh 21 (and so which payroll settles the year in December)
    # G17-E1: where overtime approval comes from (UU 27/2026 Pasal 116 ayat 1: a written / digital order)
    overtime_source = models.CharField(max_length=10, default="decision", verbose_name="Persetujuan lembur",
                                       choices=[("decision", "Keputusan HR per hari"), ("spl", "SPL")])
    # G16-5a (D76, D79): the law ("earliest") is the default for NEW companies; existing ones keep their choice.
    # A change is dated: periods ending on or after `since` follow the new rule, earlier ones the history.
    pph21_tax_month = models.CharField(max_length=12, default="earliest", verbose_name="Masa pajak ikut",
                                       choices=[("earliest", "Yang lebih dulu: dibayar atau periode selesai (aturan)"),
                                                ("paid", "Bulan dibayar"), ("period_end", "Bulan periode berakhir")])
    pph21_tax_month_since = models.DateField(null=True, blank=True,
                                             verbose_name="Masa pajak: berlaku untuk periode yang berakhir sejak")
    pph21_tax_month_history = models.JSONField(default=list, blank=True,
                                               verbose_name="Aturan masa pajak sebelumnya")
    # G16-4: hak akhir (UU 27/2026 Pasal 233 and 250)
    separation_pay_months = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1"),
                                                verbose_name="Uang pisah (bulan upah)",
                                                help_text="Bila PK / PP / PKB tidak mengatur: paling sedikit 1 bulan")
    small_business = models.BooleanField(default=False, verbose_name="Usaha mikro / kecil (hak akhir sesuai kesepakatan)")
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
            jp_employee=self.jp_employee_rate, jp_company=self.jp_company_rate,                # G16-1
            jp_wage_cap=self.jp_wage_cap, jp_by_company=self.jp_employee_by_company,
        )


class Pph21Opening(TenantScopedModel):
    """
    G16-2 (21 Nov 2026): saldo awal PPh 21 — one employee's tax months in a year before the company's first SeeGaji
    payroll (from the old book or Coretax bukti potong). Used by the yearly PPh 21 (pph21_year.py).
    """
    class Source(models.TextChoices):
        MANUAL = "manual", "Diisi HR"
        CSV    = "csv",    "File CSV"

    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="pph21_openings")
    year     = models.PositiveSmallIntegerField(verbose_name="Tahun")
    months   = models.PositiveSmallIntegerField(default=0, verbose_name="Jumlah bulan")
    # G16-5b (D77): which masa the saldo awal covers (1-12 of `year`), so SeeGaji can see an overlap or a gap with
    # its own payrolls; empty = only the count of months is known (the G16-2 way, still accepted, shown amber)
    masa_from = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Masa dari (bulan)")
    masa_to   = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Masa sampai (bulan)")
    bruto    = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"), verbose_name="Bruto")
    pph      = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"), verbose_name="PPh 21 dipotong")
    iuran    = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"),
                                   verbose_name="Iuran JHT/JP karyawan")
    note     = models.CharField(max_length=200, blank=True, default="")
    source   = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Saldo awal PPh 21"
        unique_together = [("employee", "year")]
        ordering = ["year", "employee__full_name"]


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
    # G16-5a: the masa pajak frozen when the payroll is locked (it is what was reported); never moves after that
    masa_year    = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Masa pajak (tahun)")
    masa_month   = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Masa pajak (bulan)")
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
    loan      = models.ForeignKey("EmployeeLoan", null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="repayments")                            # G13 part 2
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "Item pay run"
        ordering = ["kind", "created_at"]

    def _resolve_organization(self):
        return self.line.organization if self.line_id else None


class EmployeeLoan(TenantScopedModel):
    """G13 part 2 (15 Nov 2026): a loan or kasbon, entered once. See loans.py."""
    class Status(models.TextChoices):
        ACTIVE    = "active",    "Aktif"
        CANCELLED = "cancelled", "Dihentikan"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee    = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="loans")
    amount      = models.DecimalField(max_digits=14, decimal_places=2,
                                      verbose_name="Sisa yang harus dibayar (saat dicatat)")
    # G17-9: the figure in HR's book, for reading only: the loan's full amount (a running loan: what was lent at
    # the start), or what a kasbon asked for. Deductions always follow `amount`.
    original_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                          verbose_name="Jumlah awal / pengajuan (opsional)")
    installment = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Potongan per bulan")
    start_month = models.DateField(verbose_name="Mulai dipotong (bulan gaji, tanggal 1)")
    note        = models.CharField(max_length=120, blank=True, default="")
    status      = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "Pinjaman karyawan"
        ordering = ["start_month", "created_at"]

    @property
    def is_kasbon(self):
        return self.installment >= self.amount

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None


class FinalPay(TenantScopedModel):
    """G16-4 (23 Nov 2026): a hak akhir statement (final_pay.py). Inputs are kept; `result` is the calculation as
    saved; `run` is the payroll it was put on (Masukkan ke slip)."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee    = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="final_pays")
    end_date    = models.DateField(verbose_name="Hari terakhir bekerja")
    reason      = models.CharField(max_length=30, verbose_name="Alasan")
    upah        = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                      verbose_name="Upah (diisi HR; kosong = dari data Karyawan)")
    leave_days  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                      verbose_name="Sisa cuti (diisi HR; kosong = dari SeeGaji)")
    travel      = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Ongkos pulang")
    other_items = models.JSONField(default=list, blank=True, verbose_name="Hak lain")
    overrides   = models.JSONField(default=dict, blank=True, verbose_name="Angka yang diubah HR")
    deduct_loan = models.BooleanField(default=False, verbose_name="Lunasi pinjaman dari slip terakhir")
    note        = models.CharField(max_length=300, blank=True, default="")
    result      = models.JSONField(default=dict, blank=True)
    run         = models.ForeignKey(PayRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="final_pays")
    attached_at = models.DateTimeField(null=True, blank=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Hak akhir"
        ordering = ["-end_date", "-updated_at"]

    def _resolve_organization(self):
        return self.employee.organization if self.employee_id else None
