# =============================================================================
# === backend/apps/payroll/item_grid.py ===
# =============================================================================
"""
G13 part 1 (15 Nov 2026) — manual pay-run items for everyone, in one table.

Why: R1 still had ~85 of 100 lines from items nobody had typed: the BPJS incentive (35k for 23 people), kubikasi
(12 people), loans / kasbon (19 people), other incentives and deductions. One person at a time, through the
slip panel, that is an afternoon for 30 people and a week for 500.

GET  /api/hr/payroll/runs/<id>/items/grid/
     columns (the standard ones + any other item already in the run) and one row per employee: the amount per
     column, "Sisa pinjaman" (shown on the slip) and the net pay.
POST /api/hr/payroll/runs/<id>/items/grid/
     {"cells": [{"line", "code", "amount"}],                  amount "0" or "" removes the item
      "columns": [{"code", "label", "kind", "recurring"}],    new columns, and "tiap bulan" per column
      "loan_balance": [{"line", "value"}]}                    value null = not shown on the slip
     The changed employees are recalculated; one audit line per change. A locked run refuses.
"Tiap bulan" (recurring) is per column: the items are copied into next month's run, like the BPJS incentive.
A cell where an employee already has two items with that code (typed in the slip panel) is read-only here.
The item codes are the ones R1 understands (pinjaman, kubikasi, insentif_bpjs...).
"""
import re
import uuid
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR

from .models import PayrollSettings, PayRunItem, PayRunLine
from .payrun import calculate_line

EARNING, DEDUCTION = PayRunItem.Kind.EARNING, PayRunItem.Kind.DEDUCTION
STANDARD = [
    ("insentif_bpjs_kesehatan", "Insentif BPJS Kesehatan", EARNING),
    ("kubikasi", "Kubikasi / insentif kubikasi", EARNING),
    ("insentif_lainnya", "Insentif / penerimaan lainnya", EARNING),
    ("pinjaman", "Pinjaman / kasbon", DEDUCTION),
    ("potongan_lainnya", "Potongan lainnya", DEDUCTION),
]
MAX_AMOUNT = Decimal("999999999999")
LOCKED = "Payroll ini sudah dikunci. Buka kunci dulu untuk mengubah."


