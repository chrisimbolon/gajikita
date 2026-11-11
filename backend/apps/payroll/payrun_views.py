# =============================================================================
# === backend/apps/payroll/payrun_views.py ===
# =============================================================================
"""
HR's payroll screens (G8b part 1, 1 Nov 2026). All under /api/hr/payroll/.

  GET/PATCH  settings/                       the company's payroll settings
  GET/POST   runs/                           list / create {month: "2026-10"} (the period that ENDS that month)
  GET/DELETE runs/<id>/                      the register (one row per employee) / delete a draft
  POST       runs/<id>/recalculate/          re-read attendance and leave, recalculate everyone
  POST       runs/<id>/lock/                 {action: lock | reopen, note}
  GET/PATCH  runs/<id>/lines/<line>/         one employee: numbers, corrections, items, slip
  POST       runs/<id>/lines/<line>/items/   add an item {kind, label, amount, quantity, unit, recurring, note}
  DELETE     runs/<id>/items/<item>/         remove an item
"""
import re
from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.organizations.permissions import IsCompanyHR

from .models import PayrollSettings, PayRun, PayRunItem, PayRunLine
from .payrun import OVERRIDE_FIELDS, PayrollError, calculate_line, calculate_run, create_run, lock_run, reopen_run

LOCKED = "Payroll ini sudah dikunci. Buka kunci dulu untuk mengubah."


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "message": message}, status=code)


# ── settings ──

class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollSettings
        exclude = ["id", "organization"]
        read_only_fields = ["updated_at"]

    def validate_period_start_day(self, v):
        if not 1 <= v <= 28:
            raise serializers.ValidationError("Pilih tanggal 1 sampai 28.")
        return v

    def validate_pay_day(self, v):
        if not 1 <= v <= 28:
            raise serializers.ValidationError("Pilih tanggal 1 sampai 28.")
        return v

    def validate_overtime_min_minutes(self, v):                                         # G12e
        if v > 240:
            raise serializers.ValidationError("Paling lama 240 menit.")
        return v

    def validate_overtime_daily_cap_minutes(self, v):                                  # G12g
        if v is not None and not 30 <= v <= 24 * 60:
            raise serializers.ValidationError("Isi 30 sampai 1440 menit, atau kosongkan untuk tanpa batas.")
        return v

    def validate_night_ot_rules(self, v):                                              # G12e
        from apps.attendance.night_rules import RuleError, parse_rules
        try:
            parse_rules(v)
        except RuleError as e:
            raise serializers.ValidationError(str(e))
        return v or []

    def validate_daily_divisor(self, v):
        if v not in (21, 25, 26, 30, 31):
            raise serializers.ValidationError("Pembagi yang umum: 21, 25, 26, 30 atau 31.")
        return v

    def validate(self, attrs):
        mode = attrs.get("overtime_mode", getattr(self.instance, "overtime_mode", ""))
        hour = attrs.get("flat_overtime_hour", getattr(self.instance, "flat_overtime_hour", 0))
        if mode == PayrollSettings.OvertimeMode.FLAT and not hour:
            raise serializers.ValidationError({"flat_overtime_hour": "Isi tarif lembur per jam."})
        return attrs


