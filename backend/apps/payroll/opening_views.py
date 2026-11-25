# =============================================================================
# === backend/apps/payroll/opening_views.py ===
# =============================================================================
"""
G16-2 (21 Nov 2026) — "Saldo awal PPh 21": bruto, months, PPh 21 withheld and the employee's JHT/JP for the tax
months before the company's first SeeGaji payroll (from the old book or Coretax), per employee per year.

  GET   payroll/pph21-opening/?year=2026     everyone who worked that year, their saldo awal, the SeeGaji masa
  PATCH payroll/pph21-opening/               one row (all zero = remove it)
  POST  payroll/pph21-opening/import/        CSV, commit=0 checks only, commit=1 saves (only when no row has an error)
Every save goes to the audit log.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from . import pph21_year as Y
from .models import PayRun, PayrollSettings, Pph21Opening

MAX_FILE = 2 * 1024 * 1024


def _money(v):
    return str(Decimal(v or 0).quantize(Decimal("1")))


def _year(request):
    raw = request.query_params.get("year") or request.data.get("year") or ""
    try:
        y = int(raw)
    except (TypeError, ValueError):
        y = timezone.localdate().year
    return y if 2020 <= y <= 2100 else timezone.localdate().year


def _employees(org, year):
    first, last = date(year, 1, 1), date(year, 12, 31)
    return (Employee.objects.filter(organization=org, join_date__lte=last)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=first)).order_by("full_name"))


def _row(e, o):
    return {"employee": {"id": str(e.pk), "employee_no": e.employee_no, "full_name": e.full_name, "status": e.status},
            "months": o.months if o else 0, "bruto": _money(o.bruto if o else 0), "pph": _money(o.pph if o else 0),
            "iuran": _money(o.iuran if o else 0), "note": o.note if o else "", "saved": o is not None}


def payload(org, year):
    cfg = PayrollSettings.for_org(org)
    runs, december = Y.year_runs(org, year, cfg)                                    # G16-5a
    rule_list = Y.rules(cfg)
    openings = {o.employee_id: o for o in Pph21Opening.objects.filter(organization=org, year=year)}
    rows = [_row(e, openings.get(e.pk)) for e in _employees(org, year)]
    saved = [r for r in rows if r["saved"]]
    return {
        "success": True, "year": year, "tax_month": cfg.pph21_tax_month,
        "tax_month_label": Y.MODE_LABELS.get(cfg.pph21_tax_month, cfg.pph21_tax_month),
        "runs": [{"name": r.name, "masa": Y.masa_text(*Y.run_masa(r, cfg, rule_list)[:2]),
                  "frozen": Y.run_masa(r, cfg, rule_list)[2]} for r in runs],
        "masa_warnings": Y.masa_checks(list(PayRun.objects.filter(organization=org)), cfg, rule_list),  # G16-5a
        "december_run": december.name if december else None,
        "rows": rows,
        "totals": {"people": len(saved), "bruto": _money(sum((Decimal(r["bruto"]) for r in saved), Decimal("0"))),
                   "pph": _money(sum((Decimal(r["pph"]) for r in saved), Decimal("0")))},
    }


class OpeningInput(serializers.Serializer):
    employee_id = serializers.UUIDField()
    year = serializers.IntegerField(min_value=2020, max_value=2100)
    months = serializers.IntegerField(min_value=0, max_value=12)
    bruto = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0"))
    pph = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0"))
    iuran = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0"), required=False,
                                     default=Decimal("0"))
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


def _save(org, employee, year, months, bruto, pph, iuran, note, source):
    """Upsert one saldo awal; all zero removes it. -> (before, after) for the audit log."""
    o = Pph21Opening.objects.filter(organization=org, employee=employee, year=year).first()
    before = None if o is None else {"months": o.months, "bruto": _money(o.bruto), "pph": _money(o.pph),
                                     "iuran": _money(o.iuran)}
    if not months and not bruto and not pph and not iuran:
        if o is not None:
            o.delete()
        return before, None
    if o is None:
        o = Pph21Opening(organization=org, employee=employee, year=year)
    o.months, o.bruto, o.pph, o.iuran, o.note, o.source = months, bruto, pph, iuran, note or "", source
    o.save()
    return before, {"months": months, "bruto": _money(bruto), "pph": _money(pph), "iuran": _money(iuran)}


class OpeningListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(payload(request.hr_org, _year(request)))

    def patch(self, request):
        org = request.hr_org
        ser = OpeningInput(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        employee = Employee.objects.filter(organization=org, pk=d["employee_id"]).first()
        if employee is None:
            return Response({"success": False, "message": "Karyawan tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            before, after = _save(org, employee, d["year"], d["months"], d["bruto"], d["pph"], d["iuran"], d["note"],
                                  Pph21Opening.Source.MANUAL)
            if before != after:
                record_audit(organization=org, actor=request.user, action="payroll.pph21_opening", target=employee,
                             summary=f"Saldo awal PPh 21 {d['year']} {employee.full_name}: "
                                     + ("dihapus" if after is None else f"{d['months']} bulan, PPh {_money(d['pph'])}"),
                             before=before, after=after)
        return Response(payload(org, d["year"]))


class OpeningImportView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        org, year = request.hr_org, _year(request)
        f = request.FILES.get("file")
        if f is None:
            return Response({"success": False, "message": "Pilih file CSV."}, status=status.HTTP_400_BAD_REQUEST)
        if f.size > MAX_FILE:
            return Response({"success": False, "message": "File terlalu besar (maks. 2 MB)."},
                            status=status.HTTP_400_BAD_REQUEST)
        rows, problems = Y.parse_opening_csv(Y.decode(f.read()))
        if problems:
            return Response({"success": False, "message": problems[0]}, status=status.HTTP_400_BAD_REQUEST)
        people = {e.employee_no.strip().upper(): e for e in Employee.objects.filter(organization=org)}
        seen = set()
        for r in rows:
            e = people.get(r["employee_no"].strip().upper())
            if e is None and r["employee_no"]:
                r["errors"].append("no_karyawan tidak ditemukan")
            if e is not None:
                if e.pk in seen:
                    r["errors"].append("karyawan ini muncul dua kali")
                seen.add(e.pk)
                r["full_name"] = e.full_name
            r["_employee"] = e
        bad = sum(1 for r in rows if r["errors"])
        commit = str(request.data.get("commit") or "0") in ("1", "true", "yes")
        if commit and not bad and rows:
            with transaction.atomic():
                for r in rows:
                    _save(org, r["_employee"], year, r["months"], r["bruto"], r["pph"], r["iuran"],
                          "dari file CSV", Pph21Opening.Source.CSV)
                record_audit(organization=org, actor=request.user, action="payroll.pph21_opening", target=org,
                             summary=f"Saldo awal PPh 21 {year} diimpor dari CSV: {len(rows)} karyawan",
                             after={"file": f.name, "rows": len(rows)})
        preview = [{"line": r["line"], "employee_no": r["employee_no"], "full_name": r.get("full_name") or r["name"],
                    "months": r["months"], "bruto": _money(r["bruto"]), "pph": _money(r["pph"]),
                    "iuran": _money(r["iuran"]), "errors": r["errors"]} for r in rows]
        return Response({
            "success": True, "year": year, "saved": bool(commit and not bad and rows), "rows": preview, "errors": bad,
            "totals": {"people": len(rows), "bruto": _money(sum((r["bruto"] for r in rows), Decimal("0"))),
                       "pph": _money(sum((r["pph"] for r in rows), Decimal("0")))},
        })
