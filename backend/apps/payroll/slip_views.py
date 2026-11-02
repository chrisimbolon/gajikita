# =============================================================================
# === backend/apps/payroll/slip_views.py ===
# =============================================================================
"""
Pay slips and the bank transfer list (G8b part 2, 1 Nov 2026).

  GET runs/<id>/slips/?line=<line id>   everything a printed slip shows, for one employee or the
                                        whole run: company, period, earnings, deductions, net,
                                        Sisa Pinjaman, Sisa Cuti. Draft runs are marked "draft".
  GET runs/<id>/transfers/              one row per employee to pay: bank, account, amount,
                                        and what's missing. Locked runs only: money follows a
                                        locked payroll, never a draft.
"""
from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.leave.services import annual_balance
from apps.organizations.permissions import IsCompanyHR

from .models import PayrollSettings, PayRun

MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]


def long_date(d):
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}" if d else ""


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _run(request, pk):
    return get_object_or_404(PayRun.objects.filter(organization=request.hr_org).select_related("organization"), pk=pk)


class SlipsView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        run = _run(request, pk)
        cfg = PayrollSettings.for_org(run.organization)
        lines = run.lines.select_related("employee").order_by("employee__full_name")
        if request.query_params.get("line"):
            lines = lines.filter(pk=request.query_params["line"])
        slips = []
        for line in lines:
            emp = line.employee
            leave = annual_balance(emp, run.period_end)
            result = line.result or {}
            slips.append({
                "line_id": str(line.id),
                "employee": {"employee_no": emp.employee_no, "full_name": emp.full_name, "position": emp.position},
                "earnings": result.get("earnings", []),
                "deductions": result.get("deductions", []),
                "gross": _money(line.gross), "deductions_total": _money(line.deductions), "net": _money(line.net),
                "loan_balance": _money(line.loan_balance) if line.loan_balance is not None else None,
                "leave_left": leave["left"] if leave["entitled"] else None,
            })
        org = run.organization
        return Response({
            "success": True,
            "company": {"name": org.name, "address": cfg.slip_address or org.address, "phone": org.phone},
            "run": {"id": str(run.id), "name": run.name, "status": run.status, "draft": not run.is_locked,
                    "period": f"{long_date(run.period_start)} - {long_date(run.period_end)}",
                    "pay_date": long_date(run.pay_date)},
            "place": cfg.slip_place, "signer": cfg.slip_signer or "HRD",
            "slips": slips,
        })


class TransfersView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        run = _run(request, pk)
        if not run.is_locked:
            return Response({"success": False, "message": "Kunci payroll dulu sebelum membuat file transfer bank."},
                            status=status.HTTP_400_BAD_REQUEST)
        rows, total, problems = [], Decimal("0"), 0
        for line in run.lines.select_related("employee").order_by("employee__full_name"):
            emp = line.employee
            problem = ""
            if line.net <= 0:
                problem = "Gaji bersih nol atau minus"
            elif not emp.bank_account_no.strip():
                problem = "No. rekening kosong"
            elif not emp.bank_name.strip():
                problem = "Nama bank kosong"
            if problem:
                problems += 1
            else:
                total += line.net
            rows.append({
                "employee_no": emp.employee_no, "full_name": emp.full_name, "bank_name": emp.bank_name,
                "account_no": emp.bank_account_no, "account_name": emp.bank_account_name or emp.full_name,
                "amount": _money(line.net), "problem": problem,
            })
        return Response({"success": True, "run": {"id": str(run.id), "name": run.name,
                                                  "pay_date": run.pay_date.isoformat() if run.pay_date else None},
                         "rows": rows, "total": _money(total), "ready": len(rows) - problems, "problems": problems})
