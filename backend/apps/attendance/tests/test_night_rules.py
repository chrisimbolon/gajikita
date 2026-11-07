"""
G12e (7 Nov 2026) — coming in later after overtime past midnight (night_rules.py + evaluate_day).
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.night_rules import DKCB_EXAMPLE, NightStart, RuleError, night_start, parse_rules

WIB = ZoneInfo("Asia/Jakarta")
PAGI = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
TUE = date(2026, 10, 20)
LATER = datetime(2026, 10, 26, 12, tzinfo=WIB)
RULES = parse_rules(DKCB_EXAMPLE)


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class ParseRulesTests(SimpleTestCase):
    def test_the_dkcb_rows(self):
        self.assertEqual(RULES, ((time(1, 59), time(10)), (time(4), time(13)), (None, None)))

    def test_empty_switches_it_off(self):
        self.assertEqual(parse_rules([]), ())
        self.assertEqual(parse_rules(None), ())

    def test_mistakes_are_explained(self):
        bad = [
            [{"until": "04:00", "start": "13:00"}, {"until": "02:00", "start": "10:00"}],   # not increasing
            [{"until": "", "start": ""}, {"until": "02:00", "start": "10:00"}],             # catch-all not last
            [{"until": "25:00", "start": "10:00"}],                                         # not a time
            [{"until": "14:00", "start": "15:00"}],                                         # not after midnight
            "02:00",
            [{"until": "0%d:00" % i, "start": ""} for i in range(1, 8)],                    # too many rows
        ]
        for raw in bad:
            with self.assertRaises(RuleError):
                parse_rules(raw)


class NightStartTests(SimpleTestCase):
    def start(self, h, m, crosses=False, day=TUE):
        return night_start(day, at(day, h, m), crosses, RULES)

    def test_each_row_and_its_edges(self):
        self.assertEqual(self.start(0, 0).start, time(10))        # 00:00 counts (DKCB: "00:00 - 01:59")
        self.assertEqual(self.start(1, 59).start, time(10))
        self.assertEqual(self.start(2, 0).start, time(13))
        self.assertEqual(self.start(4, 0).start, time(13))
        self.assertTrue(self.start(4, 1).day_off)
        self.assertTrue(self.start(6, 30).day_off)

    def test_seconds_do_not_count(self):
        self.assertEqual(night_start(TUE, datetime(2026, 10, 20, 1, 59, 50, tzinfo=WIB), False, RULES).start, time(10))

    def test_only_when_the_work_ran_past_midnight_into_this_day(self):
        self.assertIsNone(night_start(TUE, at(date(2026, 10, 19), 23, 50), False, RULES))   # ended the day before
        self.assertIsNone(self.start(0, 30, crosses=True))     # a night shift ends in the morning by design
        self.assertIsNone(night_start(TUE, None, False, RULES))
        self.assertIsNone(night_start(TUE, at(TUE, 0, 30), False, ()))   # rule switched off

    def test_note(self):
        self.assertEqual(self.start(0, 30).note, "Lembur malam sampai 00:30: masuk jam 10:00")
        self.assertEqual(self.start(5, 0).note, "Lembur malam sampai 05:00: hari ini libur")


def ev(taps, night=None, **kw):
    return evaluate_day(TUE, PAGI, [Tap(k, t) for k, t in taps], LATER, WIB, night=night, **kw)


class EvaluateDayWithNightTests(SimpleTestCase):
    def test_late_counts_from_the_new_start(self):
        # Ganda 20 Okt: worked until 00:30, allowed in at 10:00, came 10:19 -> 19 minutes late, not 139
        r = ev([("in", at(TUE, 10, 19)), ("out", at(TUE, 17, 30))], NightStart(at(TUE, 0, 30), time(10)))
        self.assertEqual((r.status, r.late_minutes), (Status.LATE, 19))
        self.assertEqual(r.note, "Lembur malam sampai 00:30: masuk jam 10:00")
        plain = ev([("in", at(TUE, 10, 19)), ("out", at(TUE, 17, 30))])
        self.assertEqual((plain.late_minutes, plain.note), (139, ""))

    def test_coming_early_is_fine(self):
        r = ev([("in", at(TUE, 12, 27)), ("out", at(TUE, 19, 19))], NightStart(at(TUE, 2, 1), time(13)))
        self.assertNotIn(Status.LATE, r.tags)
        r = ev([("in", at(TUE, 8, 27)), ("out", at(TUE, 20, 30))], NightStart(at(TUE, 0, 6), time(10)))
        self.assertNotIn(Status.LATE, r.tags)

    def test_a_night_day_off_is_not_an_absence(self):
        r = ev([], NightStart(at(TUE, 5, 0), None))
        self.assertEqual(r.status, Status.DAY_OFF)
        self.assertIn("libur", r.note)
        came = ev([("in", at(TUE, 11, 0)), ("out", at(TUE, 15, 0))], NightStart(at(TUE, 5, 0), None))
        self.assertNotIn(Status.LATE, came.tags)
        self.assertNotIn(Status.EARLY_OUT, came.tags)

    def test_nothing_changes_on_a_rest_day(self):
        sunday = date(2026, 10, 18)
        r = evaluate_day(sunday, PAGI, [], LATER, WIB, night=NightStart(at(sunday, 3, 4), time(13)))
        self.assertEqual((r.status, r.note), (Status.DAY_OFF, ""))

    def test_overtime_minimum_is_a_setting(self):
        taps = [("in", at(TUE, 7, 55)), ("out", at(TUE, 17, 59))]
        self.assertEqual(ev(taps).overtime_proposed_minutes, 59)                       # default: from 30 minutes
        self.assertEqual(ev(taps, overtime_min=60).overtime_proposed_minutes, 0)       # DKCB: from 18:00
        r = ev([("in", at(TUE, 7, 55)), ("out", at(TUE, 18, 0))], overtime_min=60)
        self.assertEqual(r.overtime_proposed_minutes, 60)
