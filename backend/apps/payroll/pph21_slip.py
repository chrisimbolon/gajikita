# =============================================================================
# === backend/apps/payroll/pph21_slip.py ===
# =============================================================================
"""
G16-3 (22 Nov 2026) — PPh 21 on the slip, behind Pengaturan payroll -> PPh 21 -> "Hitung PPh 21 di slip"
(default off). Only draft payrolls change, and only when HR clicks "Hitung ulang"; locked payrolls never move.

  Normal month  : PPh 21 = bruto x TER (pph21.monthly_for_slip, Pak Holan's rules).
  Masa Desember : the year settles (Pasal 17): saldo awal + the other SeeGaji months + this month, minus what was
  or last month   withheld -> "PPh 21 (hitung setahun)", or "Pengembalian kelebihan PPh 21" when too much was taken.
  of a leaver     If the saldo awal is missing for someone who worked before SeeGaji, TER is used and the slip says why.
  Tax paid by the company: "Tunjangan PPh 21" (earning) = "PPh 21" (deduction): take-home pay is unchanged.
  A manual PPh item on the slip wins: SeeGaji adds nothing and says so (no double tax).
"""
from decimal import Decimal

from . import pph21 as P
from . import pph21_year as Y
from .engine import SlipLine

ZERO = Decimal("0")
ALLOWANCE, DEDUCTION, REFUND = "pph21_allowance", "pph21", "pph21_refund"


def _rp(v):
    return f"{Decimal(v):,.0f}".replace(",", ".")


def slip_dict(slip):
    j = lambda lines: [{"code": l.code, "label": l.label, "amount": str(l.amount)} for l in lines]
    return {"earnings": j(slip.earnings), "deductions": j(slip.deductions), "employer": j(slip.employer)}


def manual_pph(slip):
    """Deductions HR added by hand that are already a tax (an item coded pph21, or called PPh / pajak)."""
    return [d for d in slip.deductions
            if d.code != "pph21_final"                                     # G16-4: the final tax on hak akhir
            and (d.code == DEDUCTION or any(w in f"{d.code} {d.label}".lower() for w in ("pph", "pajak")))]


def _retotal(slip):
    slip.gross = sum((l.amount for l in slip.earnings), ZERO)
    slip.total_deductions = sum((l.amount for l in slip.deductions), ZERO)
    slip.net = slip.gross - slip.total_deductions


def _tax_lines(slip, by_company, tax, label):
    if tax <= 0:
        return
    if by_company:
        slip.earnings.append(SlipLine(ALLOWANCE, "Tunjangan PPh 21", tax))
    slip.deductions.append(SlipLine(DEDUCTION, label, tax))


def employee_year(employee, year, cfg, exclude_run):
    """Saldo awal + the employee's other SeeGaji months in that tax year (not exclude_run) -> Y.YearRow."""
    from .models import Pph21Opening
    runs, _ = Y.year_runs(exclude_run.organization, year, cfg.pph21_tax_month)
    agg = Y.YearRow(employee)
    o = Pph21Opening.objects.filter(employee=employee, year=year).first()
    if o is not None:
        agg.opening = o
        agg.months, agg.bruto, agg.iuran, agg.withheld = o.months, o.bruto, o.iuran, o.pph
    for run in runs:
        if run.pk == exclude_run.pk:
            continue
        line = run.lines.filter(employee=employee).first()
        if line is None or not line.result:
            continue
        m = P.monthly_for_slip(line.result, employee.ptkp_status, by_company=employee.pph21_by_company,
                               late_reduces=cfg.pph21_late_reduces_bruto,
                               company_jht_in_bruto=cfg.pph21_company_jht_in_bruto, on=run.pay_date or run.period_end)
        agg.months += 1
        agg.bruto += m.bruto
        agg.iuran += Y.iuran_from_slip(line.result, company_jht_in_bruto=cfg.pph21_company_jht_in_bruto)
        taken = Y.withheld_from_slip(line.result)
        agg.withheld += m.tax if taken is None else taken
    first = min([r.period_start for r in runs] + [exclude_run.period_start])
    agg.incomplete = o is None and bool(employee.join_date) and employee.join_date < first
    return agg


