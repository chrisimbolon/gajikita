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
                 Soft notes (G18-0, UU 27/2026 Pasal 140 / 150) are kept apart and never counted.

Not here yet (later steps): PPh 21 (TER) - entered as a one-off deduction for now;
BPJS Kesehatan and Jaminan Pensiun via payroll; THR; final pay on resignation.
"""
from dataclasses import dataclass, field
from datetime import date as Date
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal

from .overtime import hourly_rate, overtime_pay, week_pattern, week_warnings

ZERO = Decimal("0")

# overtime modes
PP35 = "pp35"            # PP 35/2021: 1/173 of the monthly wage, 1.5x / 2x / rest-day tiers (the law)
FLAT = "flat"            # a fixed rupiah per hour (and per rest day) set by the company

# overtime rounding, applied per day
EXACT = "exact"          # minute by minute
NEAREST_HALF = "nearest_half"   # to the nearest half hour (15 minutes rounds up)
DOWN_HALF = "down_half"  # down to the last full half hour
HALF_DOWN = "half_down"  # G12e, DKCB: blocks of 15/45 minutes (1-15 -> 0, 16-45 -> 0.5, 46-60 -> 1)


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
    breakfast_allowance: Decimal = ZERO     # rupiah per breakfast (G12e)
    late_fine_per_minute: Decimal = ZERO    # rupiah per chargeable late / early-leave minute
    late_tolerance_minutes: int = 0         # taken off each day's late minutes
    bpjs_base_includes_allowance: bool = True   # BPJS TK wage = gaji pokok + tunjangan tetap
    jht_employee: Decimal = Decimal("0.02")
    jht_company: Decimal = Decimal("0.037")
    jkk: Decimal = Decimal("0.0024")       # risk group 1; set per company (DKCB: 0.0089, group 3)
    jkm: Decimal = Decimal("0.003")
    minimum_wage: Decimal = ZERO            # the company's UMK; 0 = don't check
    # G16-1: Jaminan Pensiun, for employees in JP only. The wage cap comes from BPJS every year (0 = none entered).
    jp_employee: Decimal = Decimal("0.01")
    jp_company: Decimal = Decimal("0.02")
    jp_wage_cap: Decimal = ZERO
    jp_by_company: bool = False             # the company pays the employee's JP 1% (not taken from pay)


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
    overtime_basis: Decimal = None           # PP 35 monthly wage when it isn't pokok + tunjangan (daily workers)
    check_minimum_wage: bool = True          # off for daily and piece-rate workers (G8b)
    jht_by_company: bool = False             # G13-3: the company pays the worker's JHT 2% (not taken from pay)
    bpjs_wage: Decimal = None                # G16-1: the wage reported to BPJS TK; None = gaji pokok + tunjangan tetap
    jp: bool = False                         # G16-1: in Jaminan Pensiun
    attendance_bonus: Decimal = ZERO         # G13-3: tunjangan kehadiran, paid only for a perfect period
    under_one_year: bool = None              # G18-0: masa kerja < 1 tahun at period end (None = unknown, no UMK note)


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
    breakfast_days: Decimal = ZERO           # G12e
    late_minutes: Decimal = ZERO             # chargeable minutes (see chargeable_late_minutes)
    unpaid_days: Decimal = ZERO              # unpaid leave + days before joining / after leaving
    piece_work: tuple = ()                   # Extra: Kubikasi TM, Kubikasi CP, Bongkar Semen...
    additions: tuple = ()                    # Extra: one-off earnings
    loan_repayment: Decimal = ZERO
    deductions: tuple = ()                   # Extra: one-off deductions (PPh 21 for now, "Lainnya")
    sick_days: Decimal = ZERO                # G13-3: approved sick leave (with a doctor's letter) in the period
    attendance_unpaid_days: Decimal = None   # G13-3: unpaid days for the attendance bonus (None = unpaid_days)
    reduced_pay_days: Decimal = ZERO         # G14-2: cuti melahirkan days in months 5-6 (calendar days)
    reduced_pay_pct: Decimal = Decimal("100")    # G14-2: what the company pays for them (law: 75)
    long_leave_days: Decimal = ZERO          # G14-2: melahirkan / keguguran / istirahat panjang days (attendance bonus)


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
    notes: list = field(default_factory=list)          # G18-0: soft notes, not warnings (not counted)
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
    if mode == HALF_DOWN:
        return int((Decimal(minutes) / 30).quantize(Decimal("1"), rounding=ROUND_HALF_DOWN)) * 30
    return minutes


def long_late_split(late, early, limit, room=2):
    """
    G13-4 (DKCB, Anthony 18 Nov 2026): "lebih dari 2 jam telat atau pulang cepat, langsung potong ½ hari".
    One day's late and early-leave minutes -> (late, early, halves). A part LONGER than `limit` minutes becomes
    ½ day unpaid instead of a per-minute fine (its minutes become 0); late and early both long -> 2 halves.
    limit None / 0 = rule off. room = halves this day may still take (a one-tap ½ day or an unpaid ½-day permit
    already took one): a day is never cut more than one whole day; a long part with no room is fined per minute.
    Used by the payroll (payrun.collect_numbers) and by "Siap gajian?" (checklist), so both always agree.
    """
    late, early, halves = int(late or 0), int(early or 0), 0
    if not limit:
        return late, early, 0
    if late > limit and halves < room:
        late, halves = 0, halves + 1
    if early > limit and halves < room:
        early, halves = 0, halves + 1
    return late, early, halves


def halves_text(halves):
    """1 -> '½', 2 -> '1', 3 -> '1½'."""
    whole, half = divmod(int(halves), 2)
    return (str(whole) if whole else "") + ("½" if half else "") or "0"


def minutes_text(minutes):
    """120 -> '2 jam', 90 -> '90 menit'."""
    return f"{minutes // 60} jam" if minutes and minutes % 60 == 0 else f"{minutes} menit"


def chargeable_late_minutes(days, tolerance):
    """days: (late_minutes, early_leave_minutes) per day. The tolerance comes off each day's late minutes."""
    return sum(max(0, int(late) - tolerance) + max(0, int(early)) for late, early in days)


