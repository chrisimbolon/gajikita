# =============================================================================
# === backend/apps/attendance/fingerprint.py ===
# =============================================================================
"""
Reading fingerprint machine files (G9, 1 Nov 2026). Pure Python + openpyxl, no Django.

Three formats, recognised automatically:
  1. attlog.dat / 1_attlog.dat   downloaded from the machine to a flash disk (ZKTeco and the
                                 many brands built on it: Solution, Fingerspot...). One tap per line:
                                 "  15\t2026-09-26 07:14:21\t1\t0\t1\t0"
  2. CSV / TXT                   any export with a header: an ID column (No / ID / AC-No / User ID / PIN)
                                 and either a date-time column, or separate date and time columns.
  3. Attendance Record Report    the Excel grid from the machine's software ("Att.log report"
     (.xlsx)                     sheet): "Att. Time 2026-09-26 ~ 2026-10-25", one column per day,
                                 a block per person ("ID: 15  Name: Eko") with that day's taps
                                 stacked in one cell. An old .xls must be saved again as .xlsx.

Every format becomes the same thing: Punch(machine_id, at, name). Then make_sessions() turns
one person's punches into working sessions: first tap = Masuk, last tap = Pulang, double
taps merged, a night shift kept on the date it started.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date as Date, datetime, time, timedelta

DOUBLE_TAP = timedelta(minutes=3)        # taps this close together are one tap
MAX_SESSION = timedelta(hours=16)        # a tap more than 16 h after the session's first tap starts a new one
MIN_WORKED = timedelta(minutes=30)       # a last tap within 30 min of the first is not a clock-out


class FileError(Exception):
    """A file GajiKita can't read, with a message HR can act on."""


@dataclass(frozen=True)
class Punch:
    machine_id: str
    at: datetime                         # naive, the machine's local time
    name: str = ""


@dataclass
class Session:
    work_date: Date
    clock_in: datetime
    clock_out: datetime = None
    taps: int = 1
    ignored: list = field(default_factory=list)   # taps between in and out (kept for the record)


