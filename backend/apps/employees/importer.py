# =============================================================================
# === backend/apps/employees/importer.py ===
# =============================================================================
"""
Reading the employee template (G9, 1 Nov 2026). Pure Python + openpyxl, no Django.

  read_table(filename, data)   the first sheet of an .xlsx (or a CSV) -> header + rows
  parse_rows(header, rows)     each row -> {field: clean value} + errors + warnings, in plain
                               Indonesian. Nothing here touches the database: matching to existing
                               employees, shifts and sites happens in import_service.py.

Rules that keep an import predictable:
  * Columns are recognised by their title, in any order; unknown columns are ignored.
  * An empty cell means "don't change" for an existing employee, "nothing" for a new one.
  * The template's hint row and the example rows (No. Karyawan starting "CTH-") are skipped.
  * Numbers that must keep leading zeros (NIK, rekening, HP, BPJS) are read as text; when Excel
    has already turned them into numbers, they are written back without ".0" or "E+15".
"""
import csv
import io
import re
from datetime import date as Date, datetime
from decimal import Decimal, InvalidOperation

TEMPLATE_COLUMNS = [
    # (field, title in the template, required for a NEW employee, hint)
    ("employee_no", "No. Karyawan", True, "Unik per perusahaan. Contoh: DK-001"),
    ("full_name", "Nama Lengkap (sesuai KTP)", True, ""),
    ("position", "Jabatan", False, "Contoh: Driver TM"),
    ("nik", "NIK (KTP)", False, "16 angka"),
    ("npwp", "NPWP", False, ""),
    ("ptkp_status", "Status PTKP", False, "TK/0, TK/1, TK/2, TK/3, K/0, K/1, K/2, K/3"),
    ("join_date", "Tanggal Masuk", True, "Format tanggal Excel atau DD/MM/YYYY"),
    ("probation_end_date", "Tanggal Lolos Magang / Probation", False, ""),
    ("end_date", "Tanggal Keluar", False, "Kosongkan jika masih aktif"),
    ("employment_type", "Jenis Hubungan Kerja", False, "PKWTT (tetap), PKWT (kontrak), Harian lepas, Borongan"),
    ("pay_type", "Jenis Upah", False, "Bulanan, Harian, Per pekerjaan"),
    ("base_rate", "Gaji Pokok / Upah (Rp)", True, "Bulanan: sebulan. Harian: per hari"),
    ("fixed_allowance", "Tunjangan Tetap (Rp)", False, "Sebulan"),
    ("overtime_eligible", "Berhak Lembur", False, "Ya / Tidak"),
    ("bpjs_tk_enrolled", "Terdaftar BPJS Ketenagakerjaan", False, "Ya / Tidak"),
    ("bpjs_tk_no", "No. BPJS Ketenagakerjaan", False, ""),
    ("bpjs_kesehatan_no", "No. BPJS Kesehatan", False, ""),
    ("bank_name", "Bank", False, "Contoh: BCA, Mandiri, BRI"),
    ("bank_account_no", "No. Rekening", False, ""),
    ("bank_account_name", "Nama Pemilik Rekening", False, ""),
    ("phone", "No. HP", False, "Untuk login absen dari HP"),
    ("fingerprint_id", "ID Mesin Fingerprint", False, "Nomor ID karyawan di mesin absen"),
    ("shift", "Shift", False, "Nama shift persis seperti di GajiKita, contoh: Pagi"),
    ("site", "Lokasi Utama", False, "Nama lokasi persis seperti di GajiKita"),
    ("mandor", "No. Karyawan Atasan / Mandor", False, "Untuk persetujuan cuti"),
]
LABELS = {f: title for f, title, _, _ in TEMPLATE_COLUMNS}
REQUIRED_NEW = [f for f, _, req, _ in TEMPLATE_COLUMNS if req]

