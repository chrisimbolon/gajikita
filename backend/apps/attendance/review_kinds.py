# =============================================================================
# === backend/apps/attendance/review_kinds.py ===
# =============================================================================
"""
The kinds of "why HR must look at this day" (G11, 4 Nov 2026). Pure Python, no Django.
A day can have several kinds (late AND overtime). Used to filter and count the review queue.
"""
KINDS = [
    ("overtime", "Lembur"),
    ("late", "Terlambat"),
    ("no_clock_out", "Tidak absen pulang"),
    ("early_out", "Pulang cepat"),
    ("day_off_work", "Masuk di hari libur"),
    ("leave_work", "Masuk saat cuti"),
    ("other", "Lainnya (lokasi, GPS, dll.)"),
]
LABELS = dict(KINDS)
PREFIXES = [("Lembur", "overtime"), ("Terlambat", "late"), ("Tidak absen pulang", "no_clock_out"),
            ("Pulang cepat", "early_out"), ("Masuk di hari libur", "day_off_work"), ("Masuk padahal", "leave_work")]


def kinds_of(review_reasons):
    """The kinds of one day, in KINDS order, from its plain-word review reasons."""
    found = set()
    for reason in review_reasons:
        kind = next((k for prefix, k in PREFIXES if reason.startswith(prefix)), "other")
        found.add(kind)
    return [k for k, _ in KINDS if k in found]


def capped_overtime(proposed, cap):
    """Overtime minutes to approve: what the taps propose, never more than the cap (None = no cap)."""
    if not proposed:
        return None
    return min(proposed, cap) if cap is not None else proposed