def daily_rate(base_salary, divisor):
    return D(base_salary) / Decimal(divisor)


def bpjs_wage(terms, rules):
    if terms.bpjs_wage is not None and D(terms.bpjs_wage) > 0:          # G16-1: the wage reported to BPJS
        return D(terms.bpjs_wage)
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

def _days(n):
    """1 -> "1", 0.5 -> "½", 1.5 -> "1½" (days and minutes as HR writes them)."""
    n = D(n)
    whole, half = int(n), n - int(n) == D("0.5")
    if n == int(n):
        return str(int(n))
    return (f"{whole}½" if whole else "½") if half else f"{n:g}".replace(".", ",")


def attendance_lost(late_minutes, sick_days, unpaid_days, long_leave_days=0):
    """
    G13-3: why the tunjangan kehadiran is not paid this period ([] = paid). DKCB's Note sheet: "no late, no MC,
    no UL". Late = chargeable late / early-leave minutes (after the tolerance; forgiven days don't count);
    MC = sick leave with a doctor's letter (sick without one is UL anyway); UL = any unpaid day, absent or
    ½ day included, and days before joining / after leaving.
    """
    why = []
    if D(late_minutes) > 0:
        why.append(f"terlambat / pulang cepat {_days(late_minutes)} menit")
    if D(sick_days) > 0:
        why.append(f"sakit {_days(sick_days)} hari")
    if D(unpaid_days) > 0:
        why.append(f"tidak masuk tanpa upah {_days(unpaid_days)} hari")
    if D(long_leave_days) > 0:                                                         # G14-2
        why.append(f"cuti melahirkan / istirahat {_days(long_leave_days)} hari")
    return why


