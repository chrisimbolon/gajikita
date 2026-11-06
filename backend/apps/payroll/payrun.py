# =============================================================================
# === backend/apps/payroll/payrun.py ===
# =============================================================================
"""
Running payroll for a company (G8b part 1, 1 Nov 2026): the glue between the
database and the pure engine.

  collect_numbers()  one employee's period, from attendance and leave:
                     present days, absent days, unpaid leave, days outside employment,
                     approved overtime per day, late / early minutes, meal days,
                     days still waiting in Perlu Tinjau
  create_run()       a new draft run with a line per employee (recurring items copied
                     from each person's previous run), then calculate_run()
  calculate_run()    refresh the numbers from attendance and recalculate every slip
  lock_run() / reopen_run()   locking also locks those attendance days (is_locked)
"""
from collections import Counter, defaultdict
from datetime import date as Date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.attendance.day_status import Status
from apps.attendance.models import AttendanceDay
from apps.attendance.rekap_codes import day_cell, outside_cell
from apps.attendance.review import evaluate, evaluate_missing
from apps.core.audit import record_audit
from apps.employees.models import Employee
from . import meals                                                     # G12d
from apps.leave.models import LeaveRequest
from apps.leave.rules import UNPAID

from . import engine
from .models import PayrollSettings, PayRun, PayRunItem, PayRunLine

MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]
# what HR may correct on a line, with the plain words the page shows
OVERRIDE_FIELDS = {
    "overtime_hours": "Jam lembur", "rest_days_worked": "Hari lembur libur", "meal_days": "Hari uang makan",
    "late_minutes": "Menit terlambat", "unpaid_days": "Hari potong gaji",
}


class PayrollError(Exception):
    pass


