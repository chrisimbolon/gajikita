# =============================================================================
# === backend/apps/payroll/management/commands/pph21_preview.py ===
# =============================================================================
"""
G16-0 (19 Nov 2026): what PPh 21 SeeGaji WOULD take from each slip of a pay run. Read-only: nothing is saved
and no slip changes. Compare with the payroll book before G16-1 switches it on.

    python manage.py pph21_preview --period 2026-10 --org "KONSTRUCK"

G16-1 (20 Nov 2026): the rules come from Pengaturan payroll -> PPh 21 (late fines, company-paid JHT) and Pak Holan's
answers (JP 1% paid by the company is bruto; tax paid by the company is grossed up).
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.payroll import pph21 as P
from apps.payroll.models import PayRun, PayrollSettings


def rp(v):
    return f"{Decimal(v):,.0f}".replace(",", ".")


class Command(BaseCommand):
    help = "G16-0: PPh 21 per slip of a pay run, as SeeGaji would calculate it (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--period", required=True, help="Pay month, e.g. 2026-10")
        parser.add_argument("--org", default="", help="Company name (part of it)")
        pass  # G16-1: the PPh 21 rules come from Pengaturan payroll (no more --potong-telat flags)

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
        cfg = PayrollSettings.for_org(org)
        late, jht = cfg.pph21_late_reduces_bruto, cfg.pph21_company_jht_in_bruto
        yes = lambda b: "ya" if b else "tidak"
        w(f"{run.name} · PPh 21 bulanan (TER) · hanya pratinjau, tidak ada yang disimpan")
        w(f"Aturan: potong telat: {yes(late)} · JHT 2% ditanggung perusahaan masuk bruto: {yes(jht)} · "
          f"JP 1% ditanggung perusahaan masuk bruto: ya · PPh ditanggung perusahaan: gross-up\n")
        w(f"{'Nama':<28}{'PTKP':>6}{'TER':>4}{'Bruto':>14}{'Tarif':>7}{'PPh 21':>11}  Catatan")
        total, flags = Decimal("0"), {"default": 0, "npwp": 0}
        for line in run.lines.select_related("employee").order_by("employee__full_name"):
            e = line.employee
            try:
                m = P.monthly_for_slip(line.result, e.ptkp_status, by_company=e.pph21_by_company, late_reduces=late,
                                       company_jht_in_bruto=jht, company_jp_in_bruto=cfg.pph21_company_jp_in_bruto,
                                       on=pay_date)
                rate, tax = m.rate, m.tax
                cat = P.ter_category(e.ptkp_status)
            except ValueError as err:
                w(f"{e.full_name[:27]:<28}  {err}")
                continue
            notes = []
            if e.ptkp_status == "TK/0" and not e.ptkp_checked:                  # G16-2: ticked = checked
                notes.append("PTKP TK/0 (bawaan?) cek")
                flags["default"] += 1
            if not (e.npwp or "").strip():
                notes.append("tanpa NPWP")
                flags["npwp"] += 1
            if m.gross_up:
                notes.append("ditanggung perusahaan, gross-up")
            if len(m.parts) > 1:
                notes.append(" + ".join(f"{label} {rp(a)}" for label, a in m.parts[1:]))
            total += tax
            w(f"{e.full_name[:27]:<28}{e.ptkp_status:>6}{cat:>4}{rp(m.bruto):>14}{float(rate) * 100:>6.2f}%{rp(tax):>11}  "
              + " · ".join(notes))
        w(f"\nTotal PPh 21: Rp {rp(total)}")
        w(f"PTKP TK/0 belum dicek: {flags['default']} orang (centang \"Status PTKP sudah dicek\" di Karyawan). "
          f"Tanpa NPWP: {flags['npwp']} orang (NIK cukup).")
        w("Belum dipakai di slip. JKK/JKM dari upah yang dilaporkan ke BPJS (Karyawan), bila diisi. "
          "Masa pajak menunggu jawaban Pak Holan (B1).")
