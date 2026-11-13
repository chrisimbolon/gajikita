# =============================================================================
# === backend/apps/payroll/management/commands/r1_compare.py ===
# =============================================================================
"""
R1 (12 Nov 2026): SeeGaji's pay run next to the company's own payroll book, person by person.

    python manage.py r1_compare --book "path/10. Oct 2026 Rekapan Gaji DKCB.xlsx" --period 2026-10
        [--org "DKCB"] [--sheet "Data Gaji (Real)"] [--out report.xlsx]

Reads only. Writes one Excel file (default: next to the book, "R1 <period> SeeGaji vs buku.xlsx"):
  Ringkasan   one row per person: net in SeeGaji, net in the book, difference, status
  Selisih     one row per differing component, with a first-guess cause and an empty
              "Keputusan" column (SeeGaji bug / salah buku / aturan belum ada / data)
  Nama        people found on only one side
The report holds real salaries: keep it out of git (next to the book, not in the repo).
"""
import os
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.payroll import r1_compare as r1
from apps.payroll.models import PayRun


def rp(value):
    return f"{Decimal(value):,.0f}".replace(",", ".")


class Command(BaseCommand):
    help = "R1: compare a SeeGaji pay run with the company's payroll book (Excel), person by person."

    def add_arguments(self, parser):
        parser.add_argument("--book", required=True, help="The payroll book (.xlsx)")
        parser.add_argument("--period", required=True, help="Pay month, e.g. 2026-10 (the period that ends in it)")
        parser.add_argument("--org", default="", help="Company name (part of it); needed when there are several")
        parser.add_argument("--sheet", default="", help="Sheet name; default: the first sheet that looks like a register")
        parser.add_argument("--out", default="", help="Report path (.xlsx)")

    def handle(self, *args, **o):
        import openpyxl

        org = self._org(o["org"])
        try:
            year, month = (int(x) for x in o["period"].split("-"))
        except ValueError:
            raise CommandError("--period harus seperti 2026-10")
        run = (PayRun.objects.filter(organization=org, period_end__year=year, period_end__month=month)
               .order_by("-period_start").first())
        if run is None:
            raise CommandError(f"Belum ada pay run {o['period']} untuk {org.name}. Buat dulu di menu Payroll.")

        if not os.path.exists(o["book"]):
            raise CommandError(f"File buku tidak ditemukan: {o['book']}")
        wb = openpyxl.load_workbook(o["book"], data_only=True, read_only=True)
        book, sheet = self._read(wb, o["sheet"])
        wb.close()
        lines = list(run.lines.select_related("employee").order_by("employee__full_name"))
        emp_names = [l.employee.full_name for l in lines]
        pairs, book_only, sg_only = r1.match_names([b.name for b in book], emp_names)

        summary, diffs = [], []
        for i, b in enumerate(book):
            if i not in pairs:
                continue
            line = lines[pairs[i]]
            sg = r1.seegaji_amounts(line.result, line.net)
            ds = r1.compare(b.amounts, sg)
            qty = self._quantities(line.result)
            summary.append((b.no, b.name, line.employee.full_name, line.employee.employee_no, sg["net"],
                            b.amounts.get("net", r1.ZERO), sg["net"] - b.amounts.get("net", r1.ZERO), r1.status(ds),
                            len([d for d in ds if d.key != "net"]), line.warning_count))
            for d in ds:
                diffs.append((b.name, line.employee.employee_no, d.label, qty.get(d.key, ""), d.seegaji, d.book,
                              d.delta, d.hint, ""))

        out = o["out"] or os.path.join(os.path.dirname(os.path.abspath(o["book"])),
                                       f"R1 {o['period']} SeeGaji vs buku.xlsx")
        self._write(out, run, sheet, summary, diffs,
                    [book[i] for i in book_only], [lines[j] for j in sg_only])
        self._print(run, sheet, summary, diffs, [book[i] for i in book_only], [lines[j] for j in sg_only], out)

    # ── input ──
    def _org(self, name):
        qs = Organization.objects.all()
        if name:
            qs = qs.filter(name__icontains=name)
        orgs = list(qs[:5])
        if len(orgs) != 1:
            names = ", ".join(x.name for x in orgs) or "tidak ada"
            raise CommandError(f"Pilih satu perusahaan dengan --org (ditemukan: {names})")
        return orgs[0]

    def _read(self, wb, wanted):
        names = [wanted] if wanted else wb.sheetnames
        for name in names:
            if name not in wb.sheetnames:
                raise CommandError(f"Sheet '{name}' tidak ada. Ada: {', '.join(wb.sheetnames)}")
            rows = list(wb[name].iter_rows(values_only=True))
            book = r1.read_book(rows)
            if book:
                return book, name
        raise CommandError("Tidak menemukan sheet register (baris judul dengan Nama, PENGHASILAN, PENGURANGAN, PENERIMAAN).")

    def _quantities(self, result):
        """component -> '14.5 jam' style note from SeeGaji's own lines, to explain a difference."""
        out = {}
        for kind, known in (("earnings", r1.EARN_CODES), ("deductions", r1.DEDUCT_CODES)):
            for line in (result or {}).get(kind, []):
                key = known.get(line.get("code", ""))
                if key and line.get("quantity") not in (None, "", "0", "0.00"):
                    q = r1.to_dec(line["quantity"]).normalize()
                    out[key] = f"{q:f} {line.get('unit', '')}".strip()
        return out

    # ── output ──
    def _write(self, path, run, sheet, summary, diffs, book_only, sg_only):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = Workbook()
        bold = Font(bold=True)
        head_fill = PatternFill("solid", fgColor="013D5A")
        head_font = Font(bold=True, color="FFFFFF")

        def table(ws, title, header, rows, money_cols, widths):
            ws.append([title])
            ws["A1"].font = Font(bold=True, size=13)
            ws.append([f"{run.name}  ·  {run.period_start:%d %b %Y} – {run.period_end:%d %b %Y}  ·  buku: sheet '{sheet}'"])
            ws.append([])
            ws.append(header)
            for c in ws[4]:
                c.fill, c.font = head_fill, head_font
                c.alignment = Alignment(wrap_text=True, vertical="center")
            for r in rows:
                ws.append([float(v) if isinstance(v, Decimal) else v for v in r])
            for row in ws.iter_rows(min_row=5):
                for c in row:
                    if c.column in money_cols and isinstance(c.value, (int, float)):
                        c.number_format = "#,##0;[Red]-#,##0"
            for i, w in enumerate(widths, 1):
                ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = w
            ws.freeze_panes = "A5"

        ws = wb.active
        ws.title = "Ringkasan"
        table(ws, "R1 — SeeGaji vs buku gaji", ["No buku", "Nama di buku", "Nama di SeeGaji", "No. Karyawan",
              "Diterima SeeGaji", "Diterima buku", "Selisih", "Status", "Jumlah komponen beda", "Peringatan slip"],
              summary, {5, 6, 7}, [8, 26, 26, 12, 16, 16, 14, 34, 12, 10])
        total = [sum(r[i] for r in summary) if summary else 0 for i in (4, 5, 6)]
        ws.append([])
        ws.append(["", "TOTAL", "", "", *[float(t) for t in total]])
        for c in ws[ws.max_row]:
            c.font = bold
            if c.column in (5, 6, 7):
                c.number_format = "#,##0;[Red]-#,##0"

        table(wb.create_sheet("Selisih"), "Selisih per komponen", ["Nama", "No. Karyawan", "Komponen",
              "Jumlah di SeeGaji", "SeeGaji (Rp)", "Buku (Rp)", "Selisih (Rp)", "Dugaan penyebab",
              "Keputusan (bug SeeGaji / salah buku / aturan belum ada / data)"],
              diffs, {5, 6, 7}, [26, 12, 30, 14, 15, 15, 14, 52, 40])

        names = [("Hanya di buku", b.name, b.section, float(b.amounts.get("net", 0))) for b in book_only]
        names += [("Hanya di SeeGaji", l.employee.full_name, l.employee.employee_no, float(l.net)) for l in sg_only]
        table(wb.create_sheet("Nama"), "Orang yang hanya ada di satu sisi",
              ["Di mana", "Nama", "Bagian / No.", "Diterima (Rp)"], names, {4}, [18, 30, 26, 16])
        wb.save(path)

    def _print(self, run, sheet, summary, diffs, book_only, sg_only, out):
        w = self.stdout.write
        w(f"{run.name} ({run.period_start} – {run.period_end})  vs  buku sheet '{sheet}'\n")
        w(f"{'Nama':<28}{'SeeGaji':>14}{'Buku':>14}{'Selisih':>13}  Status")
        for r in summary:
            w(f"{r[1][:27]:<28}{rp(r[4]):>14}{rp(r[5]):>14}{rp(r[6]):>13}  {r[7]}")
        ok = sum(1 for r in summary if r[7] == "cocok")
        w(f"\n{len(summary)} orang dibandingkan: {ok} cocok, {len(summary) - ok} beda · {len(diffs)} baris selisih")
        if book_only:
            w("Hanya di buku: " + ", ".join(b.name for b in book_only))
        if sg_only:
            w("Hanya di SeeGaji: " + ", ".join(l.employee.full_name for l in sg_only))
        w(self.style.SUCCESS(f"\nLaporan: {out}"))
        w("Isinya gaji asli: simpan di luar repo, jangan di-commit.")
