# =============================================================================
# === backend/apps/attendance/fingerprint_views.py ===
# =============================================================================
"""
POST /api/hr/attendance/fingerprint/import/   multipart: file, commit=0|1   (G9, 1 Nov 2026)

  commit=0: what the file holds (format, period, who matched, unknown machine IDs, how many days
            are new / already imported / locked). Nothing is saved.
  commit=1: the same, then the new taps are saved. Importing the same file again adds nothing.
  machine:  G12f.1a. "" or "main" = the main machine (the IDs on the employee), a machine id, or
            "auto" = each block of a combined report goes to the machine that owns its Dept.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from . import fingerprint_import
from .fingerprint import FileError, read_punches
from .machine_views import resolve_machine
from .machines import AUTO

MAX_BYTES = 20 * 1024 * 1024


class FingerprintImportView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("file")
        if f is None:
            return Response({"success": False, "message": "Pilih file dari mesin fingerprint."},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > MAX_BYTES:
            return Response({"success": False, "message": "File terlalu besar (maks. 20 MB)."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            machine = resolve_machine(request.hr_org, request.data.get("machine"))     # G12f.1a
        except ValueError as err:
            return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            punches, unreadable, label = read_punches(f.name, f.read())
        except FileError as err:
            return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        if machine == AUTO and not any(p.dept for p in punches):
            return Response({"success": False,
                             "message": "File ini tidak punya kolom Dept., jadi mesinnya tidak bisa dipilih "
                                        "otomatis. Pilih mesin asal file ini."},
                            status=status.HTTP_400_BAD_REQUEST)
        p = fingerprint_import.plan(request.hr_org, punches, machine)
        body = {"success": True, "file": f.name, "format": label, "punches": len(punches), "unreadable": unreadable,
                **fingerprint_import.public(p)}
        if str(request.data.get("commit")) in ("1", "true", "True"):
            body["applied"] = fingerprint_import.apply(request.hr_org, p, request.user, f.name)
        return Response(body)
