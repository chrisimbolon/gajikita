"""
G2b (27 Oct 2026) — HR's office API: employees, sites, shifts.
Only owner / admin / hr of the same company get in, and nothing ever
crosses into another company.
"""
from datetime import date

from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.employees.worker_login import enable_login
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift, Site
from rest_framework import status
from rest_framework.test import APITestCase

EMP = "/api/hr/employees/"
SITES = "/api/hr/sites/"
SHIFTS = "/api/hr/shifts/"
BASE = {"employee_no": "BWI-010", "full_name": "Rudi Hartono", "join_date": "2026-11-02"}


def member(org, email, role):
    user = CustomUser.objects.create_user(email=email, password="pass12345!", full_name=email)
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


class HrTestCase(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.other = Organization.objects.create(name="PT Lain")
        self.hr = member(self.org, "hr@test.id", "hr")
        self.client.force_authenticate(self.hr)
        self.yard = Site.objects.create(organization=self.org, name="Workshop Tanjung Uban")
        self.foreign_site = Site.objects.create(organization=self.other, name="Pabrik Lain")


class AccessTests(HrTestCase):
    def test_owner_admin_and_hr_get_in(self):
        for role in ("owner", "admin"):
            self.client.force_authenticate(member(self.org, f"{role}@test.id", role))
            self.assertEqual(self.client.get(EMP).status_code, 200, role)

    def test_plain_member_is_refused(self):
        self.client.force_authenticate(member(self.org, "staff@test.id", "member"))
        self.assertEqual(self.client.get(EMP).status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_login_is_refused(self):
        emp = Employee.objects.create(organization=self.org, employee_no="W-1", full_name="W", join_date=date(2026, 1, 5))
        enable_login(emp, "081211112222", "482913")
        emp.refresh_from_db()
        self.client.force_authenticate(emp.user)
        self.assertEqual(self.client.get(SITES).status_code, status.HTTP_403_FORBIDDEN)

    def test_logged_out_gets_401(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(SHIFTS).status_code, status.HTTP_401_UNAUTHORIZED)


class EmployeeApiTests(HrTestCase):
    def test_add_and_list_only_my_company(self):
        Employee.objects.create(organization=self.other, employee_no="X-1", full_name="Orang Lain", join_date=date(2026, 1, 5))
        resp = self.client.post(EMP, {**BASE, "default_site": str(self.yard.id), "sites": [str(self.yard.id)]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["employee"]["sites"], [self.yard.id])
        names = [e["full_name"] for e in self.client.get(EMP).data["employees"]]
        self.assertEqual(names, ["Rudi Hartono"])

    def test_duplicate_employee_no_is_refused(self):
        self.client.post(EMP, BASE, format="json")
        resp = self.client.post(EMP, {**BASE, "full_name": "Dua"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("employee_no", resp.data)

    def test_cannot_assign_another_companys_site(self):
        resp = self.client.post(EMP, {**BASE, "default_site": str(self.foreign_site.id)}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("default_site", resp.data)

    def test_edit_and_cannot_open_another_companys_employee(self):
        emp_id = self.client.post(EMP, BASE, format="json").data["employee"]["id"]
        resp = self.client.patch(f"{EMP}{emp_id}/", {"pay_type": "daily", "base_rate": "180000"}, format="json")
        self.assertEqual((resp.status_code, resp.data["employee"]["pay_type"]), (200, "daily"))
        theirs = Employee.objects.create(organization=self.other, employee_no="X-1", full_name="X", join_date=date(2026, 1, 5))
        self.assertEqual(self.client.get(f"{EMP}{theirs.id}/").status_code, 404)

    def test_mandor_cannot_be_themself(self):
        emp_id = self.client.post(EMP, BASE, format="json").data["employee"]["id"]
        self.assertEqual(self.client.patch(f"{EMP}{emp_id}/", {"mandor": emp_id}, format="json").status_code, 400)

    def test_turn_on_login_returns_the_pin_once_and_it_works(self):
        emp_id = self.client.post(EMP, BASE, format="json").data["employee"]["id"]
        resp = self.client.post(f"{EMP}{emp_id}/login/", {"phone": "0812 7777 1234"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["employee"]["has_login"])
        self.assertEqual(resp.data["login_phone"], "081277771234")
        self.client.force_authenticate(None)
        login = self.client.post("/api/worker/login/", {"phone": "081277771234", "pin": resp.data["pin"]}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_bad_phone_is_refused(self):
        emp_id = self.client.post(EMP, BASE, format="json").data["employee"]["id"]
        resp = self.client.post(f"{EMP}{emp_id}/login/", {"phone": "12"}, format="json")
        self.assertEqual(resp.status_code, 400)


class SiteApiTests(HrTestCase):
    def test_add_a_site_with_its_first_pin(self):
        resp = self.client.post(SITES, {"name": "Jalan Lintas Barat", "kind": "moving",
                                        "latitude": 1.1366, "longitude": 104.00299, "radius_m": 300}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["site"]["location"]["radius_m"], 300)

    def test_moving_the_pin_keeps_history(self):
        url = f"{SITES}{self.yard.id}/pin/"
        self.client.post(url, {"latitude": 1.1, "longitude": 104.0, "radius_m": 150}, format="json")
        resp = self.client.post(url, {"latitude": 1.2, "longitude": 104.1}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.data["site"]["history"]), 2)
        self.assertEqual(resp.data["site"]["location"]["latitude"], 1.2)
        self.assertEqual(resp.data["site"]["location"]["radius_m"], 150, "radius carried over")

    def test_radius_out_of_range_is_refused(self):
        resp = self.client.post(f"{SITES}{self.yard.id}/pin/", {"latitude": 1.1, "longitude": 104.0, "radius_m": 5}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_name_and_foreign_site(self):
        self.assertEqual(self.client.post(SITES, {"name": "workshop tanjung uban"}, format="json").status_code, 400)
        self.assertEqual(self.client.get(f"{SITES}{self.foreign_site.id}/").status_code, 404)
        self.assertEqual([s["name"] for s in self.client.get(SITES).data["sites"]], ["Workshop Tanjung Uban"])

    def test_deactivate_a_site(self):
        resp = self.client.patch(f"{SITES}{self.yard.id}/", {"is_active": False}, format="json")
        self.assertEqual((resp.status_code, resp.data["site"]["is_active"]), (200, False))


class ShiftApiTests(HrTestCase):
    def test_add_a_night_shift(self):
        resp = self.client.post(SHIFTS, {"name": "Malam", "start_time": "22:00", "end_time": "06:00",
                                         "grace_minutes": 15, "working_days": "123456"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(resp.data["shift"]["crosses_midnight"])

    def test_bad_working_days_are_refused(self):
        resp = self.client.post(SHIFTS, {"name": "X", "start_time": "07:00", "end_time": "16:00",
                                         "working_days": "1189"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_edit_a_shift(self):
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time="08:00", end_time="17:00")
        resp = self.client.patch(f"{SHIFTS}{shift.id}/", {"grace_minutes": 5}, format="json")
        self.assertEqual((resp.status_code, resp.data["shift"]["grace_minutes"]), (200, 5))
