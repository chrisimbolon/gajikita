# =============================================================================
# === backend/apps/attendance/attendance_log.py ===
# =============================================================================
"""
G20-1 (23 Nov 2026) — Log Kehadiran: for every attendance item, WHO, HOW MUCH, ON WHAT BASIS and AT WHAT COST,
like the SPL log (G17-E3) does for overtime. Read-only: it never changes a number.

One source of truth: every day comes from payrun.collect_numbers(trace=[]), the same function the payroll uses, so
the log can't disagree with the slip. Rupiah use the engine's own rates (fine per minute after the tolerance,
gaji pokok / pembagi per unpaid day, meal and breakfast allowance) and are rounded once per person, as the engine
does. Each person also says whether the payroll line still matches ("same"), needs Hitung ulang ("stale"), or
was corrected by HR on the line ("override"); "none" = no payroll for this period yet.

Tabs (G20-1): late, early, absent (UL / mangkir), meal. Half days and night shifts follow in G20-4.

"Late" (agreed 23 Nov): days past the SHIFT's grace (08:12 with 10 minutes grace = 12 minutes late, counted from
08:00). Arrivals inside the grace (08:01-08:10) are shown apart, for information. "Charged" = what the payroll
fines: minus the payroll tolerance, without forgiven / leave / ½-day-permit days, a long one as ½ day (G13-4).

GET /api/hr/attendance/log/?month=YYYY-MM
"""
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

ZERO = Decimal("0")

MEAL_RULES = {"none": "Tidak ada", "overtime_day": "Per hari lembur", "present_day": "Per hari hadir",
              "late_out": "Per hari pulang malam"}


def rupiah(value):
    """Decimal -> whole rupiah as a string, rounded half up once (as engine.rupiah)."""
    from apps.payroll.engine import rupiah as engine_rupiah
    return str(engine_rupiah(value))


