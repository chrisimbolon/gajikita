# =============================================================================
# === backend/apps/payroll/management/commands/payroll_demo.py ===
# =============================================================================
"""
python manage.py payroll_demo

Runs the payroll engine on PT DKCB's real October 2026 register (names replaced by
codes) and prints each person's gross, deductions and net next to the register's
net, then the totals and the compliance warnings. Reads and writes no database.
"""
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.payroll.demo_dkcb import OCT_2026, dkcb_slip


def rp(value):
    return f"{value:,.0f}".replace(",", ".")


class Command(BaseCommand):
    help = "Rebuild PT DKCB's October 2026 payroll with the GajiKita engine (no database)."

    def handle(self, *args, **options):
        out = self.stdout.write
        out("PT DKCB  periode 26 Sep - 25 Okt 2026  (29 karyawan, nama diganti kode)\n")
        out(f"{'Kode':<5}{'Bruto':>13}{'Potongan':>13}{'Bersih':>13}{'Register':>13}  Cocok")
        totals, warnings, matched, visible = [Decimal(0)] * 3, Counter(), 0, 0
        for row in OCT_2026:
            slip, register = dkcb_slip(row), row[-1]
            ok = ""
            if register is not None:
                visible += 1
                ok = "ya" if slip.net == register else "TIDAK"
                matched += slip.net == register
            out(f"{row[0]:<5}{rp(slip.gross):>13}{rp(slip.total_deductions):>13}{rp(slip.net):>13}"
                f"{rp(register) if register is not None else '-':>13}  {ok}")
            totals = [totals[0] + slip.gross, totals[1] + slip.total_deductions, totals[2] + slip.net]
            for w in slip.warnings:
                warnings["Di bawah UMK" if "UMK" in w else w] += 1
        out(f"{'Total':<5}{rp(totals[0]):>13}{rp(totals[1]):>13}{rp(totals[2]):>13}")
        out(f"\nBersih cocok dengan register: {matched} dari {visible} yang terlihat di file.")
        out("\nPeringatan:")
        for text, n in warnings.most_common():
            out(f"  {n:>2} x {text}")
