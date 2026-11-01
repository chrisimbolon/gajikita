# =============================================================================
# === backend/apps/payroll/engine.py ===
# =============================================================================
"""
The payroll engine (G8a, 1 Nov 2026). Pure Python, no Django: one employee's
terms + one period's numbers + the company's rules go in, the payslip comes out.

Built against a real payroll run (PT DKCB, 26 Sep - 25 Oct 2026, 29 people):
tests/test_engine.py rebuilds every net pay in that register to the rupiah.

What goes in
  PayrollRules   the company's settings (overtime mode, late fine, divisor, BPJS rates...)
  EmployeeTerms  gaji pokok, fixed allowance, fixed monthly extras, BPJS enrolment
  PeriodInput    this period's numbers: overtime, meal days, late minutes, unpaid days,
                 piece-rate pay, loan repayment, one-off additions and deductions

What comes out
  Payslip        earning and deduction lines (each rounded to the rupiah, so the slip
                 adds up), gross, deductions, net, the employer's BPJS cost, and
                 compliance warnings. Warnings never stop a payroll run.

Not here yet (later steps): PPh 21 (TER) - entered as a one-off deduction for now;
BPJS Kesehatan and Jaminan Pensiun via payroll; THR; final pay on resignation.
"""
from dataclasses import dataclass, field
from datetime import date as Date
from decimal import ROUND_HALF_UP, Decimal

from .overtime import hourly_rate, overtime_pay, week_pattern, week_warnings

ZERO = Decimal("0")

# overtime modes
PP35 = "pp35"            # PP 35/2021: 1/173 of the monthly wage, 1.5x / 2x / rest-day tiers (the law)
FLAT = "flat"            # a fixed rupiah per hour (and per rest day) set by the company

# overtime rounding, applied per day
EXACT = "exact"          # minute by minute
NEAREST_HALF = "nearest_half"   # to the nearest half hour (15 minutes rounds up)
DOWN_HALF = "down_half"  # down to the last full half hour


