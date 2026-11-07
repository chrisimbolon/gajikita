# =============================================================================
# === backend/apps/attendance/rekap_codes.py ===
# =============================================================================
"""
The short codes of the Rekap Absensi grid (G10, 1 Nov 2026). Pure Python, no Django.

day_cell() turns one evaluated day (day_status.DayResult) into a grid cell. It is called
from payroll.payrun.collect_numbers(), the same loop payroll counts with, so the grid and
the payroll can never disagree.
"""
from .day_status import Status

CODES = {
    Status.ON_TIME: "H", Status.PRESENT: "H", Status.WORKING: "K", Status.LATE: "T", Status.EARLY_OUT: "PC",
    Status.NO_CLOCK_OUT: "TP", Status.ABSENT: "A", Status.NOT_YET: "", Status.DAY_OFF: "L",
    Status.DAY_OFF_WORK: "LK", Status.REJECTED: "X",
}
LEAVE_CODES = {"annual": "C", "sick": "S", "special": "CK", "unpaid": "I"}
OUTSIDE = "-"

LEGEND = [
    ("H", "Hadir"), ("T", "Terlambat"), ("PC", "Pulang cepat"), ("TP", "Tidak absen pulang"), ("K", "Sedang bekerja"),
    ("A", "Tidak hadir"), ("C", "Cuti tahunan"), ("S", "Sakit"), ("CK", "Cuti khusus"), ("I", "Izin tanpa upah"),
    ("L", "Libur"), ("LK", "Masuk di hari libur"), ("X", "Ditolak HR"), ("-", "Belum / sudah tidak bekerja"),
]
# what counts as "bermasalah" for the "hanya yang bermasalah" filter
PROBLEM_CODES = {"T", "PC", "TP", "A", "X"}


def day_cell(d, result, day, leave, approved_overtime):
    """One grid cell. first_in / last_out stay datetimes here; the view formats them in local time."""
    if result.status == Status.LEAVE:
        code = LEAVE_CODES.get(leave[0] if leave else "", "C")
    else:
        code = CODES.get(result.status, "?")
    pending = result.overtime_proposed_minutes if (result.overtime_proposed_minutes and not approved_overtime
                                                  and not (day is not None and day.decision)) else 0
    return {
        "d": d.isoformat(), "c": code, "s": result.status, "l": result.label,
        "fi": result.first_in, "lo": result.last_out,
        "day": str(day.id) if day is not None else None,
        "rv": bool(day is not None and result.needs_review and not day.decision),
        "ot": approved_overtime or 0, "otp": pending,
        "late": result.late_minutes if Status.LATE in result.tags else 0,
        "early": result.early_minutes if Status.EARLY_OUT in result.tags else 0,
        "n": result.note,                                   # G12e
    }


def outside_cell(d):
    return {"d": d.isoformat(), "c": OUTSIDE, "s": "outside", "l": "Di luar masa kerja", "fi": None, "lo": None,
            "day": None, "rv": False, "ot": 0, "otp": 0, "late": 0, "early": 0, "n": ""}


def summarize(nums, cells):
    """The summary columns, from the payroll numbers plus the cells."""
    late_days = [c for c in cells if c["late"]]
    return {
        "present": nums["present_days"], "absent": nums["absent_days"],
        "late_times": len(late_days), "late_minutes": sum(c["late"] for c in late_days),
        "early_times": sum(1 for c in cells if c["early"]), "early_minutes": sum(c["early"] for c in cells),
        "no_clock_out": sum(1 for c in cells if c["c"] == "TP"),
        "leave": nums["leave"], "unpaid_leave": nums["unpaid_leave_days"], "paid_leave": nums["paid_leave_days"],
        "overtime_minutes": sum(o["minutes"] for o in nums["overtime"]),
        "overtime_pending_minutes": sum(c["otp"] for c in cells),
        "meal_days": nums["meal_days"], "review": nums["review_days"],
        "problem": nums["review_days"] > 0 or any(c["c"] in PROBLEM_CODES for c in cells),
    }