def _settle(slip, employee, res, agg, kw, year):
    ptkp, by_company = employee.ptkp_status, employee.pph21_by_company
    plain = P.monthly_for_slip(res, ptkp, by_company=False, **kw)
    months = min(agg.months + 1, 12)
    bruto = agg.bruto + plain.bruto
    iuran = agg.iuran + Y.iuran_from_slip(res, company_jht_in_bruto=kw["company_jht_in_bruto"])
    if by_company:
        a, t = Y.annual_gross_up(bruto, months, iuran, ptkp, agg.withheld, kw["on"])
        _tax_lines(slip, True, t, "PPh 21 (hitung setahun)")
    else:
        a = P.annual_pph(bruto, months, iuran, ptkp, agg.withheld, kw["on"])
        if a.due > 0:
            slip.deductions.append(SlipLine(DEDUCTION, "PPh 21 (hitung setahun)", a.due))
        elif a.due < 0:
            slip.earnings.append(SlipLine(REFUND, "Pengembalian kelebihan PPh 21", -a.due))
    rest = "kurang dipotong" if a.due > 0 else ("lebih dipotong, dikembalikan" if a.due < 0 else "pas")
    if by_company and a.due < 0:
        rest = "lebih dibayar perusahaan (bukan hak karyawan)"
    slip.notes.append(f"PPh 21 setahun {year}: {months} bulan, pajak Rp {_rp(a.tax_year)}, sudah dipotong "
                      f"Rp {_rp(a.paid)}, {rest} Rp {_rp(abs(a.due))}.")


def add_pph21(slip, line, cfg):
    """Called by payrun.calculate_line when PPh 21 is switched on. Changes the slip in place."""
    e, run = line.employee, line.run
    manual = manual_pph(slip)
    if manual:
        slip.warnings.append(f"Ada potongan manual \"{manual[0].label}\": PPh 21 otomatis tidak dihitung "
                             f"(supaya tidak dobel). Hapus item itu bila PPh 21 dihitung SeeGaji.")
        return
    res = slip_dict(slip)
    year, month = Y.tax_month(run.period_end, run.pay_date, cfg.pph21_tax_month)
    leaving = bool(e.end_date) and run.period_start <= e.end_date <= run.period_end
    kw = dict(late_reduces=cfg.pph21_late_reduces_bruto, company_jht_in_bruto=cfg.pph21_company_jht_in_bruto,
              on=run.pay_date or run.period_end)
    try:
        if month == 12 or leaving:
            agg = employee_year(e, year, cfg, run)
            if not agg.incomplete:
                _settle(slip, e, res, agg, kw, year)
                _retotal(slip)
                return
            slip.warnings.append(f"PPh 21 setahun {year} belum dihitung: saldo awal PPh 21 belum diisi "
                                 f"(Payroll → Pengaturan → Saldo awal PPh 21). Sementara dipotong TER bulanan.")
        m = P.monthly_for_slip(res, e.ptkp_status, by_company=e.pph21_by_company, **kw)
        _tax_lines(slip, e.pph21_by_company, m.tax, "PPh 21")
    except ValueError as err:
        slip.warnings.append(f"PPh 21 tidak dihitung: {err}")
    _retotal(slip)


def readiness(organization, today):
    """What Pengaturan payroll shows next to the switch."""
    from apps.employees.models import Employee
    from .models import PayrollSettings, Pph21Opening
    cfg = PayrollSettings.for_org(organization)
    year = today.year
    runs, december = Y.year_runs(organization, year, cfg.pph21_tax_month)
    first = runs[0].period_start if runs else None
    have = set(Pph21Opening.objects.filter(organization=organization, year=year).values_list("employee_id", flat=True))
    active = Employee.objects.filter(organization=organization, status=Employee.Status.ACTIVE)
    missing = sum(1 for e in active if first and e.join_date and e.join_date < first and e.pk not in have)
    return {"year": year, "missing_opening": missing, "ptkp_unchecked": active.filter(ptkp_checked=False).count(),
            "december_run": december.name if december else None}
