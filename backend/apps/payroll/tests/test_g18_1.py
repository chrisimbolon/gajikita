"""
G18-1 (19 Nov 2026) — "Aturan perusahaan vs UU". Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from apps.employees.models import Employee
from apps.payroll import law_check as L
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

UMK = D("4583221")


class RowTests(SimpleTestCase):
    def test_overtime(self):
        self.assertEqual(L.overtime_row("pp35", 0).status, L.OK)
        row = L.overtime_row("flat", D("12500"), "Diubah oleh Anthony, 20 Nov 2026")
        self.assertEqual((row.status, row.changed), (L.DIFFERS, "Diubah oleh Anthony, 20 Nov 2026"))
        self.assertIn("Rp 12.500", row.company)

    def test_umk(self):
        self.assertEqual(L.umk_row(0, []).status, L.MISSING)
        self.assertEqual(L.umk_row(UMK, []).status, L.OK)
        row = L.umk_row(UMK, ["Vina", "Budi"])
        self.assertEqual((row.status, row.people), (L.FOUND, ["Budi", "Vina"]))
        self.assertIn("Rp 4.583.221", row.company)

    def test_base_share(self):
        self.assertEqual(L.base_share_row([]).status, L.OK)
        self.assertEqual(L.base_share_row(["Eka"]).status, L.FOUND)

    def test_people_checks(self):
        today = date(2026, 11, 19)
        people = [("Baru", date(2026, 6, 1), D("3000000"), D("1500000")),      # < 1 year, under UMK, 66%
                  ("Lama", date(2020, 1, 6), D("3000000"), D("0")),            # under UMK but > 1 year: fine
                  ("Pas", date(2026, 6, 1), D("4000000"), D("600000"))]        # 4,6 jt >= UMK, 86%
        self.assertEqual(L.people_checks(people, UMK, today), (["Baru"], ["Baru"]))
        self.assertEqual(L.people_checks(people, 0, today), ([], ["Baru"]))   # no UMK set: no UMK check

    def test_changed_text(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        at = datetime(2026, 11, 19, 20, 0, tzinfo=ZoneInfo("UTC"))           # 20 Nov 03:00 in Jakarta
        self.assertEqual(L.changed_text("Anthony", at), "Diubah oleh Anthony, 20 Nov 2026")
        self.assertEqual(L.changed_text("Anthony", None), "")


class LawCheckApiTests(base.PayRunTests):
    URL = "/api/hr/payroll/law-check/"

    def test_rows(self):
        PayrollSettings.objects.filter(organization=self.org).update(minimum_wage=UMK)
        Employee.objects.create(organization=self.org, employee_no="B-9", full_name="Eka", join_date=date(2026, 6, 1),
                                default_shift=self.shift, base_rate=D("3000000"), fixed_allowance=D("1500000"))
        data = self.client.get(self.URL).data
        rows = {r["key"]: r for r in data["rows"]}
        self.assertEqual(data["law"], "UU No. 27 Tahun 2026")
        self.assertEqual(rows["overtime"]["status"], "differs")             # the test company uses flat rates
        self.assertEqual((rows["umk"]["status"], rows["umk"]["people"]), ("found", ["Eka"]))   # Andi, Budi: > 1 year
        self.assertEqual((rows["base_share"]["status"], rows["base_share"]["people"]), ("found", ["Eka"]))
        self.assertEqual(rows["annual_leave"]["status"], "ok")

    def test_who_changed_it(self):
        self.client.patch("/api/hr/payroll/settings/", {"overtime_mode": "pp35"}, format="json")
        row = {r["key"]: r for r in self.client.get(self.URL).data["rows"]}["overtime"]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["changed"], "Diubah oleh Anthony, 26 Okt 2026")

    def test_workers_cannot_see_it(self):
        from apps.authentication.models import CustomUser
        user = CustomUser.objects.create_user(email="w2@beton.id", password="pass12345!", full_name="W", role="employee")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(self.URL).status_code, 403)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(LawCheckApiTests, _name, None)