def rupiah(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def D(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


@dataclass(frozen=True)
class PayrollRules:
    """One company's payroll settings. The defaults are the law where there is one."""
    period_start_day: int = 26              # the period runs from the 26th to the 25th
    pay_day: int = 5                        # paid on the 5th of the next month
    working_days: str = "123456"            # used for PP 35's 6-day / 5-day tiers
    daily_divisor: int = 30                 # unpaid leave per day = gaji pokok / 30
    overtime_mode: str = PP35
    overtime_rounding: str = EXACT
    flat_overtime_hour: Decimal = ZERO      # FLAT mode: rupiah per overtime hour on a working day
    flat_rest_day: Decimal = ZERO           # FLAT mode: rupiah per rest day / holiday worked
    meal_allowance: Decimal = ZERO          # rupiah per meal day
    late_fine_per_minute: Decimal = ZERO    # rupiah per chargeable late / early-leave minute
    late_tolerance_minutes: int = 0         # taken off each day's late minutes
    bpjs_base_includes_allowance: bool = True   # BPJS TK wage = gaji pokok + tunjangan tetap
    jht_employee: Decimal = Decimal("0.02")
    jht_company: Decimal = Decimal("0.037")
    jkk: Decimal = Decimal("0.0024")       # risk group 1; set per company (DKCB: 0.0089, group 3)
    jkm: Decimal = Decimal("0.003")
    minimum_wage: Decimal = ZERO            # the company's UMK; 0 = don't check


@dataclass(frozen=True)
class Extra:
    """A named amount: a fixed monthly extra, a piece-rate total, a one-off addition or deduction."""
    code: str
    label: str
    amount: Decimal
    quantity: Decimal = None    # e.g. m3 or tonnes, shown on the slip
    unit: str = ""
    rate: Decimal = None


@dataclass(frozen=True)
class EmployeeTerms:
    base_salary: Decimal
    fixed_allowance: Decimal = ZERO          # tunjangan tetap (counts for PP 35 and BPJS)
    monthly_extras: tuple = ()               # Extra, paid every period (e.g. Insentif BPJS Kesehatan)
    overtime_eligible: bool = True
    bpjs_tk: bool = True                     # enrolled in BPJS Ketenagakerjaan (JHT, JKK, JKM)


@dataclass(frozen=True)
class OvertimeDay:
    day: Date
    minutes: int
    rest_day: bool = False


@dataclass(frozen=True)
class PeriodInput:
    overtime_days: tuple = ()                # OvertimeDay, from approved attendance
    overtime_hours: Decimal = None           # FLAT mode only: hours HR already totalled (no daily detail)
    rest_days_worked: Decimal = None         # FLAT mode only, with overtime_hours
    meal_days: Decimal = ZERO
    late_minutes: Decimal = ZERO             # chargeable minutes (see chargeable_late_minutes)
    unpaid_days: Decimal = ZERO              # unpaid leave + days before joining / after leaving
    piece_work: tuple = ()                   # Extra: Kubikasi TM, Kubikasi CP, Bongkar Semen...
    additions: tuple = ()                    # Extra: one-off earnings
    loan_repayment: Decimal = ZERO
    deductions: tuple = ()                   # Extra: one-off deductions (PPh 21 for now, "Lainnya")


@dataclass
class SlipLine:
    code: str
    label: str
    amount: Decimal
    quantity: Decimal = None
    unit: str = ""
    rate: Decimal = None


@dataclass
class Payslip:
    earnings: list = field(default_factory=list)
    deductions: list = field(default_factory=list)
    employer: list = field(default_factory=list)       # company BPJS cost, not on the worker's net
    warnings: list = field(default_factory=list)
    gross: Decimal = ZERO
    total_deductions: Decimal = ZERO
    net: Decimal = ZERO

    def amount(self, code):
        return sum((l.amount for l in self.earnings + self.deductions + self.employer if l.code == code), ZERO)


# ── small rules, each testable on its own ──

def round_overtime(minutes, mode):
    minutes = int(minutes)
    if mode == NEAREST_HALF:
        return int((Decimal(minutes) / 30).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 30
    if mode == DOWN_HALF:
        return minutes // 30 * 30
    return minutes


def chargeable_late_minutes(days, tolerance):
    """days: (late_minutes, early_leave_minutes) per day. The tolerance comes off each day's late minutes."""
    return sum(max(0, int(late) - tolerance) + max(0, int(early)) for late, early in days)


def daily_rate(base_salary, divisor):
    return D(base_salary) / Decimal(divisor)


def bpjs_wage(terms, rules):
    return D(terms.base_salary) + (D(terms.fixed_allowance) if rules.bpjs_base_includes_allowance else ZERO)


def _pp35_amount(days, basis, rules):
    pattern = week_pattern(rules.working_days)
    hourly = hourly_rate(basis)
    total, warnings = ZERO, []
    for d in days:
        pay = overtime_pay(d.minutes, d.rest_day, pattern, hourly)
        total += pay.amount
        warnings += pay.warnings
    return total, warnings


# ── the engine ──

def calculate(terms, period, rules):
    slip = Payslip()
    base = D(terms.base_salary)
    basis = base + D(terms.fixed_allowance)

    def earn(code, label, amount, **kw):
        amount = rupiah(amount)
        if amount:
            slip.earnings.append(SlipLine(code, label, amount, **kw))

    def deduct(code, label, amount, **kw):
        amount = rupiah(amount)
        if amount:
            slip.deductions.append(SlipLine(code, label, amount, **kw))

    earn("base", "Gaji pokok", base)
    earn("fixed_allowance", "Tunjangan tetap", terms.fixed_allowance)

    # overtime
    days = [OvertimeDay(d.day, round_overtime(d.minutes, rules.overtime_rounding), d.rest_day)
            for d in period.overtime_days]
    if terms.overtime_eligible:
        if rules.overtime_mode == FLAT:
            if days:
                work_minutes = sum(d.minutes for d in days if not d.rest_day)
                hours = Decimal(work_minutes) / 60
                rest_days = Decimal(sum(1 for d in days if d.rest_day and d.minutes > 0))
            else:
                hours = D(period.overtime_hours)
                rest_days = D(period.rest_days_worked)
            earn("overtime", "Lembur", hours * D(rules.flat_overtime_hour), quantity=hours, unit="jam",
                 rate=D(rules.flat_overtime_hour))
            earn("overtime_rest_day", "Lembur hari libur", rest_days * D(rules.flat_rest_day),
                 quantity=rest_days, unit="hari", rate=D(rules.flat_rest_day))
            if days and basis > 0:
                legal, _ = _pp35_amount(days, basis, rules)
                paid = slip.amount("overtime") + slip.amount("overtime_rest_day")
                if legal > paid:
                    slip.warnings.append(f"Upah lembur Rp {paid:,.0f}; menurut PP 35/2021 Rp {legal:,.0f} "
                                         f"(kurang Rp {legal - paid:,.0f})".replace(",", "."))
        elif days:
            if basis > 0:
                amount, _ = _pp35_amount(days, basis, rules)
                minutes = sum(d.minutes for d in days)
                earn("overtime", "Lembur (PP 35/2021)", amount, quantity=Decimal(minutes) / 60, unit="jam")
            else:
                slip.warnings.append("Lembur tidak dihitung: gaji pokok belum diisi.")
        elif period.overtime_hours:
            slip.warnings.append("Lembur PP 35/2021 perlu rincian per hari; jam total saja tidak cukup.")
    if days:
        for d in days:
            limit = 4 * 60
            if not d.rest_day and d.minutes > limit:
                slip.warnings.append(f"{d.day:%d-%m}: lembur {d.minutes // 60} jam {d.minutes % 60} menit, "
                                     "melebihi 4 jam per hari (PP 35/2021)")
        slip.warnings += week_warnings([(d.day, d.minutes, d.rest_day) for d in days])

    earn("meal", "Uang makan", D(period.meal_days) * D(rules.meal_allowance), quantity=D(period.meal_days),
         unit="hari", rate=D(rules.meal_allowance))
    for x in tuple(period.piece_work) + tuple(terms.monthly_extras) + tuple(period.additions):
        earn(x.code, x.label, x.amount, quantity=x.quantity, unit=x.unit, rate=x.rate)

    # deductions
    deduct("late", "Potongan keterlambatan", D(period.late_minutes) * D(rules.late_fine_per_minute),
           quantity=D(period.late_minutes), unit="menit", rate=D(rules.late_fine_per_minute))
    per_day = daily_rate(base, rules.daily_divisor)
    deduct("unpaid_leave", "Potongan unpaid leave", D(period.unpaid_days) * per_day,
           quantity=D(period.unpaid_days), unit="hari", rate=rupiah(per_day))
    wage = bpjs_wage(terms, rules)
    if terms.bpjs_tk:
        deduct("jht_employee", "Iuran BPJS Ketenagakerjaan (JHT 2%)", wage * rules.jht_employee)
        for code, label, rate in (("jht_company", "JHT perusahaan", rules.jht_company),
                                  ("jkk", "JKK", rules.jkk), ("jkm", "JKM", rules.jkm)):
            amount = rupiah(wage * rate)
            if amount:
                slip.employer.append(SlipLine(code, label, amount, rate=rate))
    else:
        slip.warnings.append("Belum terdaftar BPJS Ketenagakerjaan.")
    deduct("loan", "Pinjaman", period.loan_repayment)
    for x in period.deductions:
        deduct(x.code, x.label, x.amount, quantity=x.quantity, unit=x.unit, rate=x.rate)

    if rules.minimum_wage and basis < D(rules.minimum_wage):
        slip.warnings.append(f"Gaji pokok + tunjangan tetap Rp {basis:,.0f} di bawah UMK "
                             f"Rp {D(rules.minimum_wage):,.0f}".replace(",", "."))

    slip.gross = sum((l.amount for l in slip.earnings), ZERO)
    slip.total_deductions = sum((l.amount for l in slip.deductions), ZERO)
    slip.net = slip.gross - slip.total_deductions
    if slip.net < 0:
        slip.warnings.append("Potongan lebih besar dari penghasilan: gaji bersih minus.")
    return slip