def code_of(label):
    return (re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_") or "item")[:40]


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _amount(raw):
    """"35000" / "35.000" / 35000 -> Decimal, "" / "0" -> 0, anything else -> None."""
    if raw in (None, ""):
        return Decimal("0")
    text = str(raw).strip().replace("Rp", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):          # 35.000 written the Indonesian way
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value < 0 or value > MAX_AMOUNT:
        return None
    return value.quantize(Decimal("0.01"))


def columns_of(run):
    """The standard columns, then every other item code already in this run (earnings first)."""
    items = PayRunItem.objects.filter(line__run=run)
    seen, found = {c for c, _, _ in STANDARD}, {}
    recurring = defaultdict(list)
    for i in items.order_by("created_at"):
        recurring[i.code].append(i.recurring)
        if i.code not in seen and i.code not in found:
            found[i.code] = (i.label, i.kind)
    cols = [(c, l, k, True) for c, l, k in STANDARD] + [(c, l, k, False) for c, (l, k) in found.items()]
    cols.sort(key=lambda c: 0 if c[2] == EARNING else 1)
    return [{"code": c, "label": l, "kind": k, "standard": std,
             "recurring": bool(recurring[c]) and all(recurring[c]), "count": len(recurring[c])}
            for c, l, k, std in cols]


def grid(run):
    cols = columns_of(run)
    lines = list(run.lines.select_related("employee").prefetch_related("items").order_by("employee__full_name"))
    rows = []
    for line in lines:
        cells, multi = {}, []
        by_code = defaultdict(list)
        for i in line.items.all():
            by_code[i.code].append(i)
        for code, items in by_code.items():
            cells[code] = _money(sum((i.amount for i in items), Decimal("0")))
            if len(items) > 1:
                multi.append(code)
        rows.append({"line": str(line.id),
                     "employee": {"id": str(line.employee_id), "employee_no": line.employee.employee_no,
                                  "full_name": line.employee.full_name},
                     "cells": cells, "multi": multi,
                     "loan_balance": _money(line.loan_balance) if line.loan_balance is not None else None,
                     "net": _money(line.net)})
    return {"success": True, "run": {"id": str(run.id), "name": run.name, "locked": run.is_locked},
            "columns": cols, "rows": rows}


class ItemGridView(APIView):
    permission_classes = [IsCompanyHR]

    def _run(self, request, pk):
        from .payrun_views import _runs
        return get_object_or_404(_runs(request.hr_org), pk=pk)

    def get(self, request, pk):
        return Response(grid(self._run(request, pk)))

    def post(self, request, pk):
        run = self._run(request, pk)
        if run.is_locked:
            return Response({"success": False, "message": LOCKED}, status=status.HTTP_400_BAD_REQUEST)
        body = request.data if isinstance(request.data, dict) else {}
        known = {c["code"]: c for c in columns_of(run)}
        errors = []

        # columns: new ones, and "tiap bulan"
        recurring_set = {}
        for c in body.get("columns") or []:
            label = str(c.get("label") or "").strip()[:80]
            kind = c.get("kind")
            code = str(c.get("code") or "").strip() or code_of(label)
            if not re.fullmatch(r"[a-z0-9_]{1,40}", code):
                errors.append(f"Kolom \"{label or code}\": kode tidak valid.")
                continue
            if code not in known:
                if not label or kind not in (EARNING, DEDUCTION):
                    errors.append(f"Kolom baru \"{label or code}\": isi nama dan pilih penghasilan atau potongan.")
                    continue
                known[code] = {"code": code, "label": label, "kind": kind, "standard": False, "recurring": False}
            if "recurring" in c:
                recurring_set[code] = bool(c.get("recurring"))

        lines = {str(l.id): l for l in run.lines.select_related("employee").prefetch_related("items")}
        changes = []                                   # (line, code, Decimal)
        for cell in body.get("cells") or []:
            line, code = lines.get(str(cell.get("line"))), str(cell.get("code") or "")
            if line is None or code not in known:
                errors.append("Ada sel yang tidak dikenal (muat ulang halaman).")
                continue
            amount = _amount(cell.get("amount"))
            if amount is None:
                errors.append(f"{line.employee.full_name} · {known[code]['label']}: jumlah tidak valid.")
                continue
            if sum(1 for i in line.items.all() if i.code == code) > 1:
                errors.append(f"{line.employee.full_name} · {known[code]['label']}: ada lebih dari satu item, ubah di rincian karyawan.")
                continue
            changes.append((line, code, amount))
        balances = []
        for b in body.get("loan_balance") or []:
            line = lines.get(str(b.get("line")))
            if line is None:
                errors.append("Ada sisa pinjaman untuk karyawan yang tidak dikenal (muat ulang halaman).")
                continue
            raw = b.get("value")
            value = None if raw in (None, "") else _amount(raw)
            if raw not in (None, "") and value is None:
                errors.append(f"{line.employee.full_name} · Sisa pinjaman: jumlah tidak valid.")
                continue
            balances.append((line, value))
        if errors:
            return Response({"success": False, "message": errors[0], "errors": errors[:30]},
                            status=status.HTTP_400_BAD_REQUEST)

        batch, audits, touched = uuid.uuid4().hex, [], {}
        word = lambda kind: "penghasilan" if kind == EARNING else "potongan"
        with transaction.atomic():
            for line, code, amount in changes:
                col = known[code]
                item = next((i for i in line.items.all() if i.code == code), None)
                before = str(item.amount) if item else "0"
                if amount == 0 and item is not None and item.loan_id:      # G13 part 2: a loan skips this month
                    if item.amount == 0:
                        continue
                    item.amount = Decimal("0")
                    item.save(update_fields=["amount"])
                    summary = f"{col['label']} ditunda bulan ini"
                elif amount == 0:
                    if item is None:
                        continue
                    item.delete()
                    summary = f"{col['label']} dihapus"
                elif item is None:
                    PayRunItem.objects.create(organization=run.organization, line=line, kind=col["kind"], code=code,
                                              label=col["label"], amount=amount,
                                              recurring=recurring_set.get(code, col.get("recurring", False)))
                    summary = f"{word(col['kind'])} {col['label']} Rp {amount:,.0f}"
                elif item.amount != amount:
                    item.amount = amount
                    item.save(update_fields=["amount"])
                    summary = f"{col['label']} Rp {Decimal(before):,.0f} -> Rp {amount:,.0f}"
                else:
                    continue
                touched[line.id] = line
                audits.append(AuditEntry(organization=run.organization, actor=request.user, action="payroll.item_grid",
                                         target_type=line._meta.label_lower, target_id=str(line.id),
                                         summary=f"{run.name} · {line.employee.full_name}: {summary}"[:255],
                                         data={"batch": batch, "code": code, "before": before, "after": str(amount)}))
            for code, value in recurring_set.items():
                PayRunItem.objects.filter(line__run=run, code=code).exclude(recurring=value).update(recurring=value)
            for line, value in balances:
                if line.loan_balance == value:
                    continue
                before = None if line.loan_balance is None else str(line.loan_balance)
                line.loan_balance = value
                line.save(update_fields=["loan_balance"])
                touched[line.id] = line
                audits.append(AuditEntry(organization=run.organization, actor=request.user, action="payroll.item_grid",
                                         target_type=line._meta.label_lower, target_id=str(line.id),
                                         summary=f"{run.name} · {line.employee.full_name}: sisa pinjaman "
                                                 f"{'-' if value is None else f'Rp {value:,.0f}'}"[:255],
                                         data={"batch": batch, "loan_balance": True, "before": before,
                                               "after": None if value is None else str(value)}))
            cfg = PayrollSettings.for_org(run.organization)
            for line in touched.values():
                fresh = PayRunLine.objects.select_related("employee", "employee__default_shift").get(pk=line.pk)
                calculate_line(fresh, cfg)
                fresh.save()
            AuditEntry.objects.bulk_create(audits, batch_size=500)
        out = grid(run)
        out.update({"changed": len(audits), "recalculated": len(touched)})
        return Response(out)
