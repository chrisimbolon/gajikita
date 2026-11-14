# =============================================================================
# === backend/apps/attendance/management/commands/attendance_remove_import.py ===
# =============================================================================
"""
Remove the fingerprint taps of ONE import day from a date range, so the right file can be imported again.

    python manage.py attendance_remove_import --org "KONSTRUCK" --imported 2026-11-06 --from 2026-09-26 --to 2026-10-25
    ... add --yes to really delete (without it: a preview only, nothing changes)

Why (14 Nov 2026): the test company held 923 October taps imported on 6 Nov, before the employees' machine IDs
were right. Some sat on the wrong person (Eko "worked" on days the machine and HR's notes say he was absent),
and the real import of 12 Nov could not replace them.

Removes ONLY machine taps (source "fingerprint") created on that day for work dates in the range. Days, HR's
decisions, notes, leave, events and "tidak wajib absen" are kept. Refuses when a day in a LOCKED payroll is
touched. One audit entry is written. Then: import the machine file again and recalculate the payroll.
"""
from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.audit import record_audit
from apps.organizations.models import Organization

from apps.attendance.models import ClockEvent


def _date(text, name):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise CommandError(f"--{name} harus seperti 2026-10-25")


class Command(BaseCommand):
    help = "Remove one import day's fingerprint taps from a date range (preview unless --yes)."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Company name (part of it)")
        parser.add_argument("--imported", required=True, help="The day the taps were imported, e.g. 2026-11-06")
        parser.add_argument("--from", dest="start", required=True, help="First work date, e.g. 2026-09-26")
        parser.add_argument("--to", dest="end", required=True, help="Last work date, e.g. 2026-10-25")
        parser.add_argument("--yes", action="store_true", help="Really delete (default: preview only)")

    def handle(self, *args, **o):
        orgs = list(Organization.objects.filter(name__icontains=o["org"])[:5])
        if len(orgs) != 1:
            raise CommandError("Pilih satu perusahaan dengan --org (ditemukan: "
                               + (", ".join(x.name for x in orgs) or "tidak ada") + ")")
        org = orgs[0]
        imported, start, end = _date(o["imported"], "imported"), _date(o["start"], "from"), _date(o["end"], "to")
        if end < start:
            raise CommandError("--to tidak boleh sebelum --from")
        taps = ClockEvent.objects.filter(organization=org, source=ClockEvent.Source.FINGERPRINT,
                                         created_at__date=imported, day__date__gte=start, day__date__lte=end)
        total = taps.count()
        w = self.stdout.write
        w(f"{org.name}: tap mesin yang diimport {imported:%d-%m-%Y}, hari kerja {start:%d-%m-%Y} s/d {end:%d-%m-%Y}")
        if total == 0:
            w("Tidak ada tap seperti itu. Tidak ada yang diubah.")
            return
        locked = taps.filter(day__is_locked=True).count()
        if locked:
            raise CommandError(f"{locked} tap ada di hari yang payroll-nya sudah dikunci. Buka kunci payroll dulu.")
        per = Counter(taps.values_list("employee__full_name", flat=True))
        days = taps.values("day_id").distinct().count()
        for name, n in sorted(per.items()):
            w(f"  {name:<30}{n:>5} tap")
        w(f"TOTAL {total} tap di {days} hari-orang, {len(per)} karyawan.")
        if not o["yes"]:
            w(self.style.WARNING("Ini hanya pratinjau: tidak ada yang dihapus. Tambahkan --yes untuk menghapus."))
            return
        with transaction.atomic():
            taps.delete()
            record_audit(organization=org, actor=None, action="attendance.import_removed", target=org,
                         summary=(f"{total} tap mesin (import {imported:%d-%m-%Y}) dihapus dari hari kerja "
                                  f"{start:%d-%m-%Y} s/d {end:%d-%m-%Y}")[:255],
                         after={"taps": total, "days": days, "employees": len(per)})
        w(self.style.SUCCESS(f"Dihapus: {total} tap. Hari, keputusan HR, catatan, cuti dan kejadian tidak diubah."))
        w("Berikutnya: import lagi file mesin periode itu (Absensi), lalu hitung ulang payroll.")
