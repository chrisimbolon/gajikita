# =============================================================================
# === backend/apps/attendance/overtime_import_views.py ===
# =============================================================================
"""
Overtime from HR's recap file (G17-8, 17 Nov 2026).

POST /api/hr/attendance/overtime/import/    multipart: file, machine, commit=0|1, confirm_names=0|1
     commit=0: per person, day by day, what the file pays, what the taps propose and what SeeGaji has decided,
               and what would change (pay / no overtime / changed), plus the days left alone (locked, rejected,
               not entitled, outside employment) and IDs nobody has yet.
     commit=1: the same, then decided. 400 "names_unconfirmed" while a name in the file does not look like the
               matched employee, unless HR ticked "Saya sudah cek" (confirm_names=1). The answer carries
               applied.batch: POST /api/hr/attendance/review/undo/ {"batch"} puts every day back.
     machine:  as for the tap and note imports: "" / "main", a machine id, or "auto" (each block by its Dept.).
"""
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from . import overtime_import
from .day_notes_views import MAX_BYTES, _bad
from .fingerprint import FileError
from .machine_views import resolve_machine
from .machines import AUTO
from .overtime_sheet import read_overtime


class OvertimeImportView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("file")
        if f is None:
            return _bad("Pilih file rekap yang berisi jam lembur per hari.")
        if f.size > MAX_BYTES:
            return _bad("File terlalu besar (maks. 20 MB).")
        try:
            machine = resolve_machine(request.hr_org, request.data.get("machine"))
        except ValueError as err:
            return _bad(str(err))
        try:
            of = read_overtime(f.name, f.read())
        except FileError as err:
            return _bad(str(err))
        if machine == AUTO and not any(b.dept for b in of.people):
            return _bad("File ini tidak punya Dept. di tiap orang, jadi mesinnya tidak bisa dipilih otomatis. "
                        "Pilih mesin asal ID di file ini.")
        p = overtime_import.plan(request.hr_org, of, machine)
        body = {"success": True, "file": f.name, **overtime_import.public(p)}
        if str(request.data.get("commit")) in ("1", "true", "True"):
            confirmed = str(request.data.get("confirm_names", "")).lower() in ("1", "true", "yes")
            wrong = body["totals"]["name_mismatch"]
            if wrong and not confirmed:
                return _bad(f"{wrong} nama di file tidak cocok dengan nama karyawan. Periksa baris yang merah, "
                            f"lalu centang \"Saya sudah cek\" sebelum menyimpan.", "names_unconfirmed")
            if not body["totals"]["todo"]:
                return _bad("Tidak ada lembur yang berubah: semua sudah sama dengan file ini.")
            body["applied"] = overtime_import.apply(request.hr_org, p, request.user, f.name)
        return Response(body)
