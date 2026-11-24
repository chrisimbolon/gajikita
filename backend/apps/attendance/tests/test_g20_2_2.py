"""
G20-2.2 (24 Nov 2026) — a lone night tap after a working day with no taps is that day's clock-out.
Shaped like DKCB's power cut of 12-14 Okt (made-up person "P-12", machine ID 32): no taps on 14 Okt,
overtime until 02:00; the machine wrote the 02:00 tap on 15 Okt, then 12:43 -> 21:00.
"""
from datetime import date, datetime, time
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from apps.attendance.fingerprint import make_sessions
from apps.attendance.fingerprint_import import tap_id
from apps.attendance.models import AttendanceDay, ClockEvent
from apps.attendance.tests import test_fingerprint_import as base


def dt(text):
    return datetime.fromisoformat(text)


TAPS = [dt("2026-10-13 07:56"), dt("2026-10-13 17:02"),
        dt("2026-10-15 02:00"), dt("2026-10-15 12:43"), dt("2026-10-15 21:00")]


class NightOutRuleTests(SimpleTestCase):
    def test_the_night_tap_closes_the_quiet_day_before(self):
        s = make_sessions(TAPS, time(8), "123456")
        self.assertEqual([(x.work_date, x.clock_in.strftime("%H:%M"), x.out_only) for x in s],
                         [(date(2026, 10, 13), "07:56", False), (date(2026, 10, 14), "02:00", True),
                          (date(2026, 10, 15), "12:43", False)])
        self.assertEqual(s[2].clock_out, dt("2026-10-15 21:00"))

    def test_not_after_a_day_off_a_day_with_taps_or_outside_the_file(self):
        sunday = make_sessions([dt("2026-10-17 08:00"), dt("2026-10-17 17:00"), dt("2026-10-19 02:00")], time(8), "123456")
        self.assertFalse(any(x.out_only for x in sunday))                        # 18 Okt is a Sunday
        open_day = make_sessions([dt("2026-10-14 07:56"), dt("2026-10-15 02:00")], time(8), "123456")
        self.assertEqual([(x.work_date, x.clock_out) for x in open_day], [(date(2026, 10, 14), dt("2026-10-15 02:00"))])
        first_day = make_sessions([dt("2026-10-15 02:00"), dt("2026-10-15 12:43"), dt("2026-10-15 21:00")], time(8), "123456")
        self.assertFalse(any(x.out_only for x in first_day))                     # 14 Okt is not in this file


class NightOutImportTests(base.FingerprintImportTests):
    FILE = (b"    32\t2026-10-13 07:56:00\t1\t0\t1\t0\n"
            b"    32\t2026-10-13 17:02:00\t1\t1\t1\t0\n"
            b"    32\t2026-10-15 02:00:00\t1\t0\t1\t0\n"
            b"    32\t2026-10-15 12:43:00\t1\t0\t1\t0\n"
            b"    32\t2026-10-15 21:00:00\t1\t1\t1\t0\n")

    def test_stored_as_the_clock_out_of_14_okt(self):
        self.assertEqual(self.post("1", self.FILE).data["applied"], {"events": 5, "days": 3})
        d14 = AttendanceDay.objects.get(employee=self.sudar, date=date(2026, 10, 14))
        self.assertEqual([(e.kind, e.occurred_at.astimezone(base.WIB).strftime("%d %H:%M")) for e in d14.events.all()],
                         [("out", "15 02:00")])
        d15 = AttendanceDay.objects.get(employee=self.sudar, date=date(2026, 10, 15))
        self.assertEqual(sorted(e.kind for e in d15.events.all()), ["in", "out"])
        self.assertEqual(self.post("1", self.FILE).data["applied"]["events"], 0)

    def test_a_tap_stored_before_as_masuk_is_not_stored_twice(self):
        day = AttendanceDay.objects.create(organization=self.org, employee=self.sudar, date=date(2026, 10, 15))
        at = dt("2026-10-15 02:00")
        ClockEvent.objects.create(organization=self.org, day=day, employee=self.sudar, kind="in", source="fingerprint",
                                  occurred_at=at.replace(tzinfo=base.WIB), received_at=at.replace(tzinfo=base.WIB),
                                  flags=[], client_id=tap_id(self.sudar, at, "in"))
        self.post("1", self.FILE)
        self.assertEqual(ClockEvent.objects.filter(employee=self.sudar, occurred_at=at.replace(tzinfo=base.WIB)).count(), 1)


for _name in [n for n in dir(base.FingerprintImportTests) if n.startswith("test_")]:
    setattr(NightOutImportTests, _name, None)