def _dates(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def employees_in_period(org, start, end):
    return (Employee.objects.filter(organization=org, join_date__lte=end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
            .filter(Q(status=Employee.Status.ACTIVE) | Q(end_date__isnull=False))
            .select_related("default_shift").order_by("full_name"))


def _days_by_employee(org, start, end, employee_ids):
    days = defaultdict(dict)
    qs = (AttendanceDay.objects.filter(organization=org, employee_id__in=employee_ids, date__gte=start, date__lte=end)
          .select_related("employee", "employee__default_shift", "shift").prefetch_related("events__site"))
    for d in qs:
        days[d.employee_id][d.date] = d
    return days


def _leaves_by_employee(org, start, end, employee_ids):
    """{employee_id: {date: (kind, label)}} for approved leave in the period."""
    out = defaultdict(dict)
    qs = LeaveRequest.objects.filter(organization=org, employee_id__in=employee_ids, status=LeaveRequest.Status.APPROVED,
                                     start_date__lte=end, end_date__gte=start)
    for l in qs:
        for d in _dates(max(l.start_date, start), min(l.end_date, end)):
            out[l.employee_id][d] = (l.kind, l.label)
    return out


def collect_numbers(emp, start, end, cfg, days, leaves, now, cells=None):
    """The month's numbers for one employee. With cells=[], also one Rekap Absensi cell per day (G10)."""
    shift = emp.default_shift
    nums = {"working_days": 0, "present_days": 0, "absent_days": 0, "unpaid_leave_days": 0, "outside_days": 0, "paid_leave_days": 0,
            "overtime": [], "late_raw": [], "meal_days": 0, "review_days": 0, "leave": {}}
    leave_count = Counter()
    meal_rule = meals.rule_for(emp.meal_rule, cfg.meal_rule)              # G12d: per employee
    tz = timezone.get_current_timezone()
    for d in _dates(start, end):
        if d < emp.join_date or (emp.end_date and d > emp.end_date):
            nums["outside_days"] += 1
            if cells is not None:
                cells.append(outside_cell(d))
            continue
        working = shift is None or shift.is_working_day(d)
        if working:
            nums["working_days"] += 1
        day, leave = days.get(d), leaves.get(d)
        label = leave[1] if leave else ""
        r = evaluate(day, now, leave=label) if day else evaluate_missing(emp, d, now, leave=label)
        if r.status == Status.LEAVE:
            leave_count[label] += 1
            if leave[0] == UNPAID:
                nums["unpaid_leave_days"] += 1
            else:
                nums["paid_leave_days"] += 1
        elif r.status == Status.ABSENT or (r.status == Status.REJECTED and working):
            nums["absent_days"] += 1
        elif r.first_in:
            nums["present_days"] += 1
        if day is not None and r.needs_review and not day.decision:
            nums["review_days"] += 1
        late = r.late_minutes if Status.LATE in r.tags else 0
        early = r.early_minutes if Status.EARLY_OUT in r.tags else 0
        if late or early:
            nums["late_raw"].append([late, early])
        ot = day.overtime_approved_minutes if (day is not None and day.decision == "approved") else 0
        if ot:
            nums["overtime"].append({"date": d.isoformat(), "minutes": ot, "rest_day": not working})
        if meals.earns_meal(meal_rule, d, r.first_in, r.last_out, r.status == Status.REJECTED, ot,
                            cfg.meal_late_after, tz):
            nums["meal_days"] += 1
        if cells is not None:
            cells.append(day_cell(d, r, day, leave, ot))
    nums["leave"] = dict(leave_count)
    nums["late_minutes"] = engine.chargeable_late_minutes(nums["late_raw"], cfg.late_tolerance_minutes)
    nums["unpaid_days"] = nums["absent_days"] + nums["unpaid_leave_days"] + nums["outside_days"]
    return nums


def _dec(value):
    return Decimal(str(value)) if value not in (None, "") else None


def calculate_line(line, cfg):
    """Engine inputs from the line's numbers + HR's corrections + items -> the slip, stored on the line."""
    emp = line.employee
    shift = emp.default_shift
    working_days = shift.working_days if shift else "123456"
    rules = cfg.rules(working_days)
    nums, fix = line.auto or {}, line.override or {}

    def pick(key):
        return _dec(fix[key]) if key in fix else _dec(nums.get(key, 0)) or Decimal("0")

    base, allowance = Decimal(emp.base_rate or 0), Decimal(emp.fixed_allowance or 0)
    unpaid = pick("unpaid_days")
    terms_kw = {}
    if emp.pay_type == Employee.PayType.DAILY:
        pattern = engine.week_pattern(working_days)
        days_paid = Decimal(nums.get("present_days", 0)) + Decimal(nums.get("paid_leave_days", 0))
        terms_kw = {"overtime_basis": base * {6: 25, 5: 21}[pattern] + allowance, "check_minimum_wage": False}
        base, unpaid = base * days_paid, Decimal("0")
    elif emp.pay_type == Employee.PayType.PIECE:
        terms_kw = {"check_minimum_wage": False, "overtime_eligible": False}
        base = Decimal("0")
    terms = engine.EmployeeTerms(base_salary=base, fixed_allowance=allowance, bpjs_tk=emp.bpjs_tk_enrolled,
                                 overtime_eligible=terms_kw.pop("overtime_eligible", emp.overtime_eligible), **terms_kw)

    items = list(line.items.all())
    to_extra = lambda i: engine.Extra(i.code, i.label, i.amount, quantity=i.quantity, unit=i.unit)
    if "overtime_hours" in fix:
        ot_days, ot_hours, rest_days = (), pick("overtime_hours"), pick("rest_days_worked")
    else:
        ot_days = tuple(engine.OvertimeDay(Date.fromisoformat(o["date"]), int(o["minutes"]),
                                           bool(o["rest_day"])) for o in nums.get("overtime", []))
        ot_hours = rest_days = None
    period = engine.PeriodInput(
        overtime_days=ot_days, overtime_hours=ot_hours, rest_days_worked=rest_days,
        meal_days=pick("meal_days"), late_minutes=pick("late_minutes"), unpaid_days=unpaid,
        additions=tuple(to_extra(i) for i in items if i.kind == PayRunItem.Kind.EARNING),
        deductions=tuple(to_extra(i) for i in items if i.kind == PayRunItem.Kind.DEDUCTION),
    )
    slip = engine.calculate(terms, period, rules)
    if nums.get("review_days"):
        slip.warnings.insert(0, f"{nums['review_days']} hari absensi belum ditinjau HR di periode ini.")
    worked_days, absent = nums.get("working_days", 0), nums.get("absent_days", 0)
    if worked_days and absent * 2 >= worked_days:
        slip.warnings.insert(0, f"Tidak hadir {absent} dari {worked_days} hari kerja di periode ini.")

    as_json = lambda lines: [{"code": l.code, "label": l.label, "amount": str(l.amount),
                              "quantity": str(l.quantity) if l.quantity is not None else None, "unit": l.unit}
                             for l in lines]
    line.result = {"earnings": as_json(slip.earnings), "deductions": as_json(slip.deductions),
                   "employer": as_json(slip.employer), "warnings": slip.warnings}
    line.gross, line.deductions, line.net = slip.gross, slip.total_deductions, slip.net
    line.employer_cost = sum((l.amount for l in slip.employer), Decimal("0"))
    line.warning_count = len(slip.warnings)
    return line


def _settings(run):
    return PayrollSettings.for_org(run.organization)


def calculate_run(run, now=None, refresh=True):
    """Re-read attendance and leave (unless refresh=False) and recalculate every line. Adds newly hired people."""
    if run.is_locked:
        raise PayrollError("Payroll ini sudah dikunci. Buka kunci dulu untuk menghitung ulang.")
    now = now or timezone.now()
    cfg = _settings(run)
    with transaction.atomic():
        employees = list(employees_in_period(run.organization, run.period_start, run.period_end))
        existing = {l.employee_id: l for l in run.lines.select_related("employee", "employee__default_shift")}
        for emp in employees:
            if emp.id not in existing:
                existing[emp.id] = _new_line(run, emp)
        ids = list(existing)
        days = _days_by_employee(run.organization, run.period_start, run.period_end, ids) if refresh else {}
        leaves = _leaves_by_employee(run.organization, run.period_start, run.period_end, ids) if refresh else {}
        for line in existing.values():
            if refresh:
                line.auto = collect_numbers(line.employee, run.period_start, run.period_end, cfg,
                                            days.get(line.employee_id, {}), leaves.get(line.employee_id, {}), now)
            calculate_line(line, cfg)
            line.save()
        run.calculated_at = now
        run.save(update_fields=["calculated_at"])
    return run


def _new_line(run, emp):
    line = PayRunLine.objects.create(organization=run.organization, run=run, employee=emp)
    previous = (PayRunLine.objects.filter(employee=emp, run__period_start__lt=run.period_start)
                .order_by("-run__period_start").first())
    if previous:
        for item in previous.items.filter(recurring=True):
            PayRunItem.objects.create(organization=run.organization, line=line, kind=item.kind, code=item.code,
                                      label=item.label, amount=item.amount, quantity=item.quantity, unit=item.unit,
                                      recurring=True, note=item.note)
    return line


def create_run(org, year, month, actor, now=None):
    cfg = PayrollSettings.for_org(org)
    start, end = engine.period_for(year, month, cfg.period_start_day)
    if PayRun.objects.filter(organization=org, period_start=start).exists():
        raise PayrollError(f"Payroll {MONTHS[month - 1]} {year} sudah ada.")
    with transaction.atomic():
        run = PayRun.objects.create(organization=org, name=f"Payroll {MONTHS[month - 1]} {year}", period_start=start,
                                    period_end=end, pay_date=engine.pay_date_for(end, cfg.pay_day),
                                    created_by=actor if getattr(actor, "is_authenticated", False) else None)
        record_audit(organization=org, actor=actor, action="payroll.create", target=run,
                     summary=f"{run.name} dibuat ({start:%d-%m-%Y} s/d {end:%d-%m-%Y})")
        calculate_run(run, now)
    return run


def lock_run(run, actor, note=""):
    if run.is_locked:
        raise PayrollError("Payroll ini sudah dikunci.")
    with transaction.atomic():
        calculate_run(run)                       # lock what the attendance says right now
        run.status, run.locked_by, run.locked_at = PayRun.Status.LOCKED, actor, timezone.now()
        run.save(update_fields=["status", "locked_by", "locked_at"])
        n = AttendanceDay.objects.filter(organization=run.organization, date__gte=run.period_start,
                                         date__lte=run.period_end,
                                         employee_id__in=run.lines.values("employee_id")).update(is_locked=True)
        record_audit(organization=run.organization, actor=actor, action="payroll.lock", target=run,
                     summary=f"{run.name} dikunci ({n} hari absensi ikut dikunci)", note=note)
    return run


def reopen_run(run, actor, note):
    if not run.is_locked:
        raise PayrollError("Payroll ini belum dikunci.")
    if not (note or "").strip():
        raise PayrollError("Tulis alasan membuka kunci.")
    with transaction.atomic():
        run.status, run.locked_by, run.locked_at = PayRun.Status.DRAFT, None, None
        run.save(update_fields=["status", "locked_by", "locked_at"])
        AttendanceDay.objects.filter(organization=run.organization, date__gte=run.period_start,
                                     date__lte=run.period_end,
                                     employee_id__in=run.lines.values("employee_id")).update(is_locked=False)
        record_audit(organization=run.organization, actor=actor, action="payroll.reopen", target=run,
                     summary=f"{run.name} dibuka kembali", note=note)
    return run
