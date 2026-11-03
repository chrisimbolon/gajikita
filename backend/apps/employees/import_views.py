# =============================================================================
# === backend/apps/employees/import_views.py ===
# =============================================================================
"""
Employee import screens (G9, 1 Nov 2026).

  GET  /api/hr/employees/import/template/   the .xlsx template (built from importer.TEMPLATE_COLUMNS)
  POST /api/hr/employees/import/            multipart: file, commit=0|1
                                            commit=0: the preview (nothing is saved)
                                            commit=1: the same check again, then save every
                                            create/update row (rows with errors are left out)
"""
from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from .import_service import apply_import, plan_import, public, summary
from .importer import LABELS, REQUIRED_NEW, FileError, build_template, match_columns, parse_rows, read_table

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000


def read_upload(request):
    f = request.FILES.get("file")
    if f is None:
        raise FileError("Pilih file Excel (.xlsx) atau CSV.")
    if f.size > MAX_BYTES:
        raise FileError("File terlalu besar (maks. 10 MB).")
    return f.name, f.read()


class EmployeeTemplateView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        resp = HttpResponse(build_template(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="Template_Data_Karyawan_GajiKita.xlsx"'
        return resp


class EmployeeImportView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from .import_wizard import handle          # G9d: our template or the company's own file
        return handle(request)

    def post_template_only(self, request):         # the G9 version, kept for reference
        try:
            name, data = read_upload(request)
            header, rows, header_row = read_table(name, data)
        except FileError as err:
            return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        if len(rows) > MAX_ROWS:
            return Response({"success": False, "message": f"Maksimal {MAX_ROWS} baris per import."},
                            status=status.HTTP_400_BAD_REQUEST)
        items, columns = parse_rows(header, rows, header_row + 1)
        found = set(columns.values())
        plan = plan_import(request.hr_org, items)
        body = {
            "success": True, "file": name,
            "columns_found": [LABELS[f] for f in LABELS if f in found],
            "columns_missing": [LABELS[f] for f in REQUIRED_NEW if f not in found],
            "columns_ignored": [str(h).strip() for i, h in enumerate(header)
                                if i not in columns and h is not None and str(h).strip()],     # G9c
            "counts": summary(plan), "rows": public(plan),
        }
        if str(request.data.get("commit")) in ("1", "true", "True"):
            body["applied"] = apply_import(request.hr_org, plan, request.user)
        return Response(body)