class SettingsView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response({"success": True, "settings": SettingsSerializer(PayrollSettings.for_org(request.hr_org)).data})

    def patch(self, request):
        cfg = PayrollSettings.for_org(request.hr_org)
        before = SettingsSerializer(cfg).data
        ser = SettingsSerializer(cfg, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        changed = {k: v for k, v in ser.data.items() if before.get(k) != v and k != "updated_at"}
        if changed:
            record_audit(organization=request.hr_org, actor=request.user, action="payroll.settings", target=cfg,
                         summary="Pengaturan payroll diubah: " + ", ".join(changed),
                         before={k: before[k] for k in changed}, after=changed)
        return Response({"success": True, "settings": ser.data})


# ── runs ──

def _run_summary(run):
    lines = list(run.lines.all())
    return {
        "id": str(run.id), "name": run.name, "status": run.status, "status_label": run.get_status_display(),
        "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
        "pay_date": run.pay_date.isoformat() if run.pay_date else None,
        "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
        "locked_at": run.locked_at.isoformat() if run.locked_at else None,
        "locked_by": run.locked_by.full_name if run.locked_by else None,
        "people": len(lines),
        "gross": _money(sum((l.gross for l in lines), Decimal("0"))),
        "deductions": _money(sum((l.deductions for l in lines), Decimal("0"))),
        "net": _money(sum((l.net for l in lines), Decimal("0"))),
        "employer_cost": _money(sum((l.employer_cost for l in lines), Decimal("0"))),
        "warnings": sum(l.warning_count for l in lines),
    }


def _runs(org):
    return PayRun.objects.filter(organization=org).select_related("locked_by")


def _register(run):
    """Every line with its amounts by component, and the columns present, in slip order."""
    columns, rows = {}, []
    lines = run.lines.select_related("employee").order_by("employee__full_name")
    for l in lines:
        amounts = {}
        for side in ("earnings", "deductions"):
            for x in (l.result or {}).get(side, []):
                columns.setdefault(x["code"], {"code": x["code"], "label": x["label"], "side": side})
                amounts[x["code"]] = str(Decimal(amounts.get(x["code"], "0")) + Decimal(x["amount"]))
        a = l.auto or {}
        rows.append({
            "id": str(l.id),
            "employee": {"id": str(l.employee.id), "employee_no": l.employee.employee_no,
                         "full_name": l.employee.full_name},
            "amounts": amounts, "gross": _money(l.gross), "deductions": _money(l.deductions), "net": _money(l.net),
            "warning_count": l.warning_count, "corrected": bool(l.override),
            "present_days": a.get("present_days", 0), "absent_days": a.get("absent_days", 0),
            "review_days": a.get("review_days", 0),
            "exempt_days": a.get("exempt_days", 0), "exempt_reason": a.get("exempt_reason", ""),   # G12i
        })
    order = {"earnings": 0, "deductions": 1}
    return sorted(columns.values(), key=lambda c: order[c["side"]]), rows


class RunListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        runs = _runs(request.hr_org).prefetch_related("lines")
        return Response({"success": True, "runs": [_run_summary(r) for r in runs]})

    def post(self, request):
        m = re.fullmatch(r"(\d{4})-(\d{2})", str(request.data.get("month") or ""))
        if not m or not 1 <= int(m.group(2)) <= 12:
            return _error("Pilih bulan payroll.")
        try:
            run = create_run(request.hr_org, int(m.group(1)), int(m.group(2)), request.user)
        except PayrollError as err:
            return _error(str(err))
        return Response({"success": True, "run": _run_summary(run)}, status=status.HTTP_201_CREATED)


class RunDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        columns, rows = _register(run)
        return Response({"success": True, "run": _run_summary(run), "columns": columns, "rows": rows})

    def delete(self, request, pk):
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        if run.is_locked:
            return _error(LOCKED)
        record_audit(organization=run.organization, actor=request.user, action="payroll.delete", target=run,
                     summary=f"{run.name} (draft) dihapus")
        run.delete()
        return Response({"success": True})


class RunRecalculateView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        try:
            calculate_run(run)
        except PayrollError as err:
            return _error(str(err))
        columns, rows = _register(run)
        return Response({"success": True, "run": _run_summary(run), "columns": columns, "rows": rows})


class RunLockView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        action, note = request.data.get("action"), (request.data.get("note") or "").strip()
        try:
            if action == "lock":
                lock_run(run, request.user, note)
            elif action == "reopen":
                reopen_run(run, request.user, note)
            else:
                return _error("Aksi tidak dikenal.")
        except PayrollError as err:
            return _error(str(err))
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        return Response({"success": True, "run": _run_summary(run)})


# ── one employee ──

def _line_payload(line):
    return {
        "id": str(line.id),
        "employee": {"id": str(line.employee.id), "employee_no": line.employee.employee_no,
                     "full_name": line.employee.full_name, "pay_type": line.employee.pay_type,
                     "pay_type_label": line.employee.get_pay_type_display(),
                     "base_rate": str(line.employee.base_rate), "bpjs_tk_enrolled": line.employee.bpjs_tk_enrolled},
        "auto": line.auto, "override": line.override, "note": line.note,
        "override_fields": OVERRIDE_FIELDS,
        "items": [{"id": str(i.id), "kind": i.kind, "code": i.code, "label": i.label, "amount": str(i.amount),
                   "quantity": str(i.quantity) if i.quantity is not None else None, "unit": i.unit,
                   "recurring": i.recurring, "note": i.note} for i in line.items.all()],
        "result": line.result, "gross": _money(line.gross), "deductions": _money(line.deductions),
        "net": _money(line.net), "employer_cost": _money(line.employer_cost),
        "loan_balance": _money(line.loan_balance) if line.loan_balance is not None else None,
    }


def _line(request, pk, line_id):
    run = get_object_or_404(_runs(request.hr_org), pk=pk)
    line = get_object_or_404(run.lines.select_related("employee", "employee__default_shift"), pk=line_id)
    return run, line


class LineSerializer(serializers.Serializer):
    override = serializers.DictField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)
    loan_balance = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True,
                                            min_value=Decimal("0"))

    def validate_override(self, value):
        clean = {}
        for key, raw in value.items():
            if key not in OVERRIDE_FIELDS:
                raise serializers.ValidationError(f"{key} tidak bisa diubah.")
            if raw in (None, ""):
                continue                                   # empty = back to the number from attendance
            try:
                number = Decimal(str(raw))
            except Exception:
                raise serializers.ValidationError({key: "Harus angka."})
            if number < 0 or number > 1000 or (number * 2) % 1:
                raise serializers.ValidationError({key: "Angka 0 sampai 1000, kelipatan 0,5."})
            clean[key] = str(number.normalize()) if number % 1 else str(int(number))
        return clean


class LineDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk, line_id):
        _, line = _line(request, pk, line_id)
        return Response({"success": True, "line": _line_payload(line)})

    def patch(self, request, pk, line_id):
        run, line = _line(request, pk, line_id)
        if run.is_locked:
            return _error(LOCKED)
        ser = LineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        before = {"override": line.override, "note": line.note}
        cfg = PayrollSettings.for_org(run.organization)
        if "override" in ser.validated_data:
            fix = ser.validated_data["override"]
            if ("overtime_hours" in fix or "rest_days_worked" in fix) and cfg.overtime_mode != PayrollSettings.OvertimeMode.FLAT:
                return _error("Jam lembur hanya bisa diubah langsung untuk tarif tetap. Untuk PP 35, ubah di Perlu Tinjau.")
            line.override = fix
        if "note" in ser.validated_data:
            line.note = ser.validated_data["note"]
        if "loan_balance" in ser.validated_data:
            line.loan_balance = ser.validated_data["loan_balance"]
        calculate_line(line, cfg)
        line.save()
        record_audit(organization=run.organization, actor=request.user, action="payroll.line", target=line,
                     summary=f"{run.name} · {line.employee.full_name}: angka dikoreksi",
                     before=before, after={"override": line.override, "note": line.note}, note=line.note)
        return Response({"success": True, "line": _line_payload(line)})


class ItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PayRunItem.Kind.choices)
    label = serializers.CharField(max_length=80)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("1"))
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    unit = serializers.CharField(max_length=15, required=False, allow_blank=True, default="")
    recurring = serializers.BooleanField(required=False, default=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


def _code(label):
    return (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "item")[:40]


class LineItemsView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk, line_id):
        run, line = _line(request, pk, line_id)
        if run.is_locked:
            return _error(LOCKED)
        ser = ItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        item = PayRunItem.objects.create(organization=run.organization, line=line, code=_code(d["label"]), **d)
        calculate_line(line, PayrollSettings.for_org(run.organization))
        line.save()
        word = "penghasilan" if item.kind == PayRunItem.Kind.EARNING else "potongan"
        record_audit(organization=run.organization, actor=request.user, action="payroll.item_add", target=line,
                     summary=f"{run.name} · {line.employee.full_name}: {word} {item.label} Rp {item.amount:,.0f}",
                     after={"label": item.label, "amount": str(item.amount), "kind": item.kind}, note=item.note)
        return Response({"success": True, "line": _line_payload(line)}, status=status.HTTP_201_CREATED)


class ItemDeleteView(APIView):
    permission_classes = [IsCompanyHR]

    def delete(self, request, pk, item_id):
        run = get_object_or_404(_runs(request.hr_org), pk=pk)
        if run.is_locked:
            return _error(LOCKED)
        item = get_object_or_404(PayRunItem.objects.select_related("line", "line__employee"), pk=item_id, line__run=run)
        line = item.line
        record_audit(organization=run.organization, actor=request.user, action="payroll.item_delete", target=line,
                     summary=f"{run.name} · {line.employee.full_name}: {item.label} dihapus",
                     before={"label": item.label, "amount": str(item.amount), "kind": item.kind})
        item.delete()
        line = PayRunLine.objects.select_related("employee", "employee__default_shift").get(pk=line.pk)
        calculate_line(line, PayrollSettings.for_org(run.organization))
        line.save()
        return Response({"success": True, "line": _line_payload(line)})