BASE_SHARE_MIN = Decimal("0.75")        # UU No. 27/2026 Pasal 150


def _rp(value):
    return f"Rp {rupiah(value):,.0f}".replace(",", ".")


def serves_under_one_year(join_date, on):
    """G18-0: True while the worker has been at the company less than 1 year on `on` (UU 27/2026 Pasal 140(1))."""
    try:
        anniversary = join_date.replace(year=join_date.year + 1)
    except ValueError:                                   # joined 29 Feb
        anniversary = Date(join_date.year + 1, 3, 1)
    return on < anniversary


def wage_notes(base, fixed_allowance, minimum_wage, under_one_year):
    """
    G18-0 (19 Nov 2026): soft notes from UU No. 27 Tahun 2026, for a monthly wage. They never change an amount.
      Pasal 150: gaji pokok at least 75% of gaji pokok + tunjangan tetap (only when there is a tunjangan tetap).
      Pasal 140: UMK is the lowest monthly wage (pokok + tunjangan tetap) for masa kerja < 1 tahun only.
    """
    notes = []
    base, allowance = D(base), D(fixed_allowance)
    total = base + allowance
    if base > 0 and allowance > 0 and base < total * BASE_SHARE_MIN:
        share = int(base * 100 / total)
        notes.append(f"Info: gaji pokok {_rp(base)} = {share}% dari gaji pokok + tunjangan tetap ({_rp(total)}). "
                     f"UU No. 27/2026 Pasal 150: gaji pokok paling sedikit 75%.")
    umk = D(minimum_wage or 0)
    if under_one_year and umk > 0 and total < umk:
        notes.append(f"Info: masa kerja belum 1 tahun, gaji pokok + tunjangan tetap {_rp(total)} di bawah UMK "
                     f"{_rp(umk)}. UU No. 27/2026 Pasal 140: UMK berlaku untuk masa kerja kurang dari 1 tahun.")
    return notes


