# =============================================================================
# === backend/apps/attendance/spl.py ===
# =============================================================================
"""
G17-E1 (23 Nov 2026) — the SPL (Surat Perintah Lembur, the overtime order) decides WHETHER overtime is paid; the
taps decide HOW MUCH (DKCB's rounding and the 18:00 rule, as before).

UU No. 27/2026 Pasal 116 ayat 1: overtime needs (a) the worker's consent, (b) an order in writing or digital, and
(c) at most 4 hours a day and 18 hours a week. Anthony (18 Nov): the SPL is paper from the SPV, its hours are a plan,
HR records it and pays what the fingerprint shows, and it may come after the overtime.

Payroll -> Pengaturan -> "Persetujuan lembur":
  "decision" (bawaan)  HR decides overtime per day (Lembur, Perlu Tinjau, the recap file). SPLs are a record.
  "spl"                a day HR has NOT decided, with overtime in the taps and an SPL covering the person, is paid
                       automatically; without an SPL it is listed "Lembur tanpa SPL" and not paid.
HR's own decision on a day always wins (also "Hadir, tanpa lembur" and the recap import). Locked payrolls never move.
Soft notes only: past the SPL's planned end by more than an hour, consent not recorded. (The 4 h / 18 h limits of
Pasal 116 ayat 1 huruf c come with the SPL log, step E3.)

The pure part (SplRef, apply_spl) has no database; spl_index() loads one screen's SPLs in one query.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

DECISION, SPL = "decision", "spl"
OVER_PLAN_MINUTES = 60          # a note when the last clock-out is more than this past the SPL's planned end
DAY_LIMIT, WEEK_LIMIT = 4 * 60, 18 * 60       # G17-E3: Pasal 116 ayat 1 huruf c
CONSENT_YES, CONSENT_PENDING, CONSENT_NO = "yes", "pending", "no"


@dataclass(frozen=True)
class SplRef:
    id: str
    number: int
    work: str
    planned_start: time = None
    planned_end: time = None
    consent: str = CONSENT_YES

    @property
    def label(self):
        return f"SPL {self.number}" + (f" · {self.work}" if self.work else "")


def planned_end_at(day, ref, tz):
    """The SPL's planned end as an aware datetime on that working day (past midnight = the next date)."""
    if ref is None or ref.planned_end is None:
        return None
    end_date = day
    if ref.planned_start is not None and ref.planned_end <= ref.planned_start:
        end_date = day + timedelta(days=1)
    naive = datetime.combine(end_date, ref.planned_end)
    try:
        return tz.localize(naive)                      # pytz
    except AttributeError:
        return naive.replace(tzinfo=tz)                # zoneinfo


def apply_spl(result, day, ref, *, spl_mode, decision="", overtime_approved=None, tz=None):
    """
    After the day is evaluated: mark the SPL and, in "spl" mode, turn an undecided overtime proposal into
    overtime paid by the SPL (result.overtime_spl_minutes) or "Lembur tanpa SPL" (not paid). Changes `result`.
    """
    if ref is not None:
        result.spl = ref.label
        result.spl_consent = ref.consent
    proposed = result.overtime_proposed_minutes or 0
    if not spl_mode or not proposed or decision or overtime_approved is not None:
        return result
    reasons = [x for x in result.review_reasons if not (x.startswith("Lembur ") and "menunggu persetujuan" in x)]
    if ref is not None:
        result.overtime_spl_minutes = proposed
        end = planned_end_at(day, ref, tz) if tz is not None else None
        if end is not None and result.last_out is not None:
            over = int((result.last_out - end).total_seconds() // 60)
            if over > OVER_PLAN_MINUTES:
                result.spl_over_plan = over
    else:
        result.overtime_no_spl = True
        reasons.append(f"Lembur {proposed} menit tanpa SPL (tidak dibayar)")
    result.review_reasons = reasons
    result.needs_review = bool(reasons) and decision != "approved"
    return result


def over_limits(days):
    """G17-E3: one person's paid overtime [(date, minutes)] -> (days over 4 hours, [(monday, minutes)] of weeks
    over 18 hours). Weeks run Monday to Sunday; only the days given count."""
    long_days, weeks = [], {}
    for d, m in days:
        if m > DAY_LIMIT:
            long_days.append(d)
        monday = d - timedelta(days=d.weekday())
        weeks[monday] = weeks.get(monday, 0) + m
    return sorted(long_days), sorted((w, m) for w, m in weeks.items() if m > WEEK_LIMIT)


def limit_text(name, long_days, heavy_weeks):
    parts = ([f"{len(long_days)} hari lebih dari 4 jam"] if long_days else []) + \
            ([f"{len(heavy_weeks)} minggu lebih dari 18 jam"] if heavy_weeks else [])
    return f"{name} ({', '.join(parts)})"


# ── database ──
def spl_index(organization_id, employee_ids, start, end):
    """{(employee_id, date): SplRef} for active SPLs touching start..end (a declined person is not covered).
    One query. When two SPLs cover the same person and day, the lower number is kept."""
    from .models import OvertimeOrder, OvertimeOrderPerson
    qs = (OvertimeOrderPerson.objects
          .filter(order__organization_id=organization_id, order__status=OvertimeOrder.Status.ACTIVE,
                  order__start_date__lte=end, order__end_date__gte=start)
          .exclude(consent=CONSENT_NO)
          .values("employee_id", "consent", "order_id", "order__number", "order__work", "order__start_date",
                  "order__end_date", "order__planned_start", "order__planned_end")
          .order_by("order__number"))
    if employee_ids is not None:
        qs = qs.filter(employee_id__in=list(employee_ids))
    out = {}
    for v in qs:
        ref = SplRef(str(v["order_id"]), v["order__number"], v["order__work"], v["order__planned_start"],
                     v["order__planned_end"], v["consent"])
        d = max(v["order__start_date"], start)
        while d <= min(v["order__end_date"], end):
            out.setdefault((v["employee_id"], d), ref)
            d += timedelta(days=1)
    return out
