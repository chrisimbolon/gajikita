"""
G2a (27 Oct 2026) — phone + PIN login for workers, PIN change, lockout,
and the two setup commands.
"""
import io
from datetime import date, timedelta
from unittest import mock

from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.employees.worker_login import enable_login, normalize_phone, validate_pin
from apps.organizations.models import Organization
from apps.sites.models import Site
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

LOGIN = "/api/worker/login/"
PIN_URL = "/api/worker/pin/"
TODAY = "/api/attendance/today/"


class PhoneAndPinRulesTests(SimpleTestCase):
    def test_phone_numbers_are_normalized(self):
        for raw in ("+62 812-3456-7890", "6281234567890", "81234567890", "0812 3456 7890"):
            self.assertEqual(normalize_phone(raw), "081234567890", raw)

    def test_easy_pins_are_refused(self):
        for bad in ("111111", "123456", "654321", "12345", "abcdef", ""):
            with self.assertRaises(ValueError, msg=bad):
                validate_pin(bad)
        self.assertEqual(validate_pin("482913"), "482913")


class WorkerLoginTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.emp = Employee.objects.create(organization=self.org, employee_no="BWI-001", full_name="Budi Santoso",
                                           join_date=date(2025, 1, 6))
        self.pin = enable_login(self.emp, "0812-3456-7890", "482913")
        self.emp.refresh_from_db()

    def _login(self, pin="482913", phone="+62 812 3456 7890"):
        return self.client.post(LOGIN, {"phone": phone, "pin": pin}, format="json")

    def test_enable_login_creates_a_hidden_employee_user(self):
        user = self.emp.user
        self.assertEqual(user.role, CustomUser.Role.EMPLOYEE)
        self.assertTrue(user.email.endswith("@pekerja.gajikita.id"))
        self.assertEqual((self.emp.login_phone, self.emp.must_change_pin), ("081234567890", True))
        self.assertFalse(user.check_password("000000"))
        self.assertTrue(user.check_password("482913"))

    def test_random_pin_when_none_given(self):
        other = Employee.objects.create(organization=self.org, employee_no="BWI-002", full_name="Andi",
                                        join_date=date(2025, 1, 6))
        pin = enable_login(other, "081299990000")
        self.assertEqual(validate_pin(pin), pin)

    def test_same_phone_cannot_log_in_two_employees(self):
        other = Employee.objects.create(organization=self.org, employee_no="BWI-002", full_name="Andi",
                                        join_date=date(2025, 1, 6))
        with self.assertRaises(ValueError):
            enable_login(other, "081234567890")

    def test_login_works_with_any_phone_format(self):
        resp = self._login()
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["must_change_pin"])
        self.assertEqual(resp.data["employee"]["full_name"], "Budi Santoso")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        today = self.client.get(TODAY)
        self.assertEqual(today.status_code, status.HTTP_200_OK)
        self.assertTrue(today.data["must_change_pin"])

    def test_unknown_phone_and_wrong_pin_look_the_same(self):
        unknown = self._login(phone="081100000000")
        wrong = self._login(pin="000001")
        self.assertEqual((unknown.status_code, wrong.status_code), (400, 400))
        self.assertTrue(unknown.data["message"].startswith("No. HP atau PIN salah."))
        self.assertIn("Sisa percobaan: 4", wrong.data["message"])

    def test_five_wrong_pins_lock_for_15_minutes(self):
        for _ in range(4):
            self.assertEqual(self._login(pin="000001").status_code, 400)
        self.assertEqual(self._login(pin="000001").status_code, status.HTTP_423_LOCKED)
        self.assertEqual(self._login().status_code, status.HTTP_423_LOCKED, "even the right PIN waits")
        later = timezone.now() + timedelta(minutes=16)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(self._login().status_code, status.HTTP_200_OK)
        self.emp.refresh_from_db()
        self.assertEqual((self.emp.pin_failed_attempts, self.emp.pin_locked_until), (0, None))

    def test_resigned_worker_cannot_log_in(self):
        Employee.objects.filter(pk=self.emp.pk).update(status=Employee.Status.RESIGNED)
        self.assertEqual(self._login().status_code, 400)

    def test_change_pin(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login().data['access']}")
        self.assertEqual(self.client.post(PIN_URL, {"current_pin": "999999", "new_pin": "730518"},
                                          format="json").status_code, 400)
        self.assertEqual(self.client.post(PIN_URL, {"current_pin": "482913", "new_pin": "123456"},
                                          format="json").status_code, 400)
        ok = self.client.post(PIN_URL, {"current_pin": "482913", "new_pin": "730518"}, format="json")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.must_change_pin)
        self.client.credentials()
        self.assertEqual(self._login(pin="482913").status_code, 400)
        self.assertEqual(self._login(pin="730518").status_code, 200)

    def test_office_user_cannot_use_the_pin_endpoint(self):
        boss = CustomUser.objects.create_user(email="boss@test.id", password="pass12345!", full_name="Boss")
        self.client.force_authenticate(boss)
        self.assertEqual(self.client.post(PIN_URL, {}, format="json").status_code, 403)


class SetupCommandTests(APITestCase):
    def test_set_worker_pin(self):
        org = Organization.objects.create(name="PT Bangun Wira Indah")
        Employee.objects.create(organization=org, employee_no="BWI-007", full_name="Joko", join_date=date(2025, 1, 6))
        out = io.StringIO()
        call_command("set_worker_pin", "BWI-007", "--phone", "081277778888", "--pin", "482913", stdout=out)
        self.assertIn("PIN    : 482913", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("set_worker_pin", "NOPE", "--phone", "081277778889", stdout=io.StringIO())

    def test_seed_demo_attendance_is_safe_to_run_twice(self):
        args = ["--lat", "1.130000", "--lng", "104.050000", "--phone", "081255556666", "--pin", "482913"]
        call_command("seed_demo_attendance", *args, stdout=io.StringIO())
        call_command("seed_demo_attendance", *args, stdout=io.StringIO())
        site = Site.objects.get(name="Kantor Demo")
        self.assertEqual(site.locations.count(), 1)
        call_command("seed_demo_attendance", "--lat", "1.140000", "--lng", "104.050000", "--phone", "081255556666",
                     "--pin", "482913", stdout=io.StringIO())
        self.assertEqual(site.locations.count(), 2, "new coordinates move the pin, history kept")
        self.assertEqual(Employee.objects.filter(employee_no="DEMO-001").count(), 1)
        resp = self.client.post(LOGIN, {"phone": "081255556666", "pin": "482913"}, format="json")
        self.assertEqual(resp.status_code, 200)
