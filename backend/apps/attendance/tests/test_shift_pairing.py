"""
G12c (6 Nov 2026) — shift-aware pairing of fingerprint taps.

The taps below are a real DKCB concrete-pump helper's month (anonymised as K22, times only),
transcribed from the October 2026 "ASR Edit" grid, with the HR manager's own overtime hours per
day. Paired by time alone (16 h rule) the second half of the month falls apart; paired around the
08:00 shift every day lands where HR put it, and the overtime matches HR's 93 hours except on the
four days HR decided by hand (no SPL / not counted).
"""
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.test import SimpleTestCase

from apps.attendance.fingerprint import make_sessions

K22 = {
    "2026-09-26": "08:12 08:12 20:30 20:30", "2026-09-28": "08:11 08:11 20:11 20:12", "2026-09-29": "08:14 08:14 18:09 18:09",
    "2026-09-30": "08:10 08:10 08:10 22:00 22:00 22:00", "2026-10-01": "08:04 08:04 20:02 20:02 20:02",
    "2026-10-02": "08:16 08:16 19:02 19:02 19:02 19:02", "2026-10-03": "08:07 08:07 08:07", "2026-10-04": "00:00 00:00 00:00",
    "2026-10-05": "08:23 08:23 08:23 20:22 20:22", "2026-10-06": "08:59 08:59 08:59 21:06 21:06",
    "2026-10-07": "08:21 08:21 20:00 20:01 20:01", "2026-10-08": "08:13 08:13 08:13 20:09 20:09 20:09",
    "2026-10-09": "08:29 08:29 19:01 19:01 19:01", "2026-10-10": "08:21 08:21 08:21 21:00 21:00 21:00",
    "2026-10-12": "08:25 08:25", "2026-10-13": "08:03 08:03 08:03", "2026-10-14": "07:56 07:56 07:56 22:19 22:19 22:19",
    "2026-10-15": "08:11 08:11 08:11 08:11", "2026-10-16": "02:01 02:01 12:27 12:27 12:27 19:19 19:19",
    "2026-10-17": "08:18 08:18 08:18", "2026-10-18": "03:04 03:04", "2026-10-19": "08:15 08:15 08:15",
    "2026-10-20": "00:30 00:30 10:19 10:19 17:30 17:30", "2026-10-21": "08:21 08:21",
    "2026-10-22": "00:06 00:06 00:06 08:27 08:27 20:30 20:30 20:30", "2026-10-23": "08:15 08:15 08:15",
    "2026-10-24": "00:01 00:01 08:19 08:19 08:19 17:13 17:13 17:13",
}
HR_OVERTIME = {"2026-09-26": 3.5, "2026-09-28": 3, "2026-09-30": 5, "2026-10-01": 3, "2026-10-02": 2, "2026-10-03": 7,
               "2026-10-05": 3.5, "2026-10-06": 4, "2026-10-07": 3, "2026-10-08": 3, "2026-10-09": 2, "2026-10-10": 0,
               "2026-10-13": 2, "2026-10-14": 5.5, "2026-10-15": 9, "2026-10-16": 2.5, "2026-10-17": 10, "2026-10-19": 7.5,
               "2026-10-21": 7, "2026-10-22": 3.5, "2026-10-23": 7}
DECIDED_BY_HAND = {"2026-09-29", "2026-10-10", "2026-10-13", "2026-10-20"}   # not counted / no clock-out tap


def k22_taps():
    out = []
    for d, cell in K22.items():
        seen = {}
        for t in cell.split():
            seen[t] = seen.get(t, -1) + 1
            out.append(datetime.fromisoformat(f"{d} {t}:00") + timedelta(seconds=5 * seen[t]))
    return out


def overtime_hours(s):
    if s.clock_out is None:
        return 0
    minutes = (s.clock_out - datetime.combine(s.work_date, time(17))).total_seconds() // 60
    if minutes < 30:
        return 0
    return float((Decimal(minutes) / 30).quantize(Decimal(1), rounding=ROUND_HALF_UP) * Decimal("0.5"))


class ShiftPairingTests(SimpleTestCase):
    def test_k22_month_lands_on_the_right_days(self):
        sessions = make_sessions(k22_taps(), shift_start=time(8))
        days = {str(s.work_date): s for s in sessions}
        self.assertEqual(len(sessions), 25)                                        # 25 days present
        self.assertEqual(sorted(days), sorted(d for d in K22 if d not in ("2026-10-04", "2026-10-18")))
        s15 = days["2026-10-15"]
        self.assertEqual((s15.clock_in, s15.clock_out), (datetime(2026, 10, 15, 8, 11), datetime(2026, 10, 16, 2, 1)))
        s16 = days["2026-10-16"]
        self.assertEqual((s16.clock_in, s16.clock_out), (datetime(2026, 10, 16, 12, 27), datetime(2026, 10, 16, 19, 19)))
        self.assertEqual(days["2026-10-17"].clock_out, datetime(2026, 10, 18, 3, 4))   # Saturday into Sunday

    def test_k22_overtime_matches_the_hr_manager(self):
        sessions = make_sessions(k22_taps(), shift_start=time(8))
        for s in sessions:
            d = str(s.work_date)
            if d not in DECIDED_BY_HAND:
                self.assertEqual(overtime_hours(s), HR_OVERTIME.get(d, 0), d)
        counted = sum(HR_OVERTIME.get(str(s.work_date), 0) for s in sessions)
        self.assertEqual(counted, 93)

    def test_by_time_alone_the_same_month_breaks(self):
        old = make_sessions(k22_taps())                                             # no shift: the 16 h rule
        self.assertNotEqual(len(old), 25)

    def test_ordinary_days_still_work_with_a_shift(self):
        d = lambda s: datetime.fromisoformat(s)
        lunch = make_sessions([d("2026-10-05 08:00"), d("2026-10-05 12:00"), d("2026-10-05 13:00"), d("2026-10-05 17:00")],
                              shift_start=time(8))
        self.assertEqual([(s.clock_in.hour, s.clock_out.hour) for s in lunch], [(8, 17)])
        forgot = make_sessions([d("2026-10-01 07:55"), d("2026-10-02 07:50"), d("2026-10-02 17:02")], shift_start=time(8))
        self.assertEqual([(str(s.work_date), s.clock_out) for s in forgot],
                         [("2026-10-01", None), ("2026-10-02", d("2026-10-02 17:02"))])
        night = make_sessions([d("2026-10-01 19:55"), d("2026-10-02 05:10"), d("2026-10-02 19:50"), d("2026-10-03 05:02")],
                              shift_start=time(20))
        self.assertEqual([(str(s.work_date), s.clock_out.hour) for s in night], [("2026-10-01", 5), ("2026-10-02", 5)])