def hhmm(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def _num(v):
    return Decimal(str(v if v not in (None, "") else 0))


@dataclass(frozen=True)
class Rates:
    """What one unit costs on this person's slip, with the payroll's own rules."""
    fine: Decimal = ZERO            # per chargeable late / early minute
    tolerance: int = 0              # payroll tolerance, off each late day
    long_limit: int = None          # G13-4: late / early longer than this = ½ day
    per_day: Decimal = ZERO         # an absent / unpaid-leave day: monthly gaji pokok / pembagi, daily = the day's wage
    half_day: Decimal = ZERO        # a ½ day cut: monthly per_day / 2; daily and piece workers: 0, as the payroll
    meal: Decimal = ZERO
    breakfast: Decimal = ZERO
    bonus: Decimal = ZERO           # tunjangan kehadiran (G13-3)


def rates_for(emp, cfg):
    base = Decimal(emp.base_rate or 0)
    kind = getattr(emp, "pay_type", "monthly")
    if kind == "daily":
        per_day, half = base, ZERO
    elif kind == "piece":
        per_day, half = ZERO, ZERO
    else:
        per_day = base / Decimal(cfg.daily_divisor or 30)
        half = per_day / 2
    return Rates(fine=Decimal(cfg.late_fine_per_minute or 0), tolerance=int(cfg.late_tolerance_minutes or 0),
                 long_limit=cfg.long_late_half_day_minutes, per_day=per_day, half_day=half,
                 meal=Decimal(cfg.meal_allowance or 0), breakfast=Decimal(cfg.breakfast_allowance or 0),
                 bonus=Decimal(getattr(emp, "attendance_bonus", 0) or 0))


# ── pure: one person's days -> the rows of each tab ──

def _half_text(limit):
    from apps.payroll.engine import minutes_text
    return f"Aturan: lebih dari {minutes_text(limit or 0)} = ½ hari"


def late_days(trace, rates):
    """Days past the shift's grace, and arrivals inside it (basis "grace", no money)."""
    out = []
    for t in trace:
        base = {"date": t["date"].isoformat(), "day_id": t["day_id"], "in": hhmm(t["first_in"]),
                "out": hhmm(t["last_out"])}
        if t["late_raw"] > 0:
            charged, half = 0, bool(t["late_half"])
            if t["late_tag"]:
                charged = max(0, t["late"] - rates.tolerance) if t["late"] else 0
                if half:
                    basis, label = "rule_half", _half_text(rates.long_limit)
                elif charged == 0:
                    basis, label = "tolerance", f"Dalam toleransi denda ({rates.tolerance} menit)"
                elif t["hr_fixed"]:
                    basis, label = "hr_time", "Jam dikoreksi HR"
                else:
                    basis, label = "taps", "Dari tap"
            elif t["forgiven"]:
                basis, label = "forgiven", "Dimaafkan HR"
            elif t["leave_label"]:
                basis, label = "leave", f"Cuti ({t['leave_label']})"
            elif t["half_leave"]:
                basis, label = "half_leave", "Izin / cuti ½ hari"
            else:
                basis, label = "not_counted", "Tidak dihitung"
            money = charged * rates.fine + (rates.half_day if half else ZERO)
            out.append({**base, "minutes": t["late_raw"], "charged": charged, "half": half, "amount": money,
                        "basis": basis, "label": label})
        elif t["inside_grace"] > 0 and not t["leave_label"]:
            out.append({**base, "minutes": t["inside_grace"], "charged": 0, "half": False, "amount": ZERO,
                        "basis": "grace", "label": "Dalam toleransi shift"})
    return out


def early_days(trace, rates):
    out = []
    for t in trace:
        if t["early_raw"] <= 0:
            continue
        charged, half = 0, bool(t["early_half"])
        if t["early_tag"]:
            charged = t["early"] or 0
            if half:
                basis, label = "rule_half", _half_text(rates.long_limit)
            elif t["hr_fixed"]:
                basis, label = "hr_time", "Jam dikoreksi HR"
            else:
                basis, label = "taps", "Dari tap"
        elif t["forgiven"]:
            basis, label = "forgiven", "Dimaafkan HR"
        elif t["leave_label"]:
            basis, label = "leave", f"Cuti ({t['leave_label']})"
        elif t["half_leave"]:
            basis, label = "half_leave", "Izin / cuti ½ hari"
        else:
            basis, label = "not_counted", "Tidak dihitung"
        money = charged * rates.fine + (rates.half_day if half else ZERO)
        out.append({"date": t["date"].isoformat(), "day_id": t["day_id"], "in": hhmm(t["first_in"]),
                    "out": hhmm(t["last_out"]), "minutes": t["early_raw"], "charged": charged, "half": half,
                    "amount": money, "basis": basis, "label": label})
    return out


def absent_days(trace, rates):
    """Unpaid days of a whole day: approved unpaid leave, a day HR rejected, a working day with no taps."""
    out = []
    for t in trace:
        if t["unpaid_leave"]:
            basis, label, warn = "unpaid_leave", t["leave_label"] or "Izin tanpa upah", False
        elif t["absent"] and t["rejected"]:
            basis, label, warn = "hr_rejected", "Ditolak HR", False
        elif t["absent"]:
            basis, label, warn = "none", "Tanpa keterangan", True
        else:
            continue
        out.append({"date": t["date"].isoformat(), "day_id": t["day_id"], "in": hhmm(t["first_in"]),
                    "out": hhmm(t["last_out"]), "amount": rates.per_day, "basis": basis, "label": label, "warn": warn})
    return out


def meal_days(trace, rates, late_after=None, breakfast_before=None):
    """
    Days that earned uang makan / sarapan, with the rule that paid them. For the per-present-day rule, also the
    present days WITHOUT uang makan and why ("missed"), the question HR asks most ("which day, and why?").
    A meal on a leave day is flagged (warn).
    """
    out = []
    after = late_after.strftime("%H:%M") if late_after else ""
    before = breakfast_before.strftime("%H:%M") if breakfast_before else ""
    for t in trace:
        rule = t["meal_rule"]
        base = {"date": t["date"].isoformat(), "day_id": t["day_id"], "in": hhmm(t["first_in"]),
                "out": hhmm(t["last_out"])}
        if t["meal"] or t["breakfast"]:
            parts = []
            if t["meal"]:
                if rule == "overtime_day":
                    parts.append("Hari lembur")
                elif rule == "late_out":
                    parts.append(f"Pulang {hhmm(t['last_out'])} (setelah {after})")
                else:
                    parts.append("Hadir")
                if t["meal"] > 1:
                    parts.append("lewat tengah malam (2×)")
            if t["breakfast"]:
                parts.append(f"Sarapan: masuk {hhmm(t['first_in'])} (sebelum {before})")
            warn = t["status"] == "leave"
            if warn:
                parts.append("di hari cuti")
            amount = t["meal"] * rates.meal + (rates.breakfast if t["breakfast"] else ZERO)
            out.append({**base, "meals": t["meal"], "breakfast": bool(t["breakfast"]), "amount": amount,
                        "label": " · ".join(parts), "missed": False, "warn": warn})
        elif rule == "present_day" and t["working"] and not t["unpaid_leave"] and t["status"] != "leave" \
                and (t["first_in"] or t["last_out"] or t["exempt"]):
            if t["exempt"]:
                why = "Tidak wajib absen (tap tidak dihitung)"
            elif t["rejected"]:
                why = "Ditolak HR"
            elif t["first_in"] is None:
                why = "Tidak ada tap masuk"
            else:
                why = "Tidak dihitung"
            out.append({**base, "meals": 0, "breakfast": False, "amount": ZERO, "label": why, "missed": True,
                        "warn": False})
    return out


def _emp(e):
    return {"id": str(e.id), "employee_no": e.employee_no, "full_name": e.full_name}


def _money(rows):
    for r in rows:
        r["amount"] = rupiah(r["amount"])
    return rows


def bonus_lost(nums, rates, cause):
    """G13-3, the engine's own rule: what this person loses in tunjangan kehadiran because of `cause`."""
    from apps.payroll.engine import attendance_lost
    if rates.bonus <= 0:
        return None
    why = attendance_lost(_num(nums.get("late_minutes")), _num(nums.get("sick_days")), _num(nums.get("unpaid_days")),
                          _num(nums.get("long_leave_days")))
    if not why:
        return {"amount": rupiah(rates.bonus), "lost": False, "why": []}
    hit = (cause == "late" and _num(nums.get("late_minutes")) > 0) or \
          (cause == "absent" and _num(nums.get("unpaid_days")) > 0)
    return {"amount": rupiah(rates.bonus), "lost": hit, "why": why}


SLIP_KEYS = {"late": ("late_minutes",), "early": ("late_minutes",), "absent": ("unpaid_days",),
             "meal": ("meal_days", "breakfast_days")}
SLIP_CODES = {"late": ("late",), "early": ("late",), "absent": ("unpaid_leave",), "meal": ("meal", "breakfast")}


def slip_state(nums, line, tab):
    """Does the payroll line still say what the attendance says? none / same / stale / override."""
    if line is None:
        return {"state": "none", "amount": None}
    lines = (line.result or {}).get("earnings", []) + (line.result or {}).get("deductions", [])
    amount = sum((_num(x.get("amount")) for x in lines if x.get("code") in SLIP_CODES[tab]), ZERO)
    keys = SLIP_KEYS[tab]
    if any(k in (line.override or {}) for k in keys):
        state = "override"
    elif any(_num((line.auto or {}).get(k)) != _num(nums.get(k)) for k in keys):
        state = "stale"
    else:
        state = "same"
    return {"state": state, "amount": rupiah(amount)}


def person_tabs(emp, nums, trace, rates, cfg, line=None):
    """One person -> their entry in each tab (None = nothing to show there)."""
    who = _emp(emp)
    out = {}

    rows = late_days(trace, rates)
    if rows:
        past = [r for r in rows if r["basis"] != "grace"]
        grace = [r for r in rows if r["basis"] == "grace"]
        out["late"] = {
            "employee": who, "days": len(past), "minutes": sum(r["minutes"] for r in past),
            "charged_minutes": sum(r["charged"] for r in past), "half_days": sum(1 for r in past if r["half"]),
            "forgiven_days": sum(1 for r in past if r["basis"] == "forgiven"),
            "grace_days": len(grace), "grace_minutes": sum(r["minutes"] for r in grace),
            "rupiah": rupiah(sum((r["amount"] for r in past), ZERO)),
            "bonus": bonus_lost(nums, rates, "late") if past else None,
            "slip": slip_state(nums, line, "late"), "items": _money(rows)}

    rows = early_days(trace, rates)
    if rows:
        out["early"] = {
            "employee": who, "days": len(rows), "minutes": sum(r["minutes"] for r in rows),
            "charged_minutes": sum(r["charged"] for r in rows), "half_days": sum(1 for r in rows if r["half"]),
            "forgiven_days": sum(1 for r in rows if r["basis"] == "forgiven"),
            "rupiah": rupiah(sum((r["amount"] for r in rows), ZERO)),
            "bonus": bonus_lost(nums, rates, "late"),
            "slip": slip_state(nums, line, "early"), "items": _money(rows)}

    rows = absent_days(trace, rates)
    if rows:
        out["absent"] = {
            "employee": who, "days": len(rows),
            "unpaid_leave_days": sum(1 for r in rows if r["basis"] == "unpaid_leave"),
            "rejected_days": sum(1 for r in rows if r["basis"] == "hr_rejected"),
            "no_basis_days": sum(1 for r in rows if r["basis"] == "none"),
            "rupiah": rupiah(sum((r["amount"] for r in rows), ZERO)),
            "daily_worker": getattr(emp, "pay_type", "monthly") == "daily",
            "bonus": bonus_lost(nums, rates, "absent"),
            "slip": slip_state(nums, line, "absent"), "items": _money(rows)}

    rows = meal_days(trace, rates, cfg.meal_late_after, cfg.breakfast_before)
    if rows:
        paid = [r for r in rows if not r["missed"]]
        meals = sum(r["meals"] for r in paid)
        breakfasts = sum(1 for r in paid if r["breakfast"])
        rule = trace[0]["meal_rule"] if trace else "none"
        out["meal"] = {
            "employee": who, "rule": rule, "rule_label": MEAL_RULES.get(rule, rule),
            "meals": meals, "meal_rupiah": rupiah(meals * rates.meal),
            "breakfasts": breakfasts, "breakfast_rupiah": rupiah(breakfasts * rates.breakfast),
            "rupiah": rupiah(meals * rates.meal + breakfasts * rates.breakfast),
            "missed_days": sum(1 for r in rows if r["missed"]), "warn_days": sum(1 for r in rows if r["warn"]),
            "slip": slip_state(nums, line, "meal"), "items": _money(rows)}
    return out


def _by_money(rows):
    return sorted(rows, key=lambda p: (-Decimal(p["rupiah"]), -p.get("minutes", p.get("days", 0)),
                                       p["employee"]["full_name"]))


def _slips(people):
    return {k: sum(1 for p in people if p["slip"]["state"] == k) for k in ("stale", "override")}


def summarize(tabs):
    """{tab: [person entries]} -> each tab's summary and its people, biggest rupiah first."""
    def bonus(people):
        lost = [p for p in people if p.get("bonus") and p["bonus"]["lost"]]
        return len(lost), str(sum(Decimal(p["bonus"]["amount"]) for p in lost))

    late = _by_money(tabs.get("late", []))
    past = [p for p in late if p["days"]]
    late = past + sorted([p for p in late if not p["days"]], key=lambda p: p["employee"]["full_name"])
    early = _by_money(tabs.get("early", []))
    absent = _by_money(tabs.get("absent", []))
    meal = _by_money(tabs.get("meal", []))
    bl, br = bonus(past)
    be, ber = bonus(early)
    ba, bar = bonus(absent)
    return {
        "late": {"summary": {"people": len(past), "days": sum(p["days"] for p in past),
                             "minutes": sum(p["minutes"] for p in past),
                             "charged_minutes": sum(p["charged_minutes"] for p in past),
                             "half_days": sum(p["half_days"] for p in past),
                             "forgiven_days": sum(p["forgiven_days"] for p in past),
                             "rupiah": str(sum(Decimal(p["rupiah"]) for p in past)),
                             "bonus_people": bl, "bonus_rupiah": br,
                             "grace_people": sum(1 for p in late if p["grace_days"]),
                             "grace_days": sum(p["grace_days"] for p in late), **_slips(late)},
                 "people": late},
        "early": {"summary": {"people": len(early), "days": sum(p["days"] for p in early),
                              "minutes": sum(p["minutes"] for p in early),
                              "charged_minutes": sum(p["charged_minutes"] for p in early),
                              "half_days": sum(p["half_days"] for p in early),
                              "forgiven_days": sum(p["forgiven_days"] for p in early),
                              "rupiah": str(sum(Decimal(p["rupiah"]) for p in early)),
                              "bonus_people": be, "bonus_rupiah": ber, **_slips(early)},
                  "people": early},
        "absent": {"summary": {"people": len(absent), "days": sum(p["days"] for p in absent),
                               "no_basis_days": sum(p["no_basis_days"] for p in absent),
                               "rupiah": str(sum(Decimal(p["rupiah"]) for p in absent)),
                               "bonus_people": ba, "bonus_rupiah": bar, **_slips(absent)},
                   "people": absent},
        "meal": {"summary": {"people": sum(1 for p in meal if p["meals"] or p["breakfasts"]),
                             "meals": sum(p["meals"] for p in meal),
                             "breakfasts": sum(p["breakfasts"] for p in meal),
                             "rupiah": str(sum(Decimal(p["rupiah"]) for p in meal)),
                             "missed_days": sum(p["missed_days"] for p in meal),
                             "warn_days": sum(p["warn_days"] for p in meal), **_slips(meal)},
                 "people": meal},
    }


# ── the database part ──

def build(org, month=None, now=None):
    from apps.payroll.models import PayrollSettings, PayRun
    from apps.payroll.payrun import _days_by_employee, _leaves_by_employee, collect_numbers, employees_in_period
    from .review import night_context
    from .review_bulk import _period

    info, start, end = _period(org, month)
    now = now or timezone.now()
    cfg = PayrollSettings.for_org(org)
    emps = list(employees_in_period(org, start, end))
    ids = [e.id for e in emps]
    days = _days_by_employee(org, start, end, ids)
    leaves = _leaves_by_employee(org, start, end, ids)
    ctx = night_context(org.id, ids, start, end)
    run = PayRun.objects.filter(organization=org, period_start=start).first()
    lines = {l.employee_id: l for l in run.lines.all()} if run else {}

    tabs = {"late": [], "early": [], "absent": [], "meal": []}
    shifts = {}
    for emp in emps:
        trace = []
        nums = collect_numbers(emp, start, end, cfg, days.get(emp.id, {}), leaves.get(emp.id, {}), now,
                               ctx=ctx, trace=trace)
        if emp.default_shift_id:
            shifts[emp.default_shift_id] = emp.default_shift
        for tab, entry in person_tabs(emp, nums, trace, rates_for(emp, cfg), cfg, lines.get(emp.id)).items():
            tabs[tab].append(entry)

    return {
        "success": True, **info,
        "rules": {"late_fine_per_minute": rupiah(cfg.late_fine_per_minute or 0),
                  "late_tolerance_minutes": cfg.late_tolerance_minutes,
                  "long_late_half_day_minutes": cfg.long_late_half_day_minutes,
                  "meal_allowance": rupiah(cfg.meal_allowance or 0),
                  "breakfast_allowance": rupiah(cfg.breakfast_allowance or 0),
                  "daily_divisor": cfg.daily_divisor,
                  "shifts": sorted(({"name": s.name, "grace_minutes": s.grace_minutes} for s in shifts.values()),
                                   key=lambda s: s["name"])},
        "run": ({"id": str(run.id), "name": run.name, "locked": run.is_locked,
                 "calculated_at": timezone.localtime(run.calculated_at).isoformat() if run.calculated_at else None}
                if run else None),
        **summarize(tabs),
    }


class AttendanceLogView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(build(request.hr_org, request.query_params.get("month")))
