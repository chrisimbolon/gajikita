# =============================================================================
# === backend/apps/payroll/r1_compare.py ===
# =============================================================================
"""
R1 (12 Nov 2026) — compare a SeeGaji pay run with the company's own payroll book, person by person.

Pure functions (no database), so every rule here is tested without real data:
  read_book(rows)          the book's register sheet (rows of cell values) -> BookRow list
  seegaji_amounts(result)  a PayRunLine.result -> {component: amount}
  match_names(book, emps)  book names -> employees (exact, same words, or close spelling)
  compare(book, sg)        -> Diff list for one person, each with a first-guess cause

The book layout this reads (PT DKCB, "Data Gaji (Real)"): a header row with "Nama",
"PENGHASILAN (A)", "PENGURANGAN (B)", "PENERIMAAN"; the component names in the row under it;
then numbered rows. Several sections (Karyawan Tetap / Tidak Tetap) each repeat the header.
Columns are found by their words, not their position, so a moved column still reads right.
"""
import difflib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")
TOLERANCE = Decimal("1")          # the book carries fractions (98333.33); a rupiah apart is a match

# (key, label shown in the report) in report order
COMPONENTS = [
    ("base", "Gaji pokok + tunjangan tetap"),
    ("overtime", "Lembur (jam)"),
    ("overtime_rest_day", "Lembur hari libur"),
    ("meal", "Uang makan"),
    ("piece", "Kubikasi / semen / insentif kubikasi"),
    ("bpjs_incentive", "Insentif BPJS Kesehatan"),
    ("other_earning", "Insentif / penerimaan lainnya"),
    ("thr", "THR"),
    ("late", "Potongan keterlambatan"),
    ("unpaid_leave", "Potongan unpaid leave"),
    ("jht", "BPJS TK (JHT 2%)"),
    ("loan", "Pinjaman"),
    ("other_deduction", "Potongan lainnya"),
    ("pph21", "PPh 21"),
    ("net", "DITERIMA"),
]
LABEL = dict(COMPONENTS)
DEDUCTIONS = {"late", "unpaid_leave", "jht", "loan", "other_deduction", "pph21"}


def norm(text):
    """'Lembur\\nHari Libur 120K/hr' -> 'lemburharilibur120khr'"""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def to_dec(value):
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return ZERO


# ── the book ──────────────────────────────────────────────────────────────────

def book_component(header, earning):
    """One component-column title -> component key (or None to ignore). earning: the column sits
    under PENGHASILAN (else under PENGURANGAN)."""
    h = norm(header)
    if not h:
        return None
    if earning:
        if h.startswith("gajipokok") or h.startswith("tunjangantetap"):
            return "base"
        if h.startswith("lembur"):
            return "overtime_rest_day" if "harilibur" in h else "overtime"
        if "uangmakan" in h or "sarapan" in h:
            return "meal"
        if "kubikasi" in h or "semen" in h:
            return "piece"
        if "bpjs" in h:
            return "bpjs_incentive"
        if h.startswith("thr"):
            return "thr"
        return "other_earning"
    if "terlambat" in h:
        return "late"
    if "unpaid" in h or "upah" in h:
        return "unpaid_leave"
    if "bpjs" in h or "jht" in h:
        return "jht"
    if "pinjaman" in h or "kasbon" in h:
        return "loan"
    if "pph" in h or "pajak" in h:
        return "pph21"
    return "other_deduction"


def header_map(header, sub):
    """The two header rows of one section -> (name column, {column: component}, net column)."""
    top = [norm(c) for c in header]
    name_col = next((i for i, c in enumerate(top) if c == "nama"), None)
    earn_at = next((i for i, c in enumerate(top) if c.startswith("penghasilan")), None)
    ded_at = next((i for i, c in enumerate(top) if c.startswith("pengurangan")), None)
    net_at = next((i for i, c in enumerate(top) if c.startswith("penerimaan")), None)
    if None in (name_col, earn_at, ded_at, net_at):
        return None
    cols = {}
    for i in range(earn_at, net_at):
        key = book_component(sub[i] if i < len(sub) else None, earning=i < ded_at)
        if key:
            cols[i] = key
    return name_col, cols, net_at


