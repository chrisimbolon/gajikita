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


def day_overtime(day, proposed_minutes):
    """Overtime pay for one day: the approved minutes, or an estimate on the proposed ones."""
    approved = day.overtime_approved_minutes
    minutes = approved if approved is not None else proposed_minutes
    if not minutes:
        return None
    basis, hourly, pattern, reason = wage_basis(day.employee, shift_of(day))
    if reason:
        return {"minutes": minutes, "not_paid": NOT_PAID_REASONS[reason]}
    pay = overtime_pay(minutes, is_rest_day(day), pattern, hourly)
    return pay_payload(pay, estimate=approved is None)