def calculate(terms, period, rules):
    slip = Payslip()
    base = D(terms.base_salary)
    monthly_wage = base + D(terms.fixed_allowance)
    basis = D(terms.overtime_basis) if terms.overtime_basis is not None else monthly_wage

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
    earn("breakfast", "Uang sarapan", D(period.breakfast_days) * D(rules.breakfast_allowance),
         quantity=D(period.breakfast_days), unit="hari", rate=D(rules.breakfast_allowance))
    for x in tuple(period.piece_work) + tuple(terms.monthly_extras) + tuple(period.additions):
        earn(x.code, x.label, x.amount, quantity=x.quantity, unit=x.unit, rate=x.rate)
    if D(terms.attendance_bonus) > 0:                                                  # G13-3
        unpaid_for_bonus = period.unpaid_days if period.attendance_unpaid_days is None else period.attendance_unpaid_days
        why = attendance_lost(period.late_minutes, period.sick_days, unpaid_for_bonus, period.long_leave_days)
        if why:
            slip.warnings.append(f"Tunjangan kehadiran Rp {rupiah(terms.attendance_bonus):,.0f} hangus: "
                                 .replace(",", ".") + ", ".join(why) + ".")
        else:
            earn("attendance_bonus", "Tunjangan kehadiran", terms.attendance_bonus)

    # deductions
    deduct("late", "Potongan keterlambatan", D(period.late_minutes) * D(rules.late_fine_per_minute),
           quantity=D(period.late_minutes), unit="menit", rate=D(rules.late_fine_per_minute))
    per_day = daily_rate(base, rules.daily_divisor)
    deduct("unpaid_leave", "Potongan izin tanpa upah", D(period.unpaid_days) * per_day,       # G21-3a (D72)
           quantity=D(period.unpaid_days), unit="hari", rate=rupiah(per_day))
    pct = D(period.reduced_pay_pct)
    if D(period.reduced_pay_days) > 0 and pct < 100:                     # G14-2: UU 27/2026 Pasal 123 ayat 3
        cut_per_day = daily_rate(monthly_wage, rules.daily_divisor) * (100 - pct) / 100
        deduct("maternity_cut", f"Upah cuti melahirkan bulan ke-5–6 (dibayar {pct:.0f}%)",
               D(period.reduced_pay_days) * cut_per_day, quantity=D(period.reduced_pay_days), unit="hari",
               rate=rupiah(cut_per_day))
    wage = bpjs_wage(terms, rules)
    if terms.bpjs_tk:
        if terms.jht_by_company:                                                       # G13-3
            amount = rupiah(wage * rules.jht_employee)
            if amount:
                slip.employer.append(SlipLine("jht_employee_company", "JHT 2% karyawan (ditanggung perusahaan)",
                                              amount, rate=rules.jht_employee))
        else:
            deduct("jht_employee", "Iuran BPJS Ketenagakerjaan (JHT 2%)", wage * rules.jht_employee)
        for code, label, rate in (("jht_company", "JHT perusahaan", rules.jht_company),
                                  ("jkk", "JKK", rules.jkk), ("jkm", "JKM", rules.jkm)):
            amount = rupiah(wage * rate)
            if amount:
                slip.employer.append(SlipLine(code, label, amount, rate=rate))
        if terms.jp:                                                                   # G16-1: Jaminan Pensiun
            cap = D(rules.jp_wage_cap or 0)
            jp_wage = min(wage, cap) if cap > 0 else wage
            if rules.jp_by_company:
                amount = rupiah(jp_wage * rules.jp_employee)
                if amount:
                    slip.employer.append(SlipLine("jp_employee_company", "JP 1% karyawan (ditanggung perusahaan)",
                                                  amount, rate=rules.jp_employee))
            else:
                deduct("jp_employee", "Iuran Jaminan Pensiun (JP 1%)", jp_wage * rules.jp_employee)
            amount = rupiah(jp_wage * rules.jp_company)
            if amount:
                slip.employer.append(SlipLine("jp_company", "JP perusahaan", amount, rate=rules.jp_company))
    else:
        slip.warnings.append("Belum terdaftar BPJS Ketenagakerjaan.")
    deduct("loan", "Pinjaman", period.loan_repayment)
    for x in period.deductions:
        deduct(x.code, x.label, x.amount, quantity=x.quantity, unit=x.unit, rate=x.rate)

    if terms.check_minimum_wage:                                                       # G18-0: soft, not a warning
        slip.notes += wage_notes(base, terms.fixed_allowance, rules.minimum_wage, terms.under_one_year)

    slip.gross = sum((l.amount for l in slip.earnings), ZERO)
    slip.total_deductions = sum((l.amount for l in slip.deductions), ZERO)
    slip.net = slip.gross - slip.total_deductions
    if slip.net < 0:
        slip.warnings.append("Potongan lebih besar dari penghasilan: gaji bersih minus.")
    return slip


# ── pay periods ──

def _clamp(year, month, day):
    from calendar import monthrange
    return Date(year, month, min(day, monthrange(year, month)[1]))


def period_for(year, month, start_day):
    """
    The period that ENDS in this month. start_day 26: October = 26 Sep - 25 Oct.
    start_day 1: October = 1 - 31 Oct.
    """
    from datetime import timedelta
    if start_day <= 1:
        return Date(year, month, 1), _clamp(year, month, 31)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    start = _clamp(prev_year, prev_month, start_day)
    end = _clamp(year, month, start_day) - timedelta(days=1)
    return start, end


def pay_date_for(period_end, pay_day):
    """The first date after the period's end that falls on pay_day (end 25 Oct, pay day 5 -> 5 Nov)."""
    candidate = _clamp(period_end.year, period_end.month, pay_day)
    if candidate > period_end:
        return candidate
    year, month = (period_end.year + 1, 1) if period_end.month == 12 else (period_end.year, period_end.month + 1)
    return _clamp(year, month, pay_day)
