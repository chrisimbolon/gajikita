# =============================================================================
# === backend/apps/payroll/loans.py ===
# =============================================================================
"""
G13 part 2 (15 Nov 2026) — loans that pay themselves off.

DKCB keeps two sheets: "Pinjaman bulanan" (kasbon, deducted in full from this month's pay) and "Data Angsuran"
(a loan paid in instalments: Iqbal 2.500.000 = 300.000 x 8 + 100.000; Feny 3.000.000 x 1.000.000 ...). HR typed
every deduction by hand each month and kept the balance in Excel.

An EmployeeLoan is entered once: what is still owed when it is recorded, the instalment per month and the first
pay month. Every draft pay run from that month on gets one "Pinjaman" item per loan (the same code R1 reads),
min(instalment, what is still owed). HR may change this month's amount (Item manual, or the loan page): 0 =
skip this month; the next month the normal instalment comes back. When the balance reaches 0 the loan stops by
itself. A locked run is never touched. The slip's "Sisa pinjaman" is filled from the loans.

sync_line(line)       before every calculation of a draft line (calculate_run)
balance_before(loan, run) / repayments
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum

ZERO = Decimal("0")
CODE, LABEL = "pinjaman", "Pinjaman / kasbon"


def pay_month(run):
    return date(run.period_end.year, run.period_end.month, 1)


def label_for(loan):
    if loan.is_kasbon:
        return "Kasbon" + (f" ({loan.note})" if loan.note else "")
    return "Cicilan pinjaman" + (f" ({loan.note})" if loan.note else "")


_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
           "November", "Desember"]


def add_months(d, n):
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def month_text(d):
    return f"{_MONTHS[d.month - 1]} {d.year}"


def rp(v):
    return "Rp " + f"{int(v):,}".replace(",", ".")


def schedule(total, installment, first_month):
    """G17-9. 2.500.000 at 300.000 from September 2026 -> (8, 100000, 1 May 2027): 8 full deductions, then one of
    100.000, the last in May 2027. -> (0, 0, None) when there is nothing to pay."""
    total, installment = Decimal(total), Decimal(installment)
    if total <= 0 or installment <= 0:
        return 0, ZERO, None
    installment = min(installment, total)
    full = int(total // installment)
    last = total - installment * full
    return full, last, add_months(first_month, full + (1 if last > 0 else 0) - 1)


def plan_text(total, installment, first_month):
    """"8× Rp 300.000 + 1× Rp 100.000, lunas Mei 2027". The loan page's form does the same sums."""
    full, last, end = schedule(total, installment, first_month)
    if end is None:
        return ""
    inst = min(Decimal(installment), Decimal(total))
    return f"{full}× {rp(inst)}" + (f" + 1× {rp(last)}" if last > 0 else "") + f", lunas {month_text(end)}"


def paid_before(loan, run):
    """What earlier pay runs (locked or not) already took for this loan."""
    from .models import PayRunItem
    return (PayRunItem.objects.filter(loan=loan, line__run__period_start__lt=run.period_start)
            .aggregate(s=Sum("amount"))["s"] or ZERO)


def balance_before(loan, run):
    return max(ZERO, loan.amount - paid_before(loan, run))


def sync_line(line, run=None):
    """Make the line's loan items match the employee's active loans. Draft runs only. -> True if anything changed."""
    from .models import EmployeeLoan, PayRunItem
    run = run or line.run
    if run.is_locked:
        return False
    month, changed = pay_month(run), False
    items = {i.loan_id: i for i in PayRunItem.objects.filter(line=line, loan__isnull=False)}
    loans = list(EmployeeLoan.objects.filter(employee_id=line.employee_id, start_month__lte=month))
    remaining_after = ZERO
    has_loan = False
    for loan in loans:
        item = items.pop(loan.id, None)
        before = balance_before(loan, run)
        if loan.status != EmployeeLoan.Status.ACTIVE or before <= 0:
            if item is not None:                       # cancelled, or already paid off by earlier runs
                item.delete()
                changed = True
            continue
        has_loan = True
        if item is None:
            PayRunItem.objects.create(organization=line.organization, line=line, kind=PayRunItem.Kind.DEDUCTION,
                                      code=CODE, label=label_for(loan), amount=min(loan.installment, before), loan=loan)
            amount, changed = min(loan.installment, before), True
        else:
            amount = item.amount
            if amount > before:                        # never take more than is owed
                item.amount, amount, changed = before, before, True
                item.save(update_fields=["amount"])
            if item.label != label_for(loan):
                item.label = label_for(loan)
                item.save(update_fields=["label"])
        remaining_after += before - amount
    for item in items.values():                        # loans that start later now, or were deleted
        item.delete()
        changed = True
    if has_loan:
        value = remaining_after.quantize(Decimal("0.01"))
        if line.loan_balance != value:
            line.loan_balance = value
            line.save(update_fields=["loan_balance"])
            changed = True
    return changed
