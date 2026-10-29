"""G1 (26 Oct 2026) — employee numbers per company, and which sites a worker may clock in at."""
from datetime import date

from apps.employees.models import Employee
from apps.organizations.models import Organization
from apps.sites.models import Site
from django.db import IntegrityError
from django.test import TestCase


class EmployeeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.other = Organization.objects.create(name="PT Lain")
        self.yard = Site.objects.create(organization=self.org, name="Workshop Tanjung Uban")
        self.road = Site.objects.create(organization=self.org, name="Jalan Lintas Barat", kind=Site.Kind.MOVING)
        self.closed = Site.objects.create(organization=self.org, name="Proyek Lama", is_active=False)
        self.foreign = Site.objects.create(organization=self.other, name="Pabrik Lain")

    def _emp(self, no="BWI-001", org=None, **kw):
        return Employee.objects.create(organization=org or self.org, employee_no=no, full_name="Budi Santoso",
                                       join_date=date(2025, 1, 6), **kw)

    def test_employee_no_is_unique_within_a_company(self):
        self._emp()
        self._emp(org=self.other)                      # same number, other company: fine
        with self.assertRaises(IntegrityError):
            self._emp()

    def test_no_assigned_sites_means_every_active_site_of_my_company(self):
        names = sorted(s.name for s in self._emp().candidate_sites())
        self.assertEqual(names, ["Jalan Lintas Barat", "Workshop Tanjung Uban"])

    def test_assigned_sites_plus_default_site(self):
        emp = self._emp(default_site=self.yard)
        emp.sites.add(self.road, self.closed)
        names = sorted(s.name for s in emp.candidate_sites())
        self.assertEqual(names, ["Jalan Lintas Barat", "Workshop Tanjung Uban"], "inactive sites are left out")

    def test_resigned_is_not_active(self):
        self.assertFalse(self._emp(status=Employee.Status.RESIGNED).is_active)