# other titles HR files often use for the same column
ALIASES = {
    "employee_no": ["nokaryawan", "noinduk", "nip", "idkaryawan", "nopegawai", "employeeno", "employeeid", "nikkaryawan"],
    "full_name": ["nama", "namalengkap", "namakaryawan", "namalengkapsesuaiktp", "name", "fullname"],
    "position": ["jabatan", "posisi", "position"],
    "nik": ["nik", "nikktp", "noktp", "ktp"],
    "npwp": ["npwp"],
    "ptkp_status": ["statusptkp", "ptkp"],
    "join_date": ["tanggalmasuk", "tglmasuk", "joindate", "mulaikerja", "tanggalbergabung"],
    "probation_end_date": ["tanggallolosmagangprobation", "tgllolosmagang", "lolosmagang", "akhirprobation", "tanggallolosmagang"],
    "end_date": ["tanggalkeluar", "tglkeluar", "enddate", "tanggalresign"],
    "employment_type": ["jenishubungankerja", "statuskaryawan", "statuskerja", "jeniskaryawan"],
    "pay_type": ["jenisupah", "sistemupah"],
    "base_rate": ["gajipokokupahrp", "gajipokok", "upah", "basicsalary", "gapok", "upahrp", "gajipokokrp"],
    "fixed_allowance": ["tunjangantetaprp", "tunjangantetap", "tunjangan"],
    "overtime_eligible": ["berhaklembur", "lembur"],
    "bpjs_tk_enrolled": ["terdaftarbpjsketenagakerjaan", "ikutbpjstk", "bpjstk"],
    "bpjs_tk_no": ["nobpjsketenagakerjaan", "nokartubpjstk", "nokartubpjstk", "nobpjstk", "nokartubpjsketenagakerjaan"],
    "bpjs_kesehatan_no": ["nobpjskesehatan", "nobpjskes"],
    "bank_name": ["bank", "namabank"],
    "bank_account_no": ["norekening", "rekening", "nomorrekening", "norek"],
    "bank_account_name": ["namapemilikrekening", "atasnama", "namarekening"],
    "phone": ["nohp", "hp", "nohandphone", "telepon", "nowa", "phone"],
    "fingerprint_id": ["idmesinfingerprint", "idfingerprint", "idmesin", "idfinger", "fingerprintid", "acno"],
    "shift": ["shift", "shiftutama"],
    "site": ["lokasiutama", "lokasi", "site"],
    "mandor": ["nokaryawanatasanmandor", "atasan", "mandor", "noatasan"],
}

PTKP = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"]
EMPLOYMENT = {"pkwtt": "pkwtt", "tetap": "pkwtt", "pkwt": "pkwt", "kontrak": "pkwt", "harianlepas": "harian_lepas",
              "harian": "harian_lepas", "borongan": "borongan"}
PAY = {"bulanan": "monthly", "monthly": "monthly", "harian": "daily", "daily": "daily", "perpekerjaan": "piece",
       "borongan": "piece", "piece": "piece"}
YES = {"ya", "y", "yes", "true", "1", "iya", "v", "x"}
NO = {"tidak", "t", "no", "n", "false", "0", "tdk", "-"}
DIGIT_FIELDS = {"nik", "bank_account_no", "bpjs_tk_no", "bpjs_kesehatan_no"}
MONTHS_ID = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7, "agu": 8, "agt": 8,
             "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}


class FileError(Exception):
    pass