@dataclass
class BookRow:
    no: int
    name: str
    section: str
    amounts: dict = field(default_factory=dict)      # component -> Decimal, "net" included


def read_book(rows):
    """rows: lists of cell values, top to bottom. Numbered rows under a recognised header only."""
    out, current, section = [], None, ""
    rows = [list(r) for r in rows]
    for n, row in enumerate(rows):
        first = norm(row[0] if row else "")
        if first and first[0].isdigit() and not isinstance(row[0], (int, float)) and len(row) > 1 and row[1] in (None, ""):
            section = str(row[0]).strip()                                  # "1. Karyawan Tetap"
            continue
        if any(norm(c) == "nama" for c in row):
            sub = rows[n + 1] if n + 1 < len(rows) else []
            current = header_map(row, sub)
            continue
        if current is None or not row or not isinstance(row[0], (int, float)) or isinstance(row[0], bool):
            continue
        name_col, cols, net_at = current
        name = str(row[name_col] or "").strip() if name_col < len(row) else ""
        if not name:
            continue
        amounts = {}
        for i, key in cols.items():
            amounts[key] = amounts.get(key, ZERO) + (to_dec(row[i]) if i < len(row) else ZERO)
        amounts["net"] = to_dec(row[net_at]) if net_at < len(row) else ZERO
        out.append(BookRow(int(row[0]), name, section, amounts))
    return out


# ── SeeGaji ───────────────────────────────────────────────────────────────────

EARN_CODES = {"base": "base", "fixed_allowance": "base", "overtime": "overtime",
              "overtime_rest_day": "overtime_rest_day", "meal": "meal", "breakfast": "meal"}
DEDUCT_CODES = {"late": "late", "unpaid_leave": "unpaid_leave", "jht_employee": "jht", "loan": "loan",
                "pph21": "pph21", "pph_21": "pph21"}


def item_component(code, label, earning):
    """Typed pay-run items (kubikasi_tm, insentif …) by their code or label."""
    text = norm(code) + " " + norm(label)
    if earning:
        if "kubikasi" in text or "semen" in text or text.startswith("cp") or text.startswith("tm"):
            return "piece"
        if "bpjs" in text:
            return "bpjs_incentive"
        if "thr" in text:
            return "thr"
        return "other_earning"
    if "pph" in text or "pajak" in text:
        return "pph21"
    if "pinjaman" in text or "kasbon" in text or "loan" in text:
        return "loan"
    return "other_deduction"


def seegaji_amounts(result, net=None):
    """PayRunLine.result ({"earnings": [...], "deductions": [...]}) -> {component: Decimal}."""
    amounts = {}
    for kind, known in (("earnings", EARN_CODES), ("deductions", DEDUCT_CODES)):
        for line in (result or {}).get(kind, []):
            code = line.get("code", "")
            key = known.get(code) or item_component(code, line.get("label", ""), kind == "earnings")
            amounts[key] = amounts.get(key, ZERO) + to_dec(line.get("amount"))
    if net is None:
        earned = sum((v for k, v in amounts.items() if k not in DEDUCTIONS), ZERO)
        net = earned - sum((v for k, v in amounts.items() if k in DEDUCTIONS), ZERO)
    amounts["net"] = to_dec(net)
    return amounts


# ── names ─────────────────────────────────────────────────────────────────────

def name_words(name):
    return [w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if w]


def words_cover(short, long):
    """Every word of short is in long. A one-letter word stands for any word starting with that
    letter, so the book's "M Iqbal Hidayat" finds "Muhammad Iqbal Hidayat" (Anthony, 12 Nov)."""
    return all(w in long or (len(w) == 1 and any(x.startswith(w) for x in long)) for w in short)


