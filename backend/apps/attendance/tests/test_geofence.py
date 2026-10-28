"""
G1 (26 Oct 2026) — the pure geofence rules in apps/attendance/geofence.py.
No database: these run in milliseconds and pin down every rule in the
Design v0.1 "Attendance with geofence" section.
"""
from datetime import date, datetime, time, timedelta, timezone as dt_tz

from apps.attendance.geofence import (
    Candidate, Flag, evaluate, haversine_m, resolve_time, work_date,
)
from django.test import SimpleTestCase

M_PER_DEG_LAT = 111_195.08          # metres per degree of latitude at EARTH_RADIUS_M
PIN = (1.130000, 104.050000)         # a point in Batam


def north(metres, of=PIN):
    """A point `metres` due north of `of`."""
    return of[0] + metres / M_PER_DEG_LAT, of[1]


def fenced(site_id="A", at=PIN, radius=150, kind="fixed"):
    return Candidate(site_id=site_id, kind=kind, latitude=at[0], longitude=at[1], radius_m=radius,
                     location_id=f"loc-{site_id}")


class HaversineTests(SimpleTestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(haversine_m(*PIN, *PIN), 0)

    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_m(0, 0, 1, 0), M_PER_DEG_LAT, delta=1)

    def test_fifty_metres_north(self):
        self.assertAlmostEqual(haversine_m(*PIN, *north(50)), 50, delta=0.5)


class EvaluateTests(SimpleTestCase):
    def test_inside_the_radius_has_no_flags(self):
        r = evaluate([fenced()], *north(50), accuracy_m=10)
        self.assertEqual((r.site_id, r.location_id, r.distance_m, r.flags), ("A", "loc-A", 50, []))

    def test_outside_is_recorded_not_refused(self):
        r = evaluate([fenced()], *north(350), accuracy_m=10)
        self.assertEqual(r.site_id, "A")
        self.assertEqual(r.distance_m, 350)
        self.assertEqual(r.flags, [Flag.OUTSIDE_SITE])

    def test_nearest_site_wins(self):
        far = fenced("FAR", at=north(2000))
        near = fenced("NEAR", at=north(100))
        r = evaluate([far, near], *north(120), accuracy_m=10)
        self.assertEqual((r.site_id, r.distance_m, r.flags), ("NEAR", 20, []))

    def test_inside_a_site_beats_a_nearer_site_whose_radius_is_smaller(self):
        small = fenced("SMALL", at=north(60), radius=20)      # 60 m away, radius 20 -> outside
        big = fenced("BIG", at=north(-200), radius=300)       # 200 m away, radius 300 -> inside
        r = evaluate([small, big], *PIN, accuracy_m=10)
        self.assertEqual((r.site_id, r.flags), ("BIG", []))

    def test_vessel_is_never_outside(self):
        vessel = Candidate(site_id="TUG", kind="vessel")
        r = evaluate([vessel], *north(30_000), accuracy_m=10)
        self.assertEqual((r.site_id, r.distance_m, r.flags), ("TUG", None, []))

    def test_outside_every_fence_but_has_a_vessel_site(self):
        r = evaluate([fenced(), Candidate(site_id="TUG", kind="vessel")], *north(5000), accuracy_m=10)
        self.assertEqual((r.site_id, r.flags), ("TUG", []))

    def test_low_accuracy_is_flagged_on_top(self):
        r = evaluate([fenced()], *north(50), accuracy_m=150)
        self.assertEqual(r.flags, [Flag.LOW_ACCURACY])
        self.assertEqual(evaluate([fenced()], *north(50), accuracy_m=100).flags, [])

    def test_no_gps_with_one_site_still_picks_it(self):
        r = evaluate([fenced()], None, None, accuracy_m=None)
        self.assertEqual((r.site_id, r.flags), ("A", [Flag.NO_GPS]))

    def test_no_gps_with_several_sites_picks_none(self):
        r = evaluate([fenced("A"), fenced("B", at=north(500))], None, None, accuracy_m=None)
        self.assertEqual((r.site_id, r.flags), (None, [Flag.NO_GPS]))

    def test_no_sites_at_all(self):
        self.assertEqual(evaluate([], *PIN, accuracy_m=5).flags, [Flag.NO_SITE])

    def test_fenced_site_without_a_pin(self):
        r = evaluate([Candidate(site_id="NEW", kind="fixed")], *PIN, accuracy_m=5)
        self.assertEqual((r.site_id, r.flags), ("NEW", [Flag.NO_PIN]))


class ResolveTimeTests(SimpleTestCase):
    NOW = datetime(2026, 10, 27, 2, 0, tzinfo=dt_tz.utc)    # 09:00 WIB

    def test_no_phone_time_uses_server_time(self):
        self.assertEqual(resolve_time(self.NOW, None, False), (self.NOW, []))

    def test_small_drift_uses_server_time_without_flag(self):
        self.assertEqual(resolve_time(self.NOW, self.NOW - timedelta(minutes=3), False), (self.NOW, []))

    def test_phone_clock_off_by_30_minutes_is_flagged(self):
        self.assertEqual(resolve_time(self.NOW, self.NOW - timedelta(minutes=30), False),
                         (self.NOW, [Flag.TIME_GAP]))

    def test_offline_tap_keeps_the_phone_time(self):
        two_hours_ago = self.NOW - timedelta(hours=2)
        self.assertEqual(resolve_time(self.NOW, two_hours_ago, True), (two_hours_ago, [Flag.OFFLINE]))

    def test_offline_tap_older_than_72_hours_is_not_trusted(self):
        old = self.NOW - timedelta(hours=80)
        self.assertEqual(resolve_time(self.NOW, old, True), (self.NOW, [Flag.OFFLINE, Flag.TIME_GAP]))

    def test_offline_tap_from_the_future_is_not_trusted(self):
        future = self.NOW + timedelta(hours=1)
        self.assertEqual(resolve_time(self.NOW, future, True), (self.NOW, [Flag.OFFLINE, Flag.TIME_GAP]))


class WorkDateTests(SimpleTestCase):
    def test_day_shift(self):
        self.assertEqual(work_date(datetime(2026, 10, 27, 7, 55), time(8), time(17)), date(2026, 10, 27))

    def test_night_shift_before_midnight(self):
        self.assertEqual(work_date(datetime(2026, 10, 27, 21, 55), time(22), time(6)), date(2026, 10, 27))

    def test_night_shift_late_clock_in_after_midnight_belongs_to_yesterday(self):
        self.assertEqual(work_date(datetime(2026, 10, 28, 0, 20), time(22), time(6)), date(2026, 10, 27))

    def test_no_shift(self):
        self.assertEqual(work_date(datetime(2026, 10, 28, 0, 20)), date(2026, 10, 28))
