"""G1 (26 Oct 2026) — sites keep their pin history; shifts know about night shifts."""
from datetime import date, time, timedelta
from decimal import Decimal

from apps.organizations.models import Organization
from apps.sites.models import Shift, Site, SiteLocation
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone


class SiteLocationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.site = Site.objects.create(organization=self.org, name="Jalan Lintas Barat", kind=Site.Kind.MOVING)

    def test_moving_a_pin_keeps_the_old_one(self):
        week_ago = timezone.now() - timedelta(days=7)
        old = self.site.move_pin(Decimal("1.100000"), Decimal("104.400000"), radius_m=200, valid_from=week_ago)
        new = self.site.move_pin(Decimal("1.120000"), Decimal("104.420000"))
        self.assertEqual(SiteLocation.objects.filter(site=self.site).count(), 2)
        self.assertEqual(self.site.location_at(week_ago + timedelta(days=1)), old)
        self.assertEqual(self.site.location_at(), new)
        self.assertEqual(new.radius_m, 200, "a moved pin keeps the radius unless a new one is given")

    def test_site_without_a_pin(self):
        self.assertIsNone(self.site.location_at())

    def test_pin_takes_its_company_from_the_site(self):
        loc = SiteLocation.objects.create(site=self.site, latitude=Decimal("1.1"), longitude=Decimal("104.4"))
        self.assertEqual(loc.organization, self.org)

    def test_latitude_out_of_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.site.move_pin(Decimal("91"), Decimal("104.4"))

    def test_only_fixed_and_moving_sites_are_fenced(self):
        self.assertTrue(self.site.is_fenced)
        tug = Site.objects.create(organization=self.org, name="TB Bintan Jaya", kind=Site.Kind.VESSEL)
        self.assertFalse(tug.is_fenced)


class ShiftTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Pabrik Maju")

    def test_night_shift_crosses_midnight(self):
        night = Shift(organization=self.org, name="Malam", start_time=time(22), end_time=time(6))
        day = Shift(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17))
        self.assertTrue(night.crosses_midnight)
        self.assertFalse(day.crosses_midnight)

    def test_working_days(self):
        six_days = Shift(organization=self.org, name="Lapangan", start_time=time(7), end_time=time(16),
                         working_days="123456")
        self.assertTrue(six_days.is_working_day(date(2026, 10, 31)))     # Saturday
        self.assertFalse(six_days.is_working_day(date(2026, 11, 1)))     # Sunday

    def test_bad_working_days_are_rejected(self):
        shift = Shift(organization=self.org, name="X", start_time=time(7), end_time=time(16), working_days="1189")
        with self.assertRaises(ValidationError):
            shift.full_clean()