def key(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def match_columns(header):
    """{column index: field}. Exact template titles first, then aliases."""
    by_key = {key(title): f for f, title, _, _ in TEMPLATE_COLUMNS}
    for f, names in ALIASES.items():
        for n in names:
            by_key.setdefault(n, f)
    out, used = {}, set()
    for i, h in enumerate(header):
        f = by_key.get(key(h))
        if f and f not in used:
            out[i] = f
            used.add(f)
    return out


def read_table(filename, data):
    name = (filename or "").lower()
    if name.endswith(".xls"):
        raise FileError("File .xls (Excel lama) belum bisa dibaca. Buka di Excel, Save As → \"Excel Workbook (.xlsx)\", lalu upload lagi.")
    if name.endswith(".xlsx") or data[:2] == b"PK":
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise FileError("File Excel tidak bisa dibuka. Pastikan formatnya .xlsx.")
        ws = wb["Data Karyawan"] if "Data Karyawan" in wb.sheetnames else wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        text = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
    # the header is the first row (of the first 10) that names at least the employee no. and the name
    for i, r in enumerate(rows[:10]):
        fields = set(match_columns(r).values())
        if {"employee_no", "full_name"} <= fields:
            return r, rows[i + 1:], i + 1
    raise FileError("Baris judul tidak ditemukan. Gunakan template GajiKita, atau pastikan ada kolom "
                    "\"No. Karyawan\" dan \"Nama Lengkap\".")


# ── value cleaners: each returns the clean value or raises ValueError(plain message) ──

def to_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, Date)):
        return v.strftime("%d/%m/%Y")
    return re.sub(r"\s+", " ", str(v)).strip()


def to_digits(v):
    if isinstance(v, float):
        v = f"{v:.0f}"                     # 1.234567890123456e15 -> "1234567890123456"
    text = to_text(v)
    digits = re.sub(r"[\s.\-]", "", text)
    if digits and not digits.isdigit():
        raise ValueError("harus berisi angka saja")
    return digits


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, Date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:     # an Excel serial date that lost its format
        from datetime import timedelta
        return Date(1899, 12, 30) + timedelta(days=int(v))
    text = to_text(v)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    m = re.match(r"^(\d{1,2})[\s\-/]([A-Za-z]{3})[A-Za-z]*[\s\-/](\d{2,4})$", text)     # 15-Jul-18, 8 Agustus 2024
    if m and m.group(2).lower() in MONTHS_ID:
        year = int(m.group(3))
        year += 2000 if year < 100 else 0
        return Date(year, MONTHS_ID[m.group(2).lower()], int(m.group(1)))
    raise ValueError("format tanggal tidak dikenal (gunakan DD/MM/YYYY)")


def to_money(v):
    if isinstance(v, (int, float, Decimal)):
        amount = Decimal(str(v))
    else:
        text = to_text(v).lower().replace("rp", "").replace(" ", "")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", text):          # 2.800.000 or 2.800.000,50
            text = text.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):        # 2,800,000
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise ValueError("harus angka rupiah")
    if amount < 0:
        raise ValueError("tidak boleh minus")
    return amount.quantize(Decimal("0.01"))


def to_bool(v):
    if isinstance(v, bool):
        return v
    k = key(v)
    if k == "":                              # "-" and friends
        return False
    if k in YES:
        return True
    if k in NO:
        return False
    raise ValueError("isi Ya atau Tidak")


def to_ptkp(v):
    k = to_text(v).upper().replace(" ", "")
    k = re.sub(r"^(TK|K)/?(\d)$", r"\1/\2", k)
    if k not in PTKP:
        raise ValueError("pilih salah satu: " + ", ".join(PTKP))
    return k


def to_choice(mapping, label):
    def clean(v):
        k = key(v)
        for prefix, value in mapping.items():
            if k == prefix or k.startswith(prefix):
                return value
        raise ValueError(f"{label} tidak dikenal")
    return clean


def to_phone(v):
    digits = to_digits(to_text(v).replace("+", "").replace("(", "").replace(")", ""))
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    elif digits.startswith("8"):
        digits = "0" + digits
    return digits


