# =============================================================================
# === backend/apps/employees/import_mapping.py ===
# =============================================================================
"""
"Import dari file apa saja" (G9d, 3 Nov 2026). Pure Python + openpyxl, no Django.

A company with 1,000 employees already has them in some Excel (old HRIS, payroll sheet, bank
list, BPJS report). Instead of retyping into our template, HR uploads that file and:

  1. find_table()      finds the sheet and the title row by itself (any sheet, any of the
                       first 15 rows), using the column titles we know plus what this company
                       chose last time.
  2. match()           column -> field: this company's saved choices first, then the template
                       titles and their aliases. HR can change any column in the preview.
  3. apply_values()    their own words -> ours ("Tetap" -> PKWTT, "BP Uban" -> lokasi "Batching
                       Plant"), from the choices HR made once in the preview.
  4. unknown_values()  which words we could not read, once per word with how many rows use it,
                       so HR maps 3 words instead of fixing 300 rows.
  5. error_report()    an .xlsx of only the rows with errors, their original cells + "Masalah",
                       so HR fixes those and uploads just that file.

Saved choices are keyed by the column title with spaces and punctuation removed (importer.key),
so "NAMA PEGAWAI" and "Nama  Pegawai." are the same column.
"""
import csv
import io

from apps.core.legacy_excel import LegacyExcelError, is_legacy_excel, read_legacy_excel

from .importer import (EMPLOYMENT, LABELS, PAY, PTKP, REQUIRED_NEW, TEMPLATE_COLUMNS, FileError, key,
                       match_columns, parse_row, to_text)

IGNORE = "-"                     # a saved choice meaning "this column is not imported"
MAX_SCAN_ROWS = 15
SAMPLE_COUNT = 3

# fields whose words HR can map once for the whole file, and the words we accept for each
VALUE_FIELDS = {
    "employment_type": [("PKWTT (tetap)", "PKWTT (tetap)"), ("PKWT (kontrak)", "PKWT (kontrak)"),
                        ("Harian lepas", "Harian lepas"), ("Borongan", "Borongan")],
    "pay_type": [("Bulanan", "Bulanan"), ("Harian", "Harian"), ("Per pekerjaan", "Per pekerjaan")],
    "ptkp_status": [(p, p) for p in PTKP],
    "overtime_eligible": [("Ya", "Ya"), ("Tidak", "Tidak")],
    "bpjs_tk_enrolled": [("Ya", "Ya"), ("Tidak", "Tidak")],
}
LOOKUP_FIELDS = ("shift", "site")             # mapped to names that exist in the company (import_wizard)


def fields_list():
    return [{"field": f, "label": title, "required": req} for f, title, req, _ in TEMPLATE_COLUMNS]


# ── 1. the sheet and the title row ──

def read_sheets(filename, data):
    """[(sheet name, rows)] of an .xlsx (every sheet) or a CSV (one)."""
    name = (filename or "").lower()
    if is_legacy_excel(name, data):                       # G12a
        try:
            sheets = read_legacy_excel(data)
        except LegacyExcelError as err:
            raise FileError(str(err))
        if sheets is not None:
            return sheets
        # text saved with an .xls name: read below like a CSV
    elif name.endswith(".xlsx") or data[:2] == b"PK":
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise FileError("File Excel tidak bisa dibuka. Pastikan formatnya .xlsx.")
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
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
    return [("CSV", list(csv.reader(io.StringIO(text), dialect)))]


def match(header, saved=None):
    """{column index: field}. This company's saved choices win, then template titles and aliases.
    A field is used once (the first column that claims it)."""
    saved = saved or {}
    auto = match_columns(header)
    out, used = {}, set()
    for i, h in enumerate(header):
        k = key(h)
        if not k:
            continue
        f = saved.get(k) if k in saved else auto.get(i)
        if f and f != IGNORE and f in LABELS and f not in used:
            out[i] = f
            used.add(f)
    return out


def _score(row, saved):
    fields = set(match(row, saved).values())
    return (("employee_no" in fields) + ("full_name" in fields), len(fields))


