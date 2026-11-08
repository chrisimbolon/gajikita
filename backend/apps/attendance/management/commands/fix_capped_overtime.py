"""
fix_capped_overtime (G12g, 8 Nov 2026)

Before G12g, "Setujui" in Tinjau massal cut overtime to 240 minutes per working day unless HR changed
the field. This command finds the days that cut, and gives them back their full overtime.

  python manage.py fix_capped_overtime --month 2026-10                      # show only, changes nothing
  python manage.py fix_capped_overtime --month 2026-10 --employee DK08      # one person
  python manage.py fix_capped_overtime --month 2026-10 --apply              # give the hours back

  --month    the pay period by its last month (2026-10 = 26 Sep - 25 Okt with a 26-25 period)
  --org      the company's ID or (part of) its name; needed when there is more than one company

Only days whose last decision was a bulk approval are touched: a day HR approved by hand with typed
minutes, reset, or rejected is left alone. Locked days (in a locked payroll) are listed, never changed.
Each change gets its own audit line ("Sistem"). Safe to repeat: a second run finds only locked days.
Afterwards: "Hitung ulang" on the draft payroll of that period.
"""
import re
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.attendance.review_bulk import _period, capped_bulk_days, uncap
from apps.organizations.models import Organization


def pick_org(text):
    orgs = Organization.objects.order_by("name")
    if text:
        try:
            orgs = orgs.filter(id=uuid.UUID(text))
        except ValueError:
            orgs = orgs.filter(name__icontains=text)
    found = list(orgs[:21])
    if len(found) == 1:
        return found[0]
    if not found:
        raise CommandError(f"Perusahaan '{text}' tidak ditemukan.")
    raise CommandError("Pilih satu perusahaan dengan --org (ID atau nama):\n" +
                       "\n".join(f"  {o.id}  {o.name}" for o in found[:20]))


class Command(BaseCommand):
    help = "G12g: lembur yang terpotong batas 240 menit saat Setujui massal — tampilkan, lalu kembalikan dengan --apply."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True, help="Periode gaji, mis. 2026-10")
        parser.add_argument("--org", default="", help="ID atau nama perusahaan")
        parser.add_argument("--employee", default="", help="No. karyawan, mis. DK08")
        parser.add_argument("--apply", action="store_true", help="Kembalikan lemburnya (tanpa ini: hanya tampilkan)")

    def handle(self, *args, **opts):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", opts["month"]):
            raise CommandError("Tulis --month seperti 2026-10.")
        org = pick_org(opts["org"].strip())
        info, start, end = _period(org, opts["month"])
        rows = capped_bulk_days(org, start, end, timezone.now(), opts["employee"].strip())
        out = self.stdout
        out.write(f"{org.name} · periode {info['label']} ({start:%d-%m-%Y} s/d {end:%d-%m-%Y})"
                  + (f" · karyawan {opts['employee']}" if opts["employee"] else ""))
        if not rows:
            out.write("Tidak ada lembur yang terpotong oleh Setujui massal. Tidak ada yang perlu diubah.")
            return
        for day, proposed in rows:
            old = day.overtime_approved_minutes or 0
            out.write(f"  {day.date:%d-%m-%Y}  {day.employee.employee_no:<10} {day.employee.full_name:<28} "
                      f"{old:>4} -> {proposed:>4} menit" + ("   TERKUNCI, dilewati" if day.is_locked else ""))
        extra = sum(p - (d.overtime_approved_minutes or 0) for d, p in rows if not d.is_locked)
        if not opts["apply"]:
            out.write(f"{len(rows)} hari, +{extra} menit. Belum ada yang diubah: jalankan lagi dengan --apply.")
            return
        done, locked = uncap(org, rows)
        out.write(self.style.SUCCESS(f"Selesai: {len(done)} hari dikembalikan (+{extra} menit)"
                                     + (f", {len(locked)} hari terkunci dilewati" if locked else "") + "."))
        out.write("Langkah berikutnya: Payroll → buka run periode ini → Hitung ulang.")
