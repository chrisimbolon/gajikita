# =============================================================================
# === backend/apps/payroll/loan_views.py ===
# =============================================================================
"""
G13 part 2 (15 Nov 2026) — Payroll → Pinjaman.

GET   /api/hr/payroll/loans/?show=active|all   -> loans, total_remaining, open_run (the oldest draft payroll: the
      form's default "Mulai dipotong"), runs (month, name, locked: the form says which payroll deducts first)
POST  /api/hr/payroll/loans/       {employee, amount, installment, start_month "YYYY-MM", note, original_amount?}
      original_amount (G17-9, optional, for reading only): the loan's full amount / what a kasbon asked for.
      amount = what is STILL owed when recorded (Iqbal: 2.200.000 after September). installment = amount
      -> a kasbon, deducted in full in one month. A typed "Pinjaman" item already in that month's draft run is
      taken over (linked) instead of deducting twice.
PATCH /api/hr/payroll/loans/<id>/  {installment?, note?, original_amount?, amount?, start_month?}  (G17-11: amount
      and start_month with guards, see _edit) | {run, this_month} (this month's amount, 0 = skip)
      | {action: "cancel"}
Every change re-syncs the employee's draft runs (oldest first) and recalculates them; locked runs never change.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from . import loans as L
from .models import EmployeeLoan, PayrollSettings, PayRun, PayRunItem
from .payrun import MONTHS, calculate_line

ZERO = Decimal("0")


def _err(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "message": message}, status=code)


def _money(v):
    return str(Decimal(v).quantize(Decimal("0.01")))


def _amount(raw):
    try:
        v = Decimal(str(raw).replace(".", "").replace(",", ".").strip()) if isinstance(raw, str) else Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return None
    return v.quantize(Decimal("0.01")) if ZERO < v <= Decimal("999999999999") else None


def _month(raw):
    try:
        y, m = (int(x) for x in str(raw).split("-")[:2])
        return date(y, m, 1)
    except (ValueError, TypeError):
        return None


def month_label(d):
    return f"{MONTHS[d.month - 1]} {d.year}"


def resync(org, employee):
    """Every draft run of this employee, oldest first: loan items, then the slip."""
    cfg = PayrollSettings.for_org(org)
    for run in PayRun.objects.filter(organization=org, status=PayRun.Status.DRAFT).order_by("period_start"):
        line = run.lines.select_related("employee", "employee__default_shift").filter(employee=employee).first()
        if line is None:
            continue
        L.sync_line(line, run)
        calculate_line(line, cfg)
        line.save()


def describe(loan):
    reps = list(PayRunItem.objects.filter(loan=loan).select_related("line__run").order_by("line__run__period_start"))
    paid = sum((i.amount for i in reps if i.line.run.is_locked), ZERO)
    planned = sum((i.amount for i in reps if not i.line.run.is_locked), ZERO)
    remaining = max(ZERO, loan.amount - paid - planned)
    if loan.status == EmployeeLoan.Status.CANCELLED:
        state, label = "cancelled", "Dibatalkan"
    elif loan.amount - paid <= 0:
        state, label = "paid", "Lunas"
    else:
        state, label = "active", "Berjalan"
    plan = ""                                       # G17-9: what is still to come, in words
    if state == "active":
        taken = [L.pay_month(i.line.run) for i in reps]
        rest = max(ZERO, loan.amount - paid - planned)
        if rest > 0:
            first = max(L.add_months(max(taken), 1), loan.start_month) if taken else loan.start_month
            plan = ("Berikutnya " if taken else "") + L.plan_text(rest, loan.installment, first)
        else:
            end = max((L.pay_month(i.line.run) for i in reps if i.amount > 0), default=None)
            plan = f"Lunas {L.month_text(end)}" if end else ""
    draft = next((i for i in reps if not i.line.run.is_locked), None)
    return {
        "id": str(loan.id),
        "employee": {"id": str(loan.employee_id), "employee_no": loan.employee.employee_no,
                     "full_name": loan.employee.full_name},
        "amount": _money(loan.amount), "installment": _money(loan.installment), "kasbon": loan.is_kasbon,
        "start_month": loan.start_month.strftime("%Y-%m"), "start_label": month_label(loan.start_month),
        "note": loan.note, "state": state, "state_label": label, "plan": plan,
        "original_amount": _money(loan.original_amount) if loan.original_amount is not None else None,
        "paid": _money(paid), "planned": _money(planned), "remaining": _money(remaining),
        "this_month": ({"run": str(draft.line.run_id), "run_name": draft.line.run.name, "amount": _money(draft.amount)}
                       if draft else None),
        "history": [{"run": i.line.run.name, "amount": _money(i.amount), "locked": i.line.run.is_locked} for i in reps],
    }


class LoanListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        qs = (EmployeeLoan.objects.filter(organization=request.hr_org).select_related("employee")
              .order_by("employee__full_name", "start_month"))
        rows = [describe(l) for l in qs]
        if request.query_params.get("show") != "all":
            rows = [r for r in rows if r["state"] == "active"]
        runs = list(PayRun.objects.filter(organization=request.hr_org).order_by("-period_start")[:24])
        draft = min((r for r in runs if not r.is_locked), key=lambda r: r.period_start, default=None)
        return Response({"success": True, "loans": rows,
                         "total_remaining": _money(sum((Decimal(r["remaining"]) for r in rows), ZERO)),
                         "open_run": ({"run": str(draft.id), "name": draft.name,
                                       "month": L.pay_month(draft).strftime("%Y-%m")} if draft else None),
                         "runs": [{"month": L.pay_month(r).strftime("%Y-%m"), "name": r.name, "locked": r.is_locked}
                                  for r in runs]})

    def post(self, request):
        org, d = request.hr_org, request.data
        emp = Employee.objects.filter(organization=org, pk=d.get("employee")).first() if d.get("employee") else None
        amount, installment, start = _amount(d.get("amount")), _amount(d.get("installment")), _month(d.get("start_month"))
        note = str(d.get("note") or "").strip()[:120]
        raw_original = d.get("original_amount")
        original = None if raw_original in (None, "") else _amount(raw_original)
        if emp is None:
            return _err("Pilih karyawan.")
        if amount is None:
            return _err("Isi jumlah pinjaman yang masih harus dibayar (lebih dari 0).")
        if installment is None:
            return _err("Isi potongan per bulan (lebih dari 0).")
        if installment > amount:
            installment = amount
        if raw_original not in (None, "") and original is None:
            return _err("Jumlah awal / pengajuan tidak valid.")
        if original is not None and original < amount:
            return _err("Jumlah awal / pengajuan tidak boleh lebih kecil dari jumlah yang akan dipotong.")
        if start is None:
            return _err("Pilih bulan mulai dipotong.")
        locked = PayRun.objects.filter(organization=org, status=PayRun.Status.LOCKED,
                                       period_end__year=start.year, period_end__month=start.month).first()
        if locked:
            return _err(f"{locked.name} sudah dikunci. Mulai potong bulan berikutnya.")
        with transaction.atomic():
            loan = EmployeeLoan.objects.create(organization=org, employee=emp, amount=amount, installment=installment,
                                               start_month=start, note=note, created_by=request.user,
                                               original_amount=original)
            adopted = False
            run = PayRun.objects.filter(organization=org, status=PayRun.Status.DRAFT,
                                        period_end__year=start.year, period_end__month=start.month).first()
            if run:
                typed = list(PayRunItem.objects.filter(line__run=run, line__employee=emp, code=L.CODE, loan__isnull=True))
                if len(typed) == 1:                     # the deduction HR already typed this month becomes the loan's
                    item = typed[0]
                    item.loan, item.amount = loan, min(item.amount, amount)
                    item.save(update_fields=["loan", "amount"])
                    adopted = True
            resync(org, emp)
            kind = "kasbon" if loan.is_kasbon else f"cicilan {installment:,.0f}/bulan"
            record_audit(organization=org, actor=request.user, action="payroll.loan_create", target=emp,
                         summary=f"{emp.full_name}: pinjaman Rp {amount:,.0f}, {kind}, mulai {month_label(start)}"
                                 + (f" (awal Rp {original:,.0f})" if original is not None and original != amount else "")
                                 + (" (potongan yang sudah diketik dipakai)" if adopted else ""),
                         after={"loan": str(loan.id), "amount": str(amount), "installment": str(installment),
                                "start": start.isoformat(), "note": note, "adopted": adopted,
                                "original": str(original) if original is not None else None})
        return Response({"success": True, "loan": describe(loan), "adopted": adopted}, status=status.HTTP_201_CREATED)


def _edit(org, loan, d):
    """
    G17-11: change a running loan. -> (problem, summary); problem = a message for HR, nothing saved.
    Everything is checked before anything is written. This month's draft deduction follows the new per-month
    amount only where it still equals the old one (an amount HR typed for this month, e.g. 0 = tunda, is kept).
    """
    if loan.status == EmployeeLoan.Status.CANCELLED:
        return "Pinjaman ini sudah dihentikan, tidak bisa diubah.", ""
    locked_items = PayRunItem.objects.filter(loan=loan, line__run__status=PayRun.Status.LOCKED)
    locked_paid = locked_items.aggregate(s=Sum("amount"))["s"] or ZERO
    was_kasbon, old_installment = loan.is_kasbon, loan.installment
    amount, start, installment = loan.amount, loan.start_month, loan.installment
    original, note = loan.original_amount, loan.note
    changes = []

    if "amount" in d:
        amount = _amount(d.get("amount"))
        if amount is None:
            return "Isi sisa yang harus dibayar (lebih dari 0).", ""
        if amount < locked_paid:
            return (f"Tidak bisa lebih kecil dari yang sudah dipotong di payroll yang dikunci "
                    f"(Rp {locked_paid:,.0f}).".replace(",", "."), "")
        if amount != loan.amount:
            changes.append(f"sisa Rp {loan.amount:,.0f} -> Rp {amount:,.0f}")
    if "start_month" in d:
        start = _month(d.get("start_month"))
        if start is None:
            return "Pilih bulan mulai dipotong.", ""
        if start != loan.start_month:
            if locked_items.exists():
                return "Sudah ada potongan di payroll yang dikunci, jadi bulan mulai tidak bisa diubah.", ""
            locked = PayRun.objects.filter(organization=org, status=PayRun.Status.LOCKED,
                                           period_end__year=start.year, period_end__month=start.month).first()
            if locked:
                return f"{locked.name} sudah dikunci. Pilih bulan berikutnya.", ""
            changes.append(f"mulai {month_label(loan.start_month)} -> {month_label(start)}")
    if "installment" in d and not was_kasbon:
        installment = _amount(d.get("installment"))
        if installment is None:
            return "Isi potongan per bulan (lebih dari 0).", ""
    installment = amount if was_kasbon else min(installment, amount)      # a kasbon stays whole
    if installment != old_installment:
        changes.append(f"potongan Rp {old_installment:,.0f} -> Rp {installment:,.0f}/bulan")
    if "original_amount" in d:                                            # G17-9: "" clears it
        raw = d.get("original_amount")
        original = None if raw in (None, "") else _amount(raw)
        if raw not in (None, "") and original is None:
            return "Jumlah awal / pengajuan tidak valid.", ""
        if original != loan.original_amount:
            changes.append("jumlah awal " + (f"Rp {original:,.0f}" if original is not None else "dihapus"))
    if original is not None and original < amount:
        return "Jumlah awal / pengajuan tidak boleh lebih kecil dari sisa yang harus dibayar.", ""
    if "note" in d:
        note = str(d.get("note") or "").strip()[:120]
        if note != loan.note:
            changes.append(f"catatan: {note or '-'}")

    loan.amount, loan.start_month, loan.installment = amount, start, installment
    loan.original_amount, loan.note = original, note
    loan.save(update_fields=["amount", "start_month", "installment", "original_amount", "note"])
    if installment != old_installment:                    # drafts that still take the old amount follow
        (PayRunItem.objects.filter(loan=loan, amount=old_installment)
         .exclude(line__run__status=PayRun.Status.LOCKED).update(amount=installment))
    return None, "; ".join(changes) or "tidak ada perubahan"


class LoanDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def patch(self, request, pk):
        org = request.hr_org
        loan = get_object_or_404(EmployeeLoan.objects.select_related("employee"), organization=org, pk=pk)
        d = request.data
        before = {"installment": str(loan.installment), "note": loan.note, "status": loan.status,         # G17-11
                  "amount": str(loan.amount), "start_month": loan.start_month.isoformat(),
                  "original_amount": str(loan.original_amount) if loan.original_amount is not None else None}
        with transaction.atomic():
            if d.get("action") == "cancel":
                if PayRunItem.objects.filter(loan=loan, line__run__status=PayRun.Status.LOCKED).exists():
                    summary = "pinjaman dihentikan (potongan yang sudah dikunci tetap)"
                else:
                    summary = "pinjaman dibatalkan"
                loan.status = EmployeeLoan.Status.CANCELLED
                loan.save(update_fields=["status"])
            elif "this_month" in d:
                run = PayRun.objects.filter(organization=org, pk=d.get("run")).first()
                if run is None or run.is_locked:
                    return _err("Payroll itu tidak ada atau sudah dikunci.")
                item = PayRunItem.objects.filter(loan=loan, line__run=run).first()
                if item is None:
                    return _err("Pinjaman ini tidak dipotong di payroll itu.")
                raw = d.get("this_month")
                value = ZERO if raw in ("", None, 0, "0") else _amount(raw)
                if value is None:
                    return _err("Jumlah tidak valid.")
                owed = L.balance_before(loan, run)
                if value > owed:
                    return _err(f"Lebih besar dari sisa pinjaman (Rp {owed:,.0f}).")
                item.amount = value
                item.save(update_fields=["amount"])
                summary = f"potongan {run.name}: Rp {value:,.0f}" + (" (ditunda bulan ini)" if not value else "")
            else:
                problem, summary = _edit(org, loan, d)                                       # G17-11
                if problem:
                    return _err(problem)
            resync(org, loan.employee)
            record_audit(organization=org, actor=request.user, action="payroll.loan_update", target=loan.employee,
                         summary=f"{loan.employee.full_name}: {summary}"[:255], before=before,
                         after={"installment": str(loan.installment), "note": loan.note, "status": loan.status,
                                "loan": str(loan.id), "amount": str(loan.amount),
                                "start_month": loan.start_month.isoformat(),
                                "original_amount": str(loan.original_amount) if loan.original_amount is not None else None})
        loan.refresh_from_db()
        return Response({"success": True, "loan": describe(loan)})
