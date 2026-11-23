# =============================================================================
# === backend/apps/payroll/final_pay_views.py ===
# =============================================================================
"""
G16-4 (23 Nov 2026) — Karyawan -> "Hitung hak akhir" (see final_pay.py).

  GET    payroll/final-pay/?employee=<id>   the employee, the reasons, the defaults, the saved statements
  POST   payroll/final-pay/preview/         calculate without saving
  POST   payroll/final-pay/                 save (new, or "id" to update); audit "payroll.final_pay"
  POST   payroll/final-pay/<id>/attach/     put it on the last payslip (draft payroll), fill the end date
  DELETE payroll/final-pay/<id>/            delete (and take it off a draft payslip)
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from . import final_pay as F
from .models import FinalPay, PayrollSettings


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "message": message}, status=code)


class OverrideField(serializers.DictField):
    child = serializers.DictField()


class FinalPayInput(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    employee = serializers.UUIDField()
    end_date = serializers.DateField()
    reason = serializers.ChoiceField(choices=list(F.REASONS))
    upah = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False,
                                    allow_null=True)
    leave_days = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0"), required=False,
                                          allow_null=True)
    travel = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False,
                                      default=Decimal("0"))
    other_items = serializers.ListField(child=serializers.DictField(), required=False, default=list, max_length=10)
    overrides = OverrideField(required=False, default=dict)
    deduct_loan = serializers.BooleanField(required=False, default=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    def validate_overrides(self, v):
        for key, o in v.items():
            amount = o.get("amount")
            if amount in (None, ""):
                continue
            try:
                if Decimal(str(amount)) < 0:
                    raise ValueError
            except Exception:
                raise serializers.ValidationError(f"Angka untuk {key} tidak valid.")
            if not str(o.get("reason") or "").strip():
                raise serializers.ValidationError("Isi alasan untuk setiap angka yang diubah dari UU.")
        return v


def _employee(org, pk):
    return Employee.objects.filter(organization=org, pk=pk).first()


def _calculate(org, employee, d):
    """Validated input -> (statement, upah_used, leave_used, upah_note)."""
    cfg = PayrollSettings.for_org(org)
    auto_upah, upah_note = F.upah_for(employee, cfg, d["end_date"])
    upah = d.get("upah") if d.get("upah") is not None else auto_upah
    leave = d.get("leave_days") if d.get("leave_days") is not None else F.leave_left(employee, d["end_date"])
    result = F.compute(F.Inputs(
        reason=d["reason"], join_date=employee.join_date, end_date=d["end_date"], upah=upah,
        daily_divisor=cfg.daily_divisor, leave_days=leave, travel=d.get("travel") or Decimal("0"),
        other_items=d.get("other_items") or [], separation_months=cfg.separation_pay_months,
        overrides=d.get("overrides") or {}, small_business=cfg.small_business,
        is_pkwt=employee.employment_type == Employee.EmploymentType.PKWT))
    if d.get("upah") is not None and F.rupiah(d["upah"]) != auto_upah:
        result["notes"].append(f"Upah diubah HR (dari data Karyawan: Rp {int(auto_upah):,}).".replace(",", "."))
    result["upah_note"] = upah_note if d.get("upah") is None else "diisi HR"
    run = F.run_for(employee, d["end_date"])
    owed = F.loan_balance(employee, run)
    result["loan"] = {"balance": str(owed), "deducted": bool(d.get("deduct_loan")) and owed > 0}
    result["paid_out"] = str(Decimal(result["net"]) - (owed if result["loan"]["deducted"] else 0))
    return result, upah, leave


def _record(r):
    return {"id": str(r.pk), "end_date": r.end_date.isoformat(), "reason": r.reason,
            "upah": None if r.upah is None else str(r.upah), "leave_days": None if r.leave_days is None else str(r.leave_days),
            "travel": str(r.travel), "other_items": r.other_items, "overrides": r.overrides,
            "deduct_loan": r.deduct_loan, "note": r.note, "result": r.result,
            "run": {"id": str(r.run_id), "name": r.run.name, "locked": r.run.is_locked} if r.run_id else None,
            "attached_at": r.attached_at.isoformat() if r.attached_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


class FinalPayView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        org = request.hr_org
        employee = _employee(org, request.query_params.get("employee"))
        if employee is None:
            return _bad("Karyawan tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        cfg = PayrollSettings.for_org(org)
        end = employee.end_date or timezone.localdate()
        upah, upah_note = F.upah_for(employee, cfg, end)
        return Response({
            "success": True,
            "employee": {"id": str(employee.pk), "employee_no": employee.employee_no, "full_name": employee.full_name,
                         "position": employee.position, "join_date": employee.join_date.isoformat(),
                         "end_date": employee.end_date.isoformat() if employee.end_date else None,
                         "employment_type": employee.employment_type, "pay_type": employee.pay_type},
            "reasons": [{"value": r.key, "label": r.label, "article": r.article} for r in F.REASONS.values()],
            "defaults": {"end_date": end.isoformat(), "upah": str(upah), "upah_note": upah_note,
                         "leave_days": str(F.leave_left(employee, end)), "separation_pay_months": str(cfg.separation_pay_months),
                         "small_business": cfg.small_business, "daily_divisor": cfg.daily_divisor,
                         "reason": "contract_end" if employee.employment_type == Employee.EmploymentType.PKWT else "resign"},
            "records": [_record(r) for r in FinalPay.objects.filter(organization=org, employee=employee)
                        .select_related("run").order_by("-end_date", "-updated_at")],
        })

    def post(self, request):
        org = request.hr_org
        ser = FinalPayInput(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        employee = _employee(org, d["employee"])
        if employee is None:
            return _bad("Karyawan tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        try:
            result, upah, leave = _calculate(org, employee, d)
        except ValueError as err:
            return _bad(str(err))
        with transaction.atomic():
            record = None
            if d.get("id"):
                record = FinalPay.objects.filter(organization=org, employee=employee, pk=d["id"]).first()
                if record is None:
                    return _bad("Hitungan hak akhir tidak ditemukan.", status.HTTP_404_NOT_FOUND)
                if record.run_id and record.run.is_locked:
                    return _bad(f"{record.run.name} sudah dikunci. Hitungan ini tidak bisa diubah lagi.")
            before = None if record is None else {"total": record.result.get("total"), "reason": record.reason}
            if record is None:
                record = FinalPay(organization=org, employee=employee, created_by=request.user)
            record.end_date, record.reason = d["end_date"], d["reason"]
            record.upah, record.leave_days = d.get("upah"), d.get("leave_days")
            record.travel, record.other_items = d.get("travel") or Decimal("0"), d.get("other_items") or []
            record.overrides, record.deduct_loan, record.note = d.get("overrides") or {}, d["deduct_loan"], d["note"]
            record.result = result
            record.save()
            record_audit(organization=org, actor=request.user, action="payroll.final_pay", target=employee,
                         summary=f"Hak akhir {employee.full_name}: {result['reason_label']}, total Rp {result['total']}",
                         before=before, after={"total": result["total"], "reason": record.reason,
                                               "changed": [l["key"] for l in result["lines"] if l["changed"]]})
        message = "Hitungan hak akhir disimpan."
        if record.run_id and not record.run.is_locked:
            message += " Klik \"Masukkan ke slip\" lagi supaya slip ikut berubah."
        return Response({"success": True, "message": message, "record": _record(record)})


class FinalPayPreviewView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        org = request.hr_org
        ser = FinalPayInput(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        employee = _employee(org, d["employee"])
        if employee is None:
            return _bad("Karyawan tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        try:
            result, _, _ = _calculate(org, employee, d)
        except ValueError as err:
            return _bad(str(err))
        return Response({"success": True, "result": result})


class FinalPayDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def _get(self, request, pk):
        return FinalPay.objects.filter(organization=request.hr_org, pk=pk).select_related("employee", "run").first()

    def delete(self, request, pk):
        record = self._get(request, pk)
        if record is None:
            return _bad("Hitungan hak akhir tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                F.detach(record)
                record_audit(organization=request.hr_org, actor=request.user, action="payroll.final_pay_delete",
                             target=record.employee, summary=f"Hak akhir {record.employee.full_name} dihapus",
                             before={"total": record.result.get("total")}, after=None)
                record.delete()
        except F.AttachError as err:
            return _bad(str(err))
        return Response({"success": True, "message": "Hitungan hak akhir dihapus."})


class FinalPayAttachView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        record = FinalPay.objects.filter(organization=request.hr_org, pk=pk).select_related("employee", "run").first()
        if record is None:
            return _bad("Hitungan hak akhir tidak ditemukan.", status.HTTP_404_NOT_FOUND)
        cfg = PayrollSettings.for_org(request.hr_org)
        try:
            with transaction.atomic():
                if record.run_id and not record.run.is_locked and record.run_id != getattr(
                        F.run_for(record.employee, record.end_date), "pk", None):
                    F.detach(record)                     # the end date moved to another payroll
                run = F.attach(record, cfg)
                record.run, record.attached_at = run, timezone.now()
                record.save(update_fields=["run", "attached_at", "updated_at"])
                record_audit(organization=request.hr_org, actor=request.user, action="payroll.final_pay_attach",
                             target=record.employee, summary=f"Hak akhir {record.employee.full_name} masuk {run.name}",
                             before=None, after={"run": run.name, "total": record.result.get("total")})
        except F.AttachError as err:
            return _bad(str(err))
        return Response({"success": True, "record": _record(record),
                         "message": f"Hak akhir masuk slip {record.employee.full_name} di {run.name}. Tanggal keluar "
                                    f"diisi {record.end_date:%d-%m-%Y}. Klik Hitung ulang di {run.name} supaya hari "
                                    f"setelah tanggal keluar tidak dibayar."})
