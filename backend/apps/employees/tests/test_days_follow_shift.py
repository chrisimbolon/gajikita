"""G17-5.1 (15 Nov 2026): a new shift for an employee also judges the days not yet locked. Made-up data."""
from datetime import date, time
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift


class DaysFollowShiftTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Contoh Shift")
        hr = CustomUser.objects.create_user(email="hr@shift.id", password="pass12345!", full_name="HR Shift")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.pagi = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                         working_days="123456")
        self.kantor = Shift.objects.create(organization=self.org, name="Kantor", start_time=time(8), end_time=time(17),
                                           working_days="123456", saturday_end_time=time(12))
        self.emp = Employee.objects.create(organization=self.org, employee_no="S-1", full_name="Tari Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("3000000"),
                                           default_shift=self.pagi)
        mk = lambda d, locked=False: AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d,
                                                                   shift=self.pagi, is_locked=locked)
        self.locked, self.open1, self.open2 = mk(date(2026, 9, 19), True), mk(date(2026, 10, 3)), mk(date(2026, 10, 10))

    def save(self, **body):
        resp = self.client.patch(f"/api/hr/employees/{self.emp.pk}/", body, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["employee"]["shift_days_moved"]

    def shift_of(self, day):
        day.refresh_from_db()
        return day.shift_id

    def test_unlocked_days_follow_and_locked_days_stay(self):
        self.assertEqual(self.save(default_shift=str(self.kantor.pk)), 2)
        self.assertEqual((self.shift_of(self.open1), self.shift_of(self.open2)), (self.kantor.pk, self.kantor.pk))
        self.assertEqual(self.shift_of(self.locked), self.pagi.pk)

    def test_saving_again_fixes_days_left_behind_and_other_fields_do_nothing(self):
        Employee.objects.filter(pk=self.emp.pk).update(default_shift=self.kantor)      # changed before G17-5.1
        self.assertEqual(self.save(default_shift=str(self.kantor.pk)), 2)               # one more "Simpan"
        self.assertEqual(self.save(default_shift=str(self.kantor.pk)), 0)
        self.assertEqual(self.save(position="Admin"), 0)
