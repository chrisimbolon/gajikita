# =============================================================================
# === backend/apps/employees/import_wizard.py ===
# =============================================================================
"""
POST /api/hr/employees/import/   (G9d, 3 Nov 2026: "Import dari file apa saja")

  multipart:
    file        .xlsx (any sheet) or .csv, our template or the company's own file
    commit      0 = preview (nothing saved), 1 = save
    mapping     JSON {column title key: field | "-"}           HR's column choices in the preview
    values      JSON {field: {their word key: our word | ""}}   HR's word choices in the preview
    sheet       which sheet (when the file has several)
    report      1 = download only the rows with errors (.xlsx), to fix and upload again
    reset       1 = ignore what this company chose last time

  On save, the column and word choices are remembered for the company (EmployeeImportProfile),
  so next month's file imports in one click. Nothing else changes: matching by No. Karyawan,
  empty cells never wipe data, rows with errors are left out, one transaction, one audit entry.
"""
import json

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from apps.sites.models import Shift, Site

from . import import_mapping as im
from .import_service import apply_import, plan_import, public, summary
from .importer import LABELS, FileError, key, parse_rows
from .models import EmployeeImportProfile

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _flag(request, name):
    return str(request.data.get(name, "")) in ("1", "true", "True")


def _json(request, name):
    raw = request.data.get(name)
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise FileError("Pilihan kolom tidak terbaca. Muat ulang halaman lalu coba lagi.")
    return value if isinstance(value, dict) else {}


def _clean_mapping(raw):
    return {str(k): str(v) for k, v in raw.items() if k and (v in LABELS or v == im.IGNORE)}


def _clean_values(raw, lookups):
    out = {}
    for field, words in raw.items():
        if not isinstance(words, dict):
            continue
        if field in im.VALUE_FIELDS:
            allowed = {v for v, _ in im.VALUE_FIELDS[field]}
        elif field in im.LOOKUP_FIELDS:
            allowed = set(lookups.get(field, []))
        else:
            continue
        clean = {str(k): str(v) for k, v in words.items() if k and (v == "" or v in allowed)}
        if clean:
            out[field] = clean
    return out


def handle(request):
    org = request.hr_org
    lookups = {"shift": list(Shift.objects.filter(organization=org).order_by("name").values_list("name", flat=True)),
               "site": list(Site.objects.filter(organization=org).order_by("name").values_list("name", flat=True))}
    profile = None if _flag(request, "reset") else EmployeeImportProfile.objects.filter(organization=org).first()
    try:
        f = request.FILES.get("file")
        if f is None:
            raise FileError("Pilih file Excel (.xlsx) atau CSV.")
        if f.size > MAX_BYTES:
            raise FileError("File terlalu besar (maks. 10 MB).")
        chosen = _clean_mapping(_json(request, "mapping"))
        mapping = {**(profile.column_map if profile else {}), **chosen}
        values = _clean_values(profile.value_map if profile else {}, lookups)
        for field, words in _clean_values(_json(request, "values"), lookups).items():
            values.setdefault(field, {}).update(words)
        table = im.find_table(im.read_sheets(f.name, f.read()), mapping, request.data.get("sheet") or None)
    except FileError as err:
        return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
    if len(table["numbered"]) > MAX_ROWS:
        return Response({"success": False, "message": f"Maksimal {MAX_ROWS} baris per import. Pecah file-nya jadi beberapa."},
                        status=status.HTTP_400_BAD_REQUEST)

    header = table["header"]
    columns = im.match(header, mapping)
    info = im.columns_info(header, table["rows"], columns)
    body = {
        "success": True, "file": f.name, "sheet": table["sheet"], "sheets": table["sheets"],
        "header_row": table["header_row"], "profile_used": bool(profile and (profile.column_map or profile.value_map)),
        "columns": info, "fields": im.fields_list(),
        "columns_found": [LABELS[x] for x in LABELS if x in set(columns.values())],
        "columns_missing": im.missing_required(columns),
        "columns_ignored": [c["title"] for c in info if not c["field"]],
        "unknown_values": [],
        "counts": {k: 0 for k in ("create", "update", "same", "error", "skip")}, "rows": [],
        "needs_mapping": "employee_no" not in columns.values(),
    }
    if body["needs_mapping"]:
        body["message"] = "Kolom No. Karyawan belum ditemukan. Pilih di daftar kolom, kolom mana yang berisi No. Karyawan."
        return Response(body)

    rows = im.apply_values(table["rows"], columns, values)
    items, _ = parse_rows(header, rows, table["first_row"], columns=columns)
    plan = plan_import(org, items)
    if _flag(request, "report"):
        resp = HttpResponse(im.error_report(header, table["numbered"], plan), content_type=XLSX)
        resp["Content-Disposition"] = 'attachment; filename="Perbaiki_Data_Karyawan.xlsx"'
        return resp

    body.update(counts=summary(plan), rows=public(plan),
                unknown_values=im.unknown_values(table["rows"], columns, values, lookups))
    if _flag(request, "commit"):
        body["applied"] = apply_import(org, plan, request.user)
        p, _ = EmployeeImportProfile.objects.get_or_create(organization=org)
        # remember what was imported, and the columns HR switched off on purpose
        p.column_map = {**(p.column_map or {}), **{key(header[i]): fld for i, fld in columns.items()},
                        **{k: v for k, v in chosen.items() if v == im.IGNORE}}
        p.value_map = values
        p.updated_by = request.user
        p.save()
    return Response(body)
