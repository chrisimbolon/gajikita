# =============================================================================
# === backend/apps/payroll/management/commands/pph21_preview.py ===
# =============================================================================
"""
G16-0 (19 Nov 2026): what PPh 21 SeeGaji WOULD take from each slip of a pay run. Read-only: nothing is saved
and no slip changes. Compare with the payroll book before G16-1 switches it on.

    python manage.py pph21_preview --period 2026-10 --org "KONSTRUCK" [--potong-telat] [--jht-perusahaan-bruto]

--potong-telat           late fines reduce bruto, like unpaid leave (open question for Pak Holan)
--jht-perusahaan-bruto   the employee's JHT 2% paid by the company counts as bruto (open question)
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.payroll import pph21 as P
from apps.payroll.models import PayRun


def rp(v):
    return f"{Decimal(v):,.0f}".replace(",", ".")


class Command(BaseCommand):
    help = "G16-0: PPh 21 per slip of a pay run, as SeeGaji would calculate it (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--period", required=True, help="Pay month, e.g. 2026-10")
        parser.add_argument("--org", default="", help="Company name (part of it)")
        parser.add_argument("--potong-telat", action="store_true", help="Late fines reduce bruto")
        parser.add_argument("--jht-perusahaan-bruto", action="store_true",
                            help="Company-paid employee JHT 2%% counts as bruto")

    def handle(self, *args, **o):
        qs = Organization.objects.all()
        if o["org"]:
            qs = qs.filter(name__icontains=o["org"])
        orgs = list(qs[:5])
        if len(orgs) != 1:
            raise CommandError(f"Pilih satu perusahaan dengan --org (ditemukan: {', '.join(x.name for x in orgs) or 'tidak ada'})")
        org = orgs[0]
        try:
            y, m = (int(x) for x in o["period"].split("-"))
        except ValueError:
            raise CommandError("--period harus seperti 2026-10")
        run = PayRun.objects.filter(organization=org, period_end__year=y, period_end__month=m).first()
        if run is None:
            raise CommandError(f"Belum ada pay run {o['period']} untuk {org.name}.")
        pay_date = date(y, m, 1)
        w = self.stdout.write
        w(f"{run.name} · PPh 21 bulanan (TER) · hanya pratinjau, tidak ada yang disimpan\n")
        w(f"{'Nama':<28}{'PTKP':>6}{'TER':>4}{'Bruto':>14}{'Tarif':>7}{'PPh 21':>11}  Catatan")
        total, flags = Decimal("0"), {"default": 0, "npwp": 0}
        for line in run.lines.select_related("employee").order_by("employee__full_name"):
            e = line.employee
            b = P.bruto_from_slip(line.result, late_reduces=o["potong_telat"],
                                  company_jht_in_bruto=o["jht_perusahaan_bruto"])
            try:
                rate, tax = P.monthly_pph(b.total, e.ptkp_status, pay_date)
                cat = P.ter_category(e.ptkp_status)
            except ValueError as err:
                w(f"{e.full_name[:27]:<28}  {err}")
                continue
            notes = []
            if e.ptkp_status == "TK/0":
                notes.append("PTKP TK/0 (bawaan?) cek")
                flags["default"] += 1
            if not (e.npwp or "").strip():
                notes.append("tanpa NPWP")
                flags["npwp"] += 1
            if e.pph21_by_company:
                g_rate, g_tax = P.gross_up(b.total, e.ptkp_status, pay_date)
                notes.append(f"ditanggung perusahaan; gross-up {rp(g_tax)} ({g_rate * 100:.2f}%)")
            if len(b.parts) > 1:
                notes.append(" + ".join(f"{label} {rp(a)}" for label, a in b.parts[1:]))
            total += tax
            w(f"{e.full_name[:27]:<28}{e.ptkp_status:>6}{cat:>4}{rp(b.total):>14}{float(rate) * 100:>6.2f}%{rp(tax):>11}  "
              + " · ".join(notes))
        w(f"\nTotal PPh 21: Rp {rp(total)}")
        w(f"PTKP masih TK/0: {flags['default']} orang (cek status K/TK di buku gaji). Tanpa NPWP: {flags['npwp']} orang.")
        w("Belum dipakai di slip (G16-1 setelah jawaban Pak Holan). Upah BPJS mengikuti gaji pokok, belum upah lapor BPJS.")