def clean_id(value):
    """'0015', 15, 15.0 -> '15'; ' ab ' -> 'ab'. Machine IDs are compared as text without leading zeros."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text.lstrip("0") or ("0" if text else "")


# ── 1. attlog.dat ──
DAT_LINE = re.compile(r"^\s*(\S+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?::\d{2})?)")


def parse_dat(text):
    punches, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = DAT_LINE.match(line)
        if not m:
            bad += 1
            continue
        t = m.group(3) if m.group(3).count(":") == 2 else m.group(3) + ":00"
        punches.append(Punch(clean_id(m.group(1)), datetime.fromisoformat(f"{m.group(2)} {t.zfill(8)}")))
    if not punches:
        raise FileError("Tidak ada baris absen yang terbaca di file .dat ini.")
    return punches, bad


# ── 2. CSV / TXT with a header ──
ID_HEADERS = {"id", "no", "acno", "userid", "pin", "enno", "nokaryawan", "idkaryawan", "idmesin", "badgenumber",
              "personid", "employeeid", "nik"}
NAME_HEADERS = {"name", "nama", "namakaryawan", "username"}
DATETIME_HEADERS = {"datetime", "time", "waktu", "checktime", "punchtime", "tanggaljam", "jam", "datetimeabsen",
                    "attendancetime"}
DATE_HEADERS = {"date", "tanggal", "tgl"}
TIME_ONLY_HEADERS = {"time", "jam", "waktu"}


def _key(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y")


def parse_datetime(text):
    """'2026-09-26 07:14:21', '26/09/2026 07:14', '26-09-2026 7:14' -> datetime (day before month)."""
    text = str(text or "").strip()
    m = re.match(r"^(\S+)[ T]+(\d{1,2}:\d{2}(?::\d{2})?)\s*(AM|PM|am|pm)?$", text)
    if not m:
        raise ValueError(text)
    day = parse_date(m.group(1))
    hhmm = [int(x) for x in m.group(2).split(":")]
    hour = hhmm[0]
    if m.group(3):
        hour = hour % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return datetime(day.year, day.month, day.day, hour, hhmm[1], hhmm[2] if len(hhmm) > 2 else 0)


def parse_date(text):
    text = str(text).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def parse_csv(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    header_at = next((i for i, r in enumerate(rows[:10]) if any(_key(c) in ID_HEADERS for c in r)), None)
    if header_at is None:
        raise FileError("Kolom ID karyawan tidak ditemukan. Baris judul harus punya kolom seperti No / ID / AC-No / User ID.")
    header = [_key(c) for c in rows[header_at]]
    find = lambda names: next((i for i, h in enumerate(header) if h in names), None)
    i_id, i_name = find(ID_HEADERS), find(NAME_HEADERS)
    i_date = find(DATE_HEADERS)
    i_dt = find(DATETIME_HEADERS) if i_date is None else find(TIME_ONLY_HEADERS)
    if i_dt is None:
        raise FileError("Kolom waktu absen tidak ditemukan. Perlu kolom tanggal-jam (mis. \"Time\") atau kolom Tanggal + Jam.")
    punches, bad = [], 0
    for r in rows[header_at + 1:]:
        if not r or len(r) <= max(i_id, i_dt, i_date or 0) or not str(r[i_id]).strip():
            continue
        try:
            when = parse_datetime(f"{r[i_date]} {r[i_dt]}" if i_date is not None else r[i_dt])
        except ValueError:
            bad += 1
            continue
        punches.append(Punch(clean_id(r[i_id]), when, (r[i_name].strip() if i_name is not None else "")))
    if not punches:
        raise FileError("Tidak ada baris absen yang terbaca. Periksa format tanggal dan jam di file.")
    return punches, bad


# ── 3. Attendance Record Report grid (.xlsx) ──
RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
TIME_IN_CELL = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, time)):
        return v.strftime("%H:%M")
    return str(v)


def parse_record_grid(rows):
    """rows: a list of lists of cell values (one sheet). Returns punches."""
    start = end = None
    for r in rows[:8]:
        m = RANGE.search(" ".join(_cell_text(c) for c in r))
        if m:
            start, end = Date.fromisoformat(m.group(1)), Date.fromisoformat(m.group(2))
            break
    if start is None:
        raise FileError("Periode laporan (mis. \"Att. Time 2026-09-26 ~ 2026-10-25\") tidak ditemukan di sheet.")
    # the row of day numbers: walk from the start date, a new month whenever the day number drops
    day_cols = {}
    for r in rows[:12]:
        nums = [(i, int(float(c))) for i, c in enumerate(r) if isinstance(c, (int, float)) or (isinstance(c, str) and c.strip().isdigit())]
        if len(nums) >= 7 and nums[0][1] == start.day:
            current = start
            prev = None
            for i, n in nums:
                if prev is not None:
                    current = current + timedelta(days=1)
                    if current.day != n:            # columns skipped: find the next date with this day number
                        while current.day != n and current <= end:
                            current += timedelta(days=1)
                if current > end:
                    break
                day_cols[i] = current
                prev = n
            break
    if not day_cols:
        raise FileError("Baris tanggal (26, 27, 28 ...) tidak ditemukan di bawah judul laporan.")

    punches = []
    i = 0
    while i < len(rows):
        texts = [_cell_text(c).strip() for c in rows[i]]
        if any(re.fullmatch(r"ID\s*[:：]?", t, re.I) or re.match(r"^ID\s*[:：]\s*\S", t, re.I) for t in texts):
            machine_id, name = "", ""
            for k, t in enumerate(texts):
                m = re.match(r"^ID\s*[:：]\s*(\S+)", t, re.I)
                if m:
                    machine_id = m.group(1)
                elif re.fullmatch(r"ID\s*[:：]?", t, re.I):
                    machine_id = next((x for x in texts[k + 1:] if x), "")
                m = re.match(r"^Name\s*[:：]\s*(.+)", t, re.I) or re.match(r"^Nama\s*[:：]\s*(.+)", t, re.I)
                if m:
                    name = m.group(1).strip()
                elif re.fullmatch(r"(Name|Nama)\s*[:：]?", t, re.I):
                    name = next((x for x in texts[k + 1:] if x), "")
            if machine_id.endswith(":"):
                machine_id = ""                    # the ID cell was empty; we picked up the next label
            machine_id = clean_id(machine_id)
            if i + 1 < len(rows) and machine_id:
                times_row = rows[i + 1]
                for col, day in day_cols.items():
                    if col < len(times_row):
                        for hh, mm in TIME_IN_CELL.findall(_cell_text(times_row[col])):
                            if int(hh) < 24 and int(mm) < 60:
                                punches.append(Punch(machine_id, datetime.combine(day, time(int(hh), int(mm))), name))
            i += 2
            continue
        i += 1
    if not punches:
        raise FileError("Tidak ada jam absen yang terbaca di laporan ini.")
    return punches, 0


def read_xlsx_rows(data):
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise FileError("File Excel tidak bisa dibuka. Pastikan formatnya .xlsx.")
    best = None
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        joined = " ".join(_cell_text(c) for r in rows[:8] for c in r)
        if RANGE.search(joined):
            return rows
        best = best or rows
    return best or []


# ── which format? ──
def read_punches(filename, data):
    """Returns (punches, unreadable_line_count, format_label)."""
    name = (filename or "").lower()
    if name.endswith(".xls"):
        raise FileError("File .xls (Excel lama) belum bisa dibaca. Buka di Excel, lalu Save As → \"Excel Workbook (.xlsx)\", dan upload lagi.")
    if name.endswith(".xlsx") or data[:2] == b"PK":
        rows = read_xlsx_rows(data)
        joined = " ".join(_cell_text(c) for r in rows[:8] for c in r)
        if RANGE.search(joined):
            punches, bad = parse_record_grid(rows)
            return punches, bad, "Attendance Record Report (Excel)"
        text = "\n".join(";".join(_cell_text(c) if not isinstance(c, datetime) else c.strftime("%Y-%m-%d %H:%M:%S")
                                  for c in r) for r in rows)
        punches, bad = parse_csv(text)
        return punches, bad, "Tabel Excel"
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = data.decode(enc)
            if "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileError("File tidak bisa dibaca sebagai teks.")
    first = next((l for l in text.splitlines() if l.strip()), "")
    if DAT_LINE.match(first):
        punches, bad = parse_dat(text)
        return punches, bad, "attlog.dat (download dari mesin)"
    punches, bad = parse_csv(text)
    return punches, bad, "CSV / teks"


# ── punches -> working sessions ──
def make_sessions(punch_times):
    """One person's tap times (any order) -> sessions. First tap = in, last = out."""
    taps = []
    for t in sorted(set(punch_times)):
        if taps and t - taps[-1] <= DOUBLE_TAP:
            continue                       # a double tap
        taps.append(t)
    sessions = []
    for t in taps:
        s = sessions[-1] if sessions else None
        if s is not None and t - s.clock_in <= MAX_SESSION:
            if s.clock_out is not None:
                s.ignored.append(s.clock_out)
            s.clock_out = t
            s.taps += 1
        else:
            sessions.append(Session(work_date=t.date(), clock_in=t))
    for s in sessions:
        if s.clock_out is not None and s.clock_out - s.clock_in < MIN_WORKED:
            s.ignored.append(s.clock_out)
            s.clock_out = None
    return sessions
