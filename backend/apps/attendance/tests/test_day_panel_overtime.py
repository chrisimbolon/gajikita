"""
G12h (8 Nov 2026) — found on Ganda's 13 Okt (no clock-out tap, Anthony paid 2 h overtime):
  * Setujui can approve typed overtime on a day the taps propose none (a missing clock-out);
  * not for someone who is not paid overtime;
  * Ubah jam approves the overtime its new times propose (it used to leave it empty: paid 0);
  * uang makan 'pulang malam' is AFTER 19:00 (DKCB: 'OT melebihi pukul 19.00'), so 19:00 earns none.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.payroll.payrun import collect_numbers
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
BASE = "/api/hr/attendance/"
NOW = datetime(2026, 10, 26, 10, tzinfo=WIB)
DAY = date(2026, 10, 13)                                           # a Tuesday


class DayPanelOvertimeTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.ganda = self.person("DK08", "Ganda", eligible=True)
        self.driver = self.person("DK14", "Amsar", eligible=False)
        self.cfg = PayrollSettings.for_org(self.org)
        self.cfg.meal_rule, self.cfg.meal_allowance, self.cfg.meal_late_after = "late_out", Decimal("15000"), time(19)
        self.cfg.save()

    def person(self, no, name, eligible):
        return Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=date(2021, 6, 2),
                                       default_shift=self.shift, base_rate=Decimal("3250000"), overtime_eligible=eligible)

    def only_clock_in(self, emp):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=DAY, shift=self.shift)
        t = datetime(2026, 10, 13, 8, 0, tzinfo=WIB)
        ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind="in", source="fingerprint",
                                  occurred_at=t, received_at=t)
        return day

    def fix(self, emp, out, reason="Lembur 2 jam sesuai data HR"):
        return self.client.post(f"{BASE}fix/", {"employee": str(emp.id), "date": DAY.isoformat(), "clock_out": out,
                                                "reason": reason}, format="json")

    def meals(self, emp):
        days = {d.date: d for d in AttendanceDay.objects.filter(employee=emp)}
        return collect_numbers(emp, DAY, DAY, self.cfg, days, {}, NOW)["meal_days"]

    def test_typed_overtime_on_a_day_without_a_clock_out(self):
        day = self.only_clock_in(self.ganda)
        resp = self.client.post(f"{BASE}days/{day.id}/decide/", {"action": "approve", "overtime_minutes": 120}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.data["day"]["overtime_proposed_minutes"], resp.data["day"]["overtime_approved_minutes"]), (0, 120))
        self.assertTrue(resp.data["day"]["employee"]["overtime_eligible"])

    def test_zero_typed_means_no_overtime(self):
        day = self.only_clock_in(self.ganda)
        self.client.post(f"{BASE}days/{day.id}/decide/", {"action": "approve", "overtime_minutes": 0}, format="json")
        day.refresh_from_db()
        self.assertEqual((day.decision, day.overtime_approved_minutes), ("approved", None))

    def test_not_for_someone_not_paid_overtime(self):
        day = self.only_clock_in(self.driver)
        url = f"{BASE}days/{day.id}/decide/"
        resp = self.client.post(url, {"action": "approve", "overtime_minutes": 60}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tidak berhak upah lembur", resp.data["message"])
        self.assertEqual(self.client.post(url, {"action": "approve", "overtime_minutes": None}, format="json").status_code, 200)

    def test_ubah_jam_approves_the_overtime_of_the_new_times(self):
        self.only_clock_in(self.ganda)
        resp = self.fix(self.ganda, "19:00")
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data["day"]
        self.assertEqual((d["decision"], d["overtime_proposed_minutes"], d["overtime_approved_minutes"]), ("approved", 120, 120))
        self.assertIn("lembur 120 menit", d["audit"][0]["summary"])
        resp = self.fix(self.ganda, "17:00", reason="Salah ketik")                   # back to no overtime
        self.assertIsNone(resp.data["day"]["overtime_approved_minutes"])

    def test_ubah_jam_for_someone_not_paid_overtime(self):
        self.only_clock_in(self.driver)
        self.assertIsNone(self.fix(self.driver, "21:00").data["day"]["overtime_approved_minutes"])

    def test_uang_makan_after_seven_not_at_seven(self):
        self.only_clock_in(self.ganda)
        self.fix(self.ganda, "19:00")
        self.assertEqual(self.meals(self.ganda), 0)                                   # Ganda, 13 Okt: as Anthony
        self.fix(self.ganda, "19:01")
        self.assertEqual(self.meals(self.ganda), 1)