CLEANERS = {
    "nik": to_digits, "bank_account_no": to_digits, "bpjs_tk_no": to_digits, "bpjs_kesehatan_no": to_digits,
    "npwp": lambda v: re.sub(r"[^\d]", "", to_text(v)),
    "phone": to_phone, "join_date": to_date, "probation_end_date": to_date, "end_date": to_date,
    "base_rate": to_money, "fixed_allowance": to_money, "overtime_eligible": to_bool, "bpjs_tk_enrolled": to_bool,
    "ptkp_status": to_ptkp, "employment_type": to_choice(EMPLOYMENT, "Jenis hubungan kerja"),
    "pay_type": to_choice(PAY, "Jenis upah"),
    "fingerprint_id": lambda v: (to_text(v).lstrip("0") or ("0" if to_text(v) else "")),
}
MAX_LEN = {"employee_no": 30, "full_name": 200, "position": 100, "nik": 16, "npwp": 20, "bank_name": 50,
           "bank_account_no": 30, "bank_account_name": 200, "bpjs_kesehatan_no": 20, "bpjs_tk_no": 20, "phone": 20,
           "fingerprint_id": 30}


def parse_row(cells, columns):
    """One row -> (values, errors, warnings). values only holds non-empty cells."""
    values, errors, warnings = {}, [], []
    for i, f in columns.items():
        raw = cells[i] if i < len(cells) else None
        if raw is None or to_text(raw) == "":
            continue
        try:
            value = CLEANERS.get(f, to_text)(raw)
        except ValueError as err:
            errors.append(f"{LABELS[f]}: {err} (\"{to_text(raw)}\")")
            continue
        if isinstance(value, str) and f in MAX_LEN and len(value) > MAX_LEN[f]:
            errors.append(f"{LABELS[f]}: terlalu panjang (maks. {MAX_LEN[f]} karakter)")
            continue
        values[f] = value
    if values.get("nik") and len(values["nik"]) != 16:
        warnings.append(f"NIK {len(values['nik'])} digit (biasanya 16)")
    if values.get("end_date") and values.get("join_date") and values["end_date"] < values["join_date"]:
        errors.append("Tanggal keluar sebelum tanggal masuk")
    return values, errors, warnings


def parse_rows(header, rows, first_row_number=2):
    """
    Every data row -> dict(row, values, errors, warnings, skip). Rows that are completely empty
    are dropped; the template's hint row and example rows are marked skip with a reason.
    """
    columns = match_columns(header)
    no_col = next(i for i, f in columns.items() if f == "employee_no")
    hints = {key(h) for _, _, _, h in TEMPLATE_COLUMNS if h}
    out, seen = [], {}
    for n, cells in enumerate(rows, start=first_row_number):
        if not any(to_text(c) for c in cells):
            continue
        raw_no = to_text(cells[no_col]) if no_col < len(cells) else ""
        if key(raw_no) in hints:
            out.append({"row": n, "values": {}, "errors": [], "warnings": [], "skip": "Baris petunjuk dari template"})
            continue
        values, errors, warnings = parse_row(cells, columns)
        no = to_text(values.get("employee_no", ""))
        item = {"row": n, "values": values, "errors": errors, "warnings": warnings, "skip": ""}
        if no.upper().startswith("CTH-"):
            item["skip"] = "Baris contoh dari template"
            item["errors"], item["warnings"] = [], []
        elif not no:
            errors.insert(0, "No. Karyawan kosong")
        elif no.lower() in seen:
            errors.insert(0, f"No. Karyawan {no} sudah ada di baris {seen[no.lower()]}")
        else:
            seen[no.lower()] = n
        out.append(item)
    return out, columns


# ── the template HR fills in ──
SAMPLE_ROWS = [
    ["CTH-001", "Budi Santoso", "Driver TM", "1234567890123456", "", "K/1", "15/07/2018", "", "", "PKWTT (tetap)",
     "Bulanan", 2800000, 0, "Ya", "Ya", "22104124288", "", "BCA", "0123456789", "BUDI SANTOSO", "081234567890", 15,
     "Pagi", "Batching Plant", "CTH-002"],
    ["CTH-002", "Andi Wijaya", "Kepala Plant", "", "", "TK/0", "26/01/2023", "", "", "PKWTT (tetap)", "Bulanan",
     7500000, 500000, "Tidak", "Ya", "", "", "Mandiri", "1090012345678", "ANDI WIJAYA", "081298765432", 26, "Pagi",
     "Batching Plant", ""],
]
TEXT_COLUMNS = {"nik", "npwp", "bank_account_no", "phone", "bpjs_tk_no", "bpjs_kesehatan_no"}
LISTS = {"ptkp_status": ",".join(PTKP), "employment_type": "PKWTT (tetap),PKWT (kontrak),Harian lepas,Borongan",
         "pay_type": "Bulanan,Harian,Per pekerjaan", "overtime_eligible": "Ya,Tidak", "bpjs_tk_enrolled": "Ya,Tidak"}
