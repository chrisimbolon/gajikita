# =============================================================================
# === backend/apps/attendance/day_notes_views.py ===
# =============================================================================
"""
HR's notes per day (G12f.3.1, 10 Nov 2026)

POST /api/hr/attendance/notes/import/    multipart: file, machine, commit=0|1, confirm_names=0|1
     commit=0: what the recap holds (sheet, period, colour legend, who matched, unknown IDs) and what
               would change: new / changed / unchanged / removed notes, locked days left alone.
     commit=1: the same, then saved. Refused (400 "names_unconfirmed") while a name in the file does not
               look like the matched employee, unless HR ticked "Saya sudah cek" (confirm_names=1).
     machine:  as for the tap import: "" / "main", a machine id, or "auto" (each row by its Department).

POST /api/hr/attendance/notes/delete/    {"start", "end", "commit": false, "reason"}
     removes imported notes in a date range (locked days stay); the reason goes into the audit log.
"""
from datetime import timedelta

from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from . import day_notes_import
from .day_notes import read_notes
from .fingerprint import FileError
from .machine_views import resolve_machine
from .machines import AUTO

MAX_BYTES = 20 * 1024 * 1024


def _bad(message, code=None):
    body = {"success": False, "message": message}
    if code:
        body["code"] = code
    return Response(body, status=status.HTTP_400_BAD_REQUEST)


class DayNotesImportView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("file")
        if f is None:
            return _bad("Pilih file rekap yang berisi catatan HR.")
        if f.size > MAX_BYTES:
            return _bad("File terlalu besar (maks. 20 MB).")
        try:
            machine = resolve_machine(request.hr_org, request.data.get("machine"))
        except ValueError as err:
            return _bad(str(err))
        try:
            nf = read_notes(f.name, f.read())
        except FileError as err:
            return _bad(str(err))
        if machine == AUTO and not any(r.dept for r in nf.rows):
            return _bad("File ini tidak punya kolom Department, jadi mesinnya tidak bisa dipilih otomatis. "
                        "Pilih mesin asal ID di file ini.")
        p = day_notes_import.plan(request.hr_org, nf, machine)
        body = {"success": True, "file": f.name, **day_notes_import.public(p)}
        if str(request.data.get("commit")) in ("1", "true", "True"):
            confirmed = str(request.data.get("confirm_names", "")).lower() in ("1", "true", "yes")
            wrong = body["totals"]["name_mismatch"]
            if wrong and not confirmed:
                return _bad(f"{wrong} nama di file tidak cocok dengan nama karyawan. Periksa baris yang merah, "
                            f"lalu centang \"Saya sudah cek\" sebelum menyimpan.", "names_unconfirmed")
            body["applied"] = day_notes_import.apply(request.hr_org, p, request.user, f.name)
        return Response(body)


class NotesDeleteSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    commit = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError({"end": "Tanggal akhir sebelum tanggal awal."})
        if attrs["end"] - attrs["start"] > timedelta(days=92):
            raise serializers.ValidationError({"end": "Maksimal 3 bulan sekali hapus."})
        if attrs["commit"] and len(attrs["reason"].strip()) < 5:
            raise serializers.ValidationError({"reason": "Tulis alasan menghapus (minimal 5 huruf)."})
        return attrs


class DayNotesDeleteView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        ser = NotesDeleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        p = day_notes_import.delete_plan(request.hr_org, d["start"], d["end"])
        body = {"success": True, **day_notes_import.delete_public(p)}
        if d["commit"]:
            if not p["remove"]:
                return _bad("Tidak ada catatan import yang bisa dihapus di tanggal ini.")
            body["applied"] = day_notes_import.delete_apply(request.hr_org, p, request.user, d["reason"].strip())
        return Response(body)