def find_table(sheets, saved=None, sheet=None):
    """
    The sheet and title row to import: the one where we recognise the most columns (No. Karyawan
    and Nama count most). With nothing recognised, the first row with 2+ filled cells of the first
    non-empty sheet, so HR can map the columns by hand. -> dict(sheet, sheets, header, rows, header_row)
    """
    names = [n for n, _ in sheets]
    best = None
    for n, rows in sheets:
        if sheet and n != sheet:
            continue
        for i, r in enumerate(rows[:MAX_SCAN_ROWS]):
            if sum(1 for c in r if to_text(c)) < 2:
                continue
            s = _score(r, saved)
            if best is None or s > best[0]:
                best = (s, n, i, rows)
    if best is None or best[0] == (0, 0):
        for n, rows in sheets:
            if sheet and n != sheet:
                continue
            for i, r in enumerate(rows[:MAX_SCAN_ROWS]):
                if sum(1 for c in r if to_text(c)) >= 2:
                    best = ((0, 0), n, i, rows)
                    break
            if best:
                break
    if best is None:
        raise FileError("File ini kosong: tidak ada baris dengan isi.")
    _, n, i, rows = best
    header = [to_text(c) for c in rows[i]]
    body = rows[i + 1:]                              # empty rows kept, so row numbers stay true
    numbered = [(i + 2 + k, r) for k, r in enumerate(body) if any(to_text(c) for c in r)]
    return {"sheet": n, "sheets": names, "header": header, "rows": body, "numbered": numbered,
            "header_row": i + 1, "first_row": i + 2}


def columns_info(header, rows, columns, auto=None):
    """What the preview shows per column: title, chosen field, how it was chosen, a few examples."""
    auto = auto if auto is not None else match_columns(header)
    out = []
    for i, title in enumerate(header):
        if not title:
            continue
        sample = []
        for r in rows:
            v = to_text(r[i]) if i < len(r) else ""
            if v and v not in sample:
                sample.append(v)
            if len(sample) >= SAMPLE_COUNT:
                break
        out.append({"index": i, "title": title, "key": key(title), "field": columns.get(i, ""),
                    "auto": columns.get(i) is not None and auto.get(i) == columns.get(i), "sample": sample})
    return out


# ── 3. their words -> ours ──

def apply_values(rows, columns, value_map):
    """rows with mapped words replaced; value_map = {field: {key(their word): our word ("" = leave empty)}}."""
    if not value_map:
        return rows
    by_col = {i: value_map[f] for i, f in columns.items() if value_map.get(f)}
    if not by_col:
        return rows
    out = []
    for r in rows:
        r = list(r)
        for i, words in by_col.items():
            if i < len(r):
                k = key(r[i])
                if k and k in words:
                    r[i] = words[k] or None
        out.append(r)
    return out


def unknown_values(rows, columns, value_map=None, lookups=None):
    """
    The words we could not read, once each: [{field, label, raw, key, count, options, mapped}].
    lookups = {"shift": [names], "site": [names]} (what exists in the company).
    """
    lookups = lookups or {}
    value_map = value_map or {}
    found = {}
    for i, f in columns.items():
        if f not in VALUE_FIELDS and f not in LOOKUP_FIELDS:
            continue
        known = {key(n) for n in lookups.get(f, [])}
        for r in rows:
            raw = to_text(r[i]) if i < len(r) else ""
            k = key(raw)
            if not k:
                continue
            if f in LOOKUP_FIELDS:
                bad = k not in known
            else:
                values, errors, _ = parse_row([raw], {0: f})
                bad = bool(errors)
            if bad:
                item = found.setdefault((f, k), {"field": f, "label": LABELS[f], "raw": raw, "key": k, "count": 0})
                item["count"] += 1
    out = []
    for (f, k), item in sorted(found.items(), key=lambda kv: (list(LABELS).index(kv[0][0]), -kv[1]["count"])):
        options = VALUE_FIELDS.get(f) or [(n, n) for n in lookups.get(f, [])]
        item["options"] = [{"value": v, "label": l} for v, l in options]
        item["mapped"] = value_map.get(f, {}).get(k)
        out.append(item)
    return out


# ── 5. only the rows with errors, to fix and upload again ──

def error_report(header, numbered, plan):
    """.xlsx bytes: the title row + every row whose preview result is an error, with a "Masalah" column."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    bad = {r["row"]: r for r in plan if r["action"] == "error"}
    wb = Workbook()
    ws = wb.active
    ws.title = "Perlu diperbaiki"
    ws.append(["Baris di file asli"] + list(header) + ["Masalah"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="013D5A")
    for n, cells in numbered:
        if n in bad:
            values = list(cells) + [None] * max(0, len(header) - len(cells))
            ws.append([n] + values[:len(header)] + ["; ".join(bad[n]["errors"])])
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions[ws.cell(row=1, column=len(header) + 2).column_letter].width = 60
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def missing_required(columns):
    found = set(columns.values())
    return [LABELS[f] for f in REQUIRED_NEW if f not in found]