def match_names(book_names, emp_names):
    """-> ({book index: employee index}, unmatched book indexes, unmatched employee indexes).
    Exact words first, then one name's words all inside the other's, then close spelling
    (Hutasoid / Hutasoit). Each employee is used once; ambiguous candidates are left unmatched."""
    pairs, used = {}, set()
    keys = {j: " ".join(name_words(e)) for j, e in enumerate(emp_names)}
    wordsets = {j: set(name_words(e)) for j, e in enumerate(emp_names)}

    def take(i, candidates):
        candidates = [j for j in candidates if j not in used]
        if len(candidates) == 1:
            pairs[i] = candidates[0]
            used.add(candidates[0])
            return True
        return False

    order = list(range(len(book_names)))
    for i in order:                                                       # 1. same words
        k = " ".join(name_words(book_names[i]))
        take(i, [j for j, v in keys.items() if v == k])
    for i in order:                                                       # 2. subset of words
        if i in pairs:
            continue
        w = set(name_words(book_names[i]))
        if w:
            take(i, [j for j, s in wordsets.items() if s and (words_cover(w, s) or words_cover(s, w))])
    for i in order:                                                       # 3. close spelling
        if i in pairs:
            continue
        k = " ".join(name_words(book_names[i]))
        scored = sorted(((difflib.SequenceMatcher(None, k, v).ratio(), j) for j, v in keys.items() if j not in used),
                        reverse=True)
        if scored and scored[0][0] >= 0.85 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05):
            take(i, [scored[0][1]])
    return (pairs, [i for i in order if i not in pairs],
            [j for j in range(len(emp_names)) if j not in used])


# ── the comparison ────────────────────────────────────────────────────────────

MANUAL = {"piece", "bpjs_incentive", "other_earning", "thr", "other_deduction"}
ATTENDANCE = {"overtime", "overtime_rest_day", "meal", "late", "unpaid_leave"}


def hint(key, sg, book):
    """First guess at the cause. A person decides; this only sorts the list."""
    if key in MANUAL and sg == 0:
        return "Belum ada di SeeGaji: item yang diketik di pay run" + (" (aturan G13)" if key == "piece" else "")
    if key == "pph21":
        return "PPh 21 belum dihitung SeeGaji (G16)" if sg == 0 else "PPh 21 beda"
    if key == "loan":
        return "Pinjaman belum diisi di pay run" if sg == 0 else "Jumlah pinjaman beda"
    if key == "base":
        return "Gaji pokok / tunjangan tetap beda: cek data karyawan (G12b)"
    if key == "jht":
        return "Dasar BPJS beda, atau tanda BPJS TK" if sg and book else "Tanda BPJS TK beda"
    if key in ATTENDANCE:
        return "Beda dari absensi: cek Rekap / Perlu Tinjau orang ini"
    if key == "net":
        return "Akibat selisih di atas"
    return ""


@dataclass
class Diff:
    key: str
    seegaji: Decimal
    book: Decimal
    hint: str

    @property
    def delta(self):
        return self.seegaji - self.book

    @property
    def label(self):
        return LABEL.get(self.key, self.key)


def compare(book_amounts, sg_amounts):
    """-> Diff for every component that differs by more than TOLERANCE, in report order."""
    out = []
    for key, _ in COMPONENTS:
        sg, bk = sg_amounts.get(key, ZERO), book_amounts.get(key, ZERO)
        if abs(sg - bk) > TOLERANCE:
            out.append(Diff(key, sg, bk, hint(key, sg, bk)))
    return out


def status(diffs):
    """'cocok' / 'cocok tanpa item manual' / 'beda'."""
    if not diffs:
        return "cocok"
    if all(d.key in MANUAL | {"loan", "pph21", "net"} for d in diffs):
        return "beda hanya di item manual / pinjaman / PPh"
    return "beda"