WIDTHS = {"full_name": 28, "bank_account_name": 24, "position": 20, "site": 18}


def build_template():
    """The .xlsx HR downloads from GajiKita: the columns import reads, hints, two example rows, a Petunjuk sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Data Karyawan"
    fields = [c[0] for c in TEMPLATE_COLUMNS]
    for i, (f, title, req, hint) in enumerate(TEMPLATE_COLUMNS, start=1):
        c = ws.cell(row=1, column=i, value=title + (" *" if req else ""))
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F78A8" if req else "013D5A")
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        h = ws.cell(row=2, column=i, value=hint)
        h.font = Font(italic=True, color="5B6B78", size=9)
        h.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(f, 16)
        if f in TEXT_COLUMNS:
            for r in range(3, 2001):
                ws.cell(row=r, column=i).number_format = "@"
        if f in LISTS:
            dv = DataValidation(type="list", formula1=f'"{LISTS[f]}"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(i)}3:{get_column_letter(i)}2000")
    for r, row in enumerate(SAMPLE_ROWS, start=3):
        for i, v in enumerate(row, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.fill = PatternFill("solid", fgColor="FDF0D9")
            if fields[i - 1] in ("base_rate", "fixed_allowance"):
                c.number_format = "#,##0"
    ws.row_dimensions[1].height = 42
    ws.row_dimensions[2].height = 48
    ws.freeze_panes = "C3"

    g = wb.create_sheet("Petunjuk")
    lines = [
        ("Template Data Karyawan GajiKita", True),
        ("", False),
        ("1. Isi satu baris per karyawan di sheet \"Data Karyawan\", mulai baris 3. Kolom bertanda * wajib untuk karyawan baru.", False),
        ("2. Dua baris kuning adalah CONTOH (CTH-001, CTH-002). Boleh dihapus; kalau tidak, GajiKita melewatinya.", False),
        ("3. NIK, No. Rekening, No. HP dan No. BPJS sudah diformat sebagai teks agar angka 0 di depan tidak hilang.", False),
        ("4. Tanggal boleh format tanggal Excel atau DD/MM/YYYY.", False),
        ("5. ID Mesin Fingerprint = nomor ID karyawan di mesin absen. Ini yang menghubungkan data mesin ke karyawan.", False),
        ("6. Shift dan Lokasi: tulis namanya persis seperti di GajiKita. Boleh dikosongkan dan diisi nanti.", False),
        ("7. Data pribadi (NIK, rekening, gaji) bersifat rahasia: kirim langsung ke HR/pemilik, jangan lewat grup.", False),
        ("", False),
        ("Yang terjadi saat diimport", True),
        ("- GajiKita menampilkan pratinjau dulu: karyawan baru, karyawan yang datanya berubah, dan baris yang salah beserta alasannya.", False),
        ("- Tidak ada yang tersimpan sebelum HR menekan Simpan. No. Karyawan yang sudah ada diperbarui, tidak dobel.", False),
        ("- Sel kosong tidak menghapus data yang sudah ada.", False),
    ]
    for r, (text, bold) in enumerate(lines, start=1):
        c = g.cell(row=r, column=1, value=text)
        c.font = Font(bold=bold, size=13 if r == 1 else 11, color="013D5A" if bold else "1A2733")
    g.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
