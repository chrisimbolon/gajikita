# =============================================================================
# === backend/apps/leave/rules.py ===
# =============================================================================
"""
Leave rules (G7, 28 Oct 2026). Pure Python, no Django: easy to test, easy to read.

G14-1 (20 Nov 2026): cuti khusus follow UU No. 27/2026 Pasal 124 and 149 (istri melahirkan 2 days + the
company's extra, istri keguguran 2 days, haid up to 2 days for women); see special_reasons().
Defaults from UU 13/2003 (as amended by UU 6/2023), each to become a company
setting once a customer tells us theirs:
  * Cuti tahunan: 12 working days a year, from the day the worker has worked 12 months.
    Pending + approved requests in the same calendar year count against it.
  * Sakit: paid, no day limit here; a doctor's letter photo is optional (HR sees if one is missing).
  * Cuti khusus (pasal 93): paid, a fixed number of days per reason (SPECIAL_REASONS).
  * Izin tanpa upah: not paid; payroll deducts it later.
Days are counted as the worker's own working days (their shift's working days),
so Monday to Sunday on a Monday-Saturday shift is 6 days.
"""
from datetime import date as Date, timedelta

ANNUAL_DAYS = 12
MAX_RANGE_DAYS = 90             # one request covers at most 90 calendar days
WORKER_BACKDATE_DAYS = 30       # a worker may ask for days up to 30 days back (sick, say)

ANNUAL, SICK, SPECIAL, UNPAID = "annual", "sick", "special", "unpaid"

KIND_LABELS = {
    ANNUAL:  "Cuti tahunan",
    SICK:    "Sakit",
    SPECIAL: "Cuti khusus",
    UNPAID:  "Izin tanpa upah",
}
PAID = {ANNUAL: True, SICK: True, SPECIAL: True, UNPAID: False}

MENSTRUAL = "menstrual"          # G14-1
PATERNITY_EXTRA_MAX = 3         # G14-1: UU 27/2026 Pasal 124 ayat 1, "paling lama 3 hari berikutnya"

# UU No. 27/2026 Pasal 149 ayat 2 (was UU 13/2003 pasal 93 ayat 4): reason -> (label, days)
SPECIAL_REASONS = {
    "marriage":           ("Menikah", 3),
    "child_marriage":     ("Menikahkan anak", 2),
    "child_circumcision": ("Mengkhitankan anak", 2),
    "child_baptism":      ("Membaptiskan anak", 2),
    "wife_birth":         ("Istri melahirkan", 2),              # + the company's extra days (special_reasons)
    "wife_miscarriage":   ("Istri keguguran", 2),               # G14-1: Pasal 124 ayat 2
    "family_death":       ("Suami/istri, orang tua/mertua, anak/menantu meninggal", 2),
    "household_death":    ("Anggota keluarga serumah meninggal", 1),
    MENSTRUAL:            ("Haid (sakit, hari pertama dan kedua)", 2),   # G14-1: Pasal 120, 149 ayat 2 b; women only
}


def special_reasons(paternity_extra=PATERNITY_EXTRA_MAX, menstrual=True):
    """G14-1: the reasons and day limits for one company (Pengaturan cuti)."""
    out = {}
    for key, (label, days) in SPECIAL_REASONS.items():
        if key == MENSTRUAL and not menstrual:
            continue
        if key == "wife_birth":
            days = 2 + max(0, min(int(paternity_extra or 0), PATERNITY_EXTRA_MAX))
        out[key] = (label, days)
    return out


def label_of(kind, special_reason=""):
    if kind == SPECIAL and special_reason in SPECIAL_REASONS:
        return f"Cuti khusus: {SPECIAL_REASONS[special_reason][0].lower()}"
    return KIND_LABELS.get(kind, kind)


def working_dates(start, end, working_days=None):
    """Every date from start to end (inclusive) that is a working day. working_days "123456" = Mon-Sat; None = every day."""
    out, d = [], start
    while d <= end:
        if working_days is None or str(d.isoweekday()) in working_days:
            out.append(d)
        d += timedelta(days=1)
    return out


def one_year_after(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:              # 29 February
        return d.replace(year=d.year + 1, day=28)


def annual_entitlement(join_date, on_date):
    """12 days once the worker has worked 12 months by on_date, otherwise 0."""
    return ANNUAL_DAYS if on_date >= one_year_after(join_date) else 0


def check_request(*, kind, special_reason, start, end, days, annual_left, today, by_worker, reasons=None):
    """
    Every reason this request can't be made, as {field: message}. Empty = fine.
    annual_left: annual days still free in the start date's year (only used for annual leave).
    """
    errors = {}
    if kind not in KIND_LABELS:
        errors["kind"] = "Pilih jenis cuti."
        return errors
    if end < start:
        errors["end_date"] = "Tanggal selesai tidak boleh sebelum tanggal mulai."
        return errors
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        errors["end_date"] = f"Satu pengajuan paling lama {MAX_RANGE_DAYS} hari. Buat pengajuan baru untuk sisanya."
        return errors
    if by_worker and start < today - timedelta(days=WORKER_BACKDATE_DAYS):
        errors["start_date"] = f"Tanggal mulai paling lama {WORKER_BACKDATE_DAYS} hari yang lalu. Hubungi HR untuk yang lebih lama."
        return errors
    if days == 0:
        errors["end_date"] = "Semua tanggal itu hari libur shift, tidak perlu cuti."
        return errors
    reasons = SPECIAL_REASONS if reasons is None else reasons           # G14-1: the company's reasons and limits
    if kind == SPECIAL:
        if special_reason not in reasons:
            errors["special_reason"] = "Pilih alasan cuti khusus."
        else:
            label, most = reasons[special_reason]
            if days > most:
                errors["end_date"] = f"Cuti khusus \"{label.lower()}\" paling banyak {most} hari kerja (ini {days} hari)."
    if kind == ANNUAL and days > annual_left:
        errors["end_date"] = (f"Sisa cuti tahunan {annual_left} hari, pengajuan ini {days} hari."
                              if annual_left > 0 else "Belum ada sisa cuti tahunan.")
    return errors


def sick_note_missing(kind, days, has_attachment):
    """A hint for HR, never a refusal: sick for more than 2 working days without a doctor's letter photo."""
    return kind == SICK and days > 2 and not has_attachment
