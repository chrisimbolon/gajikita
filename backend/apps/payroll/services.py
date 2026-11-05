# =============================================================================
# === backend/apps/payroll/services.py ===
# =============================================================================
"""
Overtime in rupiah for real employees and days (G4a, 28 Oct 2026). The rules
live in overtime.py; this file only reads the employee, shift and day.
"""
from .overtime import hourly_rate, monthly_basis, overtime_pay, rupiah, week_pattern

NOT_PAID_REASONS = {
    "not_eligible": "Tidak berhak upah lembur (diatur di data karyawan)",
    "piece": "Upah borongan: hitungan lembur belum tersedia",
    "no_wage": "Gaji pokok / upah belum diisi",
}


def shift_of(day):
    return day.shift or day.employee.default_shift


def wage_basis(employee, shift):
    """(monthly basis, hourly rate, week pattern) or (None, None, pattern, reason)."""
    pattern = week_pattern(shift.working_days if shift else "123456")
    if not employee.overtime_eligible:
        return None, None, pattern, "not_eligible"
    basis = monthly_basis(employee.pay_type, employee.base_rate, employee.fixed_allowance, pattern)
    if basis is None:
        return None, None, pattern, "piece"
    if basis <= 0:
        return None, None, pattern, "no_wage"
    return basis, hourly_rate(basis), pattern, None


def is_rest_day(day):
    shift = shift_of(day)
    return bool(shift and not shift.is_working_day(day.date))


def pay_payload(pay, estimate=False):
    return {
        "minutes": pay.minutes,
        "rest_day": pay.rest_day,
        "hourly_rate": str(rupiah(pay.hourly_rate)),
        "lines": [{"minutes": l.minutes, "multiplier": str(l.multiplier), "amount": str(l.amount)} for l in pay.lines],
        "amount": str(pay.amount),
        "warnings": pay.warnings,
        "estimate": estimate,
    }


def price_overtime(employee, shift, minutes, rest_day, cfg, estimate=False):
    """
    One day's overtime in rupiah, the way the company's payroll pays it (G11c):
      PP 35 mode: the PP 35 calculation, as before.
      Tarif tetap: rounded hours x the hourly rate (working day) or the rest-day rate, with the
      PP 35 amount beside it (pp35_amount, gap) so HR sees the difference when approving.
    """
    from decimal import Decimal
    from .engine import FLAT, round_overtime
    basis, hourly, pattern, reason = wage_basis(employee, shift)
    if reason == "not_eligible" or (reason and cfg.overtime_mode != FLAT):
        return {"minutes": minutes, "not_paid": NOT_PAID_REASONS[reason]}
    pp35 = None if reason else overtime_pay(minutes, rest_day, pattern, hourly)
    if cfg.overtime_mode != FLAT:
        return {**pay_payload(pp35, estimate=estimate), "mode": "pp35"}
    rounded = round_overtime(minutes, cfg.overtime_rounding)
    if rest_day:
        rate = Decimal(cfg.flat_rest_day)
        amount = rate if minutes > 0 else Decimal("0")
    else:
        rate = Decimal(cfg.flat_overtime_hour)
        amount = Decimal(rounded) / 60 * rate
    amount = rupiah(amount)
    out = {"minutes": minutes, "rest_day": rest_day, "mode": "flat", "rounded_minutes": rounded,
           "rate": str(rupiah(rate)), "amount": str(amount), "estimate": estimate, "lines": [], "warnings": [],
           "hourly_rate": str(rupiah(hourly)) if hourly else "0", "pp35_amount": None, "gap": "0"}
    if pp35 is not None:
        out.update(lines=pay_payload(pp35)["lines"], warnings=pp35.warnings, pp35_amount=str(pp35.amount),
                   gap=str(max(pp35.amount - amount, Decimal("0"))))
    return out


def day_overtime(day, proposed_minutes):
    """Overtime pay for one day: the approved minutes, or an estimate on the proposed ones."""
    from .models import PayrollSettings
    approved = day.overtime_approved_minutes
    minutes = approved if approved is not None else proposed_minutes
    if not minutes:
        return None
    cfg = PayrollSettings.for_org(day.organization)
    return price_overtime(day.employee, shift_of(day), minutes, is_rest_day(day), cfg, estimate=approved is None)
