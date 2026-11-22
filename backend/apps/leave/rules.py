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
MATERNITY, MISCARRY, LONG_REST = "maternity", "miscarry", "long_rest"            # G14-2

KIND_LABELS = {
    ANNUAL:  "Cuti tahunan",
    SICK:    "Sakit",
    SPECIAL: "Cuti khusus",
    UNPAID:  "Izin tanpa upah",
    MATERNITY: "Cuti melahirkan",           # G14-2: UU 27/2026 Pasal 121, 123
    MISCARRY:  "Istirahat keguguran",       # G14-2: Pasal 121 ayat 4
    LONG_REST: "Istirahat panjang",         # G14-2: Pasal 118 ayat 2 c
}
PAID = {ANNUAL: True, SICK: True, SPECIAL: True, UNPAID: False, MATERNITY: True, MISCARRY: True, LONG_REST: True}

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
    if kind in HR_ONLY and by_worker:                                                   # G14-2
        errors["kind"] = f"{KIND_LABELS[kind]} dicatat oleh HR. Hubungi HR."
        return errors
    if end < start:
        errors["end_date"] = "Tanggal selesai tidak boleh sebelum tanggal mulai."
        return errors
    limit = CALENDAR_MAX_DAYS if kind in CALENDAR_KINDS else MAX_RANGE_DAYS              # G14-2
    if (end - start).days + 1 > limit:
        errors["end_date"] = f"Satu pengajuan paling lama {limit} hari. Buat pengajuan baru untuk sisanya."
        return errors
    if kind == MATERNITY and end >= add_months(start, MATERNITY_MAX_MONTHS):              # G14-2
        errors["end_date"] = "Cuti melahirkan paling lama 6 bulan (3 bulan + perpanjangan 3 bulan)."
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


# ── G14-2 (23 Nov 2026): UU No. 27/2026 Pasal 118 ayat 2 c dan 4, 121, 123, 149 ayat 3 ──
CALENDAR_KINDS = (MATERNITY, MISCARRY, LONG_REST)   # counted in calendar days, recorded by HR only
HR_ONLY = CALENDAR_KINDS
WOMEN_ONLY = (MATERNITY, MISCARRY)
CALENDAR_MAX_DAYS = 200                            # one request: maternity with the extension is about 6 months
MATERNITY_MONTHS, MATERNITY_MAX_MONTHS, MATERNITY_FULL_MONTHS = 3, 6, 4
MATERNITY_LAW_PAY = 75                             # % of the wage in months 5 and 6 (Pasal 123 ayat 3)
LONG_REST_DAYS, LONG_REST_YEARS = 30, 5


def add_months(d, n):
    """d + n months, the day clamped to the month's end (31 Jan + 1 month = 28/29 Feb)."""
    from calendar import monthrange
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return Date(y, m, min(d.day, monthrange(y, m)[1]))


def calendar_days(start, end):
    return (end - start).days + 1 if end >= start else 0


def default_end(kind, start):
    """The end date HR sees first (the last day included): 3 months, 1,5 months, 30 days."""
    if kind == MATERNITY:
        return add_months(start, MATERNITY_MONTHS) - timedelta(days=1)
    if kind == MISCARRY:
        return add_months(start, 1) + timedelta(days=14)
    if kind == LONG_REST:
        return start + timedelta(days=LONG_REST_DAYS - 1)
    return start


def maternity_reduced_from(start):
    """The first day of month 5 of cuti melahirkan: from here the company's extension pay applies (months 1-4: full)."""
    return add_months(start, MATERNITY_FULL_MONTHS)


def _years_between(start, on):
    return on.year - start.year - ((on.month, on.day) < (start.month, start.day))


def long_rest_since(join_date, on):
    """The latest 5-year mark (5, 10, 15... years of continuous work) on or before `on`; None before 5 years."""
    if not join_date or on < join_date:
        return None
    k = _years_between(join_date, on) // LONG_REST_YEARS
    return add_months(join_date, 12 * LONG_REST_YEARS * k) if k >= 1 else None


def next_long_rest(join_date, on):
    """The next 5-year mark after `on` (the current istirahat panjang is replaced then)."""
    k = max(0, _years_between(join_date, on)) // LONG_REST_YEARS + 1
    return add_months(join_date, 12 * LONG_REST_YEARS * k)


def leave_notes(kind, start, end, has_attachment, annual_used_that_year=0):
    """Soft notes HR sees next to a request. Never a refusal."""
    notes = []
    if kind == MATERNITY:
        three = add_months(start, MATERNITY_MONTHS)
        if end < three - timedelta(days=1):
            notes.append("Menurut UU, cuti melahirkan paling singkat 3 bulan (Pasal 121 ayat 2).")
        if end >= three and not has_attachment:
            notes.append("Perpanjangan lewat 3 bulan perlu surat keterangan dokter (Pasal 121 ayat 2 huruf b).")
    if kind == MISCARRY and end > default_end(MISCARRY, start) and not has_attachment:
        notes.append("Istirahat keguguran lebih dari 1,5 bulan perlu surat dokter atau bidan (Pasal 121 ayat 4).")
    if kind == LONG_REST and annual_used_that_year:
        notes.append(f"Cuti tahunan {start.year} sudah dipakai {annual_used_that_year} hari. Menurut Pasal 118 ayat 4, "
                     f"tidak ada cuti tahunan di tahun istirahat panjang diambil.")
    return notes


def sick_month(first, day):
    """Which month of an unbroken sick leave `day` falls in (1 = the first month)."""
    n = 1
    while add_months(first, n) <= day:
        n += 1
    return n


def long_sick_text(first, last):
    """Pasal 149 ayat 3: 100% for 4 months, 75% for the next 4, 50% for the next 4, then 25%. A note, not a cut."""
    n = sick_month(first, last)
    if n <= 4:
        return ""
    pct = 75 if n <= 8 else 50 if n <= 12 else 25
    return (f"Sakit berturut-turut sejak {first:%d-%m-%Y}: bulan ke-{n}. Menurut UU 27/2026 Pasal 149 ayat 3, "
            f"upah bulan ini {pct}%. SeeGaji tidak memotong otomatis; tambahkan potongan di slip bila diterapkan.")


def sick_note_missing(kind, days, has_attachment):
    """A hint for HR, never a refusal: sick for more than 2 working days without a doctor's letter photo."""
    return kind == SICK and days > 2 and not has_attachment
