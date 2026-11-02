# =============================================================================
# === backend/apps/attendance/fingerprint_delete_views.py ===
# =============================================================================
"""
POST /api/hr/attendance/fingerprint/delete/    (G9b, 2 Nov 2026)
  {"start": "2026-10-26", "end": "2026-11-25", "keep_decided": true, "commit": false}
      what would be removed (taps, days, people, locked days skipped, days HR already decided)
  the same with "commit": true and "reason": "..."   removes it; the reason goes into the audit log.
"""
from datetime import timedelta

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from . import fingerprint_delete


class DeleteSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    keep_decided = serializers.BooleanField(required=False, default=True)
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


class FingerprintDeleteView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        ser = DeleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        p = fingerprint_delete.plan(request.hr_org, d["start"], d["end"], d["keep_decided"])
        body = {"success": True, **fingerprint_delete.public(p)}
        if d["commit"]:
            if not p["remove"]:
                return Response({"success": False, "message": "Tidak ada tap fingerprint yang bisa dihapus di tanggal ini."},
                                status=status.HTTP_400_BAD_REQUEST)
            body["applied"] = fingerprint_delete.apply(request.hr_org, p, request.user, d["reason"].strip())
        return Response(body)
