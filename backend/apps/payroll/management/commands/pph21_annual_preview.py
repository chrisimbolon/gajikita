# =============================================================================
# === backend/apps/payroll/management/commands/pph21_annual_preview.py ===
# =============================================================================
"""
G16-2 (21 Nov 2026): what the year's PPh 21 (Pasal 17) WOULD be per person: saldo awal + SeeGaji pay runs in that
tax year, minus what was withheld. Read-only: nothing is saved and no slip changes.

    python manage.py pph21_annual_preview --year 2026 --org "KONSTRUCK"
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.payroll import pph21_year as Y


def rp(v):
    return f"{Decimal(v):,.0f}".replace(",", ".")


class Command(BaseCommand):
    help = "G16-2: the year's PPh 21 per person (Pasal 17), from saldo awal + SeeGaji pay runs (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--org", default="", help="Company name (part of it)")

    def handle(self, *args, **o):
        qs = Organization.objects.all()
        if o["org"]:
            qs = qs.filter(name__icontains=o["org"])
        orgs = list(qs[:5])
        if len(orgs) != 1:
            raise CommandError(f"Pilih satu perusahaan dengan --org (ditemukan: {', '.join(x.name for x in orgs) or 'tidak ada'})")
        org, year = orgs[0], o["year"]
        rows, runs, december, cfg = Y.year_rows(org, year)
        w = self.stdout.write
        mode = Y.MODE_LABELS.get(cfg.pph21_tax_month, cfg.pph21_tax_month)                  # G16-5a
        w(f"{org.name} · PPh 21 setahun {year} (Pasal 17) · hanya pratinjau, tidak ada yang disimpan")
        w(f"Masa pajak ikut {mode}. Payroll SeeGaji di tahun ini: "
          + (", ".join(f"{r.name} (masa {Y.masa_text(*Y.run_masa(r, cfg)[:2])})"
                       for r in runs) or "belum ada"))
        w(f"Payroll masa Desember: {december.name if december else 'belum ada (hasil di bawah = sampai bulan terakhir)'}\n")
        w(f"{'Nama':<26}{'PTKP':>6}{'Bln':>4}{'Bruto':>14}{'Iuran':>11}{'PKP':>13}{'Pajak':>11}{'Dipotong':>11}"
          f"{'Sisa':>11}  Catatan")
        due = refund = Decimal("0")
        incomplete = 0                                                              # G16-2.1
        for r in rows:
            e, a = r.employee, r.annual
            if a is None:
                incomplete += 1 if r.incomplete else 0                              # G16-5b: an overlap
                w(f"{e.full_name[:25]:<26}  " + " · ".join(r.notes))
                continue
            notes = list(r.notes)
            if r.allowance:
                notes.append(f"tunjangan PPh {rp(r.allowance)}")
            if r.incomplete:                                                        # G16-2.1: not in the totals
                incomplete += 1
            elif a.due > 0:
                due += a.due
            else:
                refund += -a.due
            w(f"{e.full_name[:25]:<26}{e.ptkp_status:>6}{r.months:>4}{rp(a.bruto):>14}{rp(a.iuran):>11}{rp(a.pkp):>13}"
              f"{rp(a.tax_year):>11}{rp(a.paid):>11}{rp(a.due):>11}  " + " · ".join(notes))
        w(f"\nKurang potong (dipotong di payroll masa Desember): Rp {rp(due)}")
        w(f"Lebih potong (dikembalikan ke karyawan): Rp {rp(refund)}")
        if incomplete:
            w(f"Belum lengkap, tidak dijumlah: {incomplete} orang. Isi Payroll -> Pengaturan -> Saldo awal PPh 21 dulu.")
        w("Belum dipakai di slip. Sisa minus = kelebihan, dikembalikan paling lambat akhir bulan berikutnya.")
