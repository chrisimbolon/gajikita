"""
G14-1 (20 Nov 2026) — leave under UU No. 27/2026: Libur days are not leave days, cuti bersama, cuti pendampingan,
cuti haid, the settings page and the law-check rows. Made-up people.
"""
from datetime import date

from django.test import SimpleTestCase

from apps.attendance.models import CompanyEvent
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.leave import rules
from apps.leave.models import LeaveRequest
from apps.leave.tests import test_leave_api as base

SETTINGS = "/api/hr/leave/settings/"


class ReasonRuleTests(SimpleTestCase):
    def test_reasons_follow_the_settings(self):
        r = rules.special_reasons(3, True)
        self.assertEqual((r["wife_birth"][1], r["wife_miscarriage"][1], r[rules.MENSTRUAL][1]), (5, 2, 2))
        r = rules.special_reasons(0, False)
        self.assertEqual(r["wife_birth"][1], 2)
        self.assertNotIn(rules.MENSTRUAL, r)

    def test_check_request_uses_the_company_limits(self):
        common = dict(kind=rules.SPECIAL, special_reason="wife_birth", start=date(2026, 11, 2), end=date(2026, 11, 7),
                      annual_left=0, today=date(2026, 10, 28), by_worker=True)
        self.assertEqual(rules.check_request(days=5, reasons=rules.special_reasons(3, True), **common), {})
        self.assertIn("end_date", rules.check_request(days=5, reasons=rules.special_reasons(0, True), **common))


class LeaveUu27Tests(base.LeaveApiTests):
    def libur(self, start, end, collective=False, reason="Cuti bersama Natal"):
        return CompanyEvent.objects.create(organization=self.org, start=start, end=end, kind="libur", reason=reason,
                                           collective_leave=collective)

    def test_a_libur_day_is_not_annual_leave(self):
        self.libur(date(2026, 11, 4), date(2026, 11, 4))
        r = self.ask(self.budi)                                          # Mon 2 - Sat 7 Nov: 6 working days
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["leave"]["days"], 5)

    def test_a_new_libur_recounts_waiting_leave(self):
        r = self.ask(self.budi)
        self.assertEqual(r.data["leave"]["days"], 6)
        self.as_("hr")
        r = self.client.post("/api/hr/attendance/events/", {"start": "2026-11-04", "end": "2026-11-04", "kind": "libur",
                                                             "reason": "Cuti bersama", "everyone": True,
                                                             "collective_leave": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["event"]["collective_leave"])
        self.assertEqual(LeaveRequest.objects.get(employee=self.budi).days, 5)

    def test_cuti_bersama_takes_annual_leave_only_when_the_company_chooses_so(self):
        self.libur(date(2026, 12, 24), date(2026, 12, 24), collective=True)
        self.as_(self.budi)
        self.assertEqual(self.client.get(base.MINE).data["annual"]["used"], 0)          # the law: not reduced
        self.as_("hr")
        r = self.client.patch(SETTINGS, {"collective_leave_reduces_annual": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="leave.settings").exists())
        self.as_(self.budi)
        annual = self.client.get(base.MINE).data["annual"]
        self.assertEqual((annual["used"], annual["collective"], annual["left"]), (1, 1, 11))
        self.as_(self.citra)                                             # not entitled yet: nothing taken
        self.assertEqual(self.client.get(base.MINE).data["annual"]["collective"], 0)

    def test_paternity_extra_days_come_from_the_settings(self):
        r = self.ask(self.budi, kind="special", special_reason="wife_birth", start_date="2026-11-02", end_date="2026-11-06")
        self.assertEqual(r.status_code, 201, r.data)                     # 2 + 3 days (default)
        self.as_("hr")
        self.client.patch(SETTINGS, {"paternity_extra_days": 0}, format="json")
        r = self.ask(self.budi, kind="special", special_reason="wife_birth", start_date="2026-11-09", end_date="2026-11-11")
        self.assertEqual(r.status_code, 400)
        r = self.ask(self.budi, kind="special", special_reason="wife_miscarriage", start_date="2026-11-16", end_date="2026-11-17")
        self.assertEqual(r.status_code, 201, r.data)

    def test_menstrual_leave_is_for_women_and_two_days_a_month(self):
        Employee.objects.filter(pk=self.citra.pk).update(gender="P")
        self.as_(self.citra)
        self.assertIn(rules.MENSTRUAL, [x["value"] for x in self.client.get(base.MINE).data["special_reasons"]])
        self.as_(self.budi)
        self.assertNotIn(rules.MENSTRUAL, [x["value"] for x in self.client.get(base.MINE).data["special_reasons"]])
        r = self.ask(self.budi, kind="special", special_reason=rules.MENSTRUAL, start_date="2026-11-02", end_date="2026-11-02")
        self.assertEqual(r.status_code, 400)
        self.assertIn("perempuan", r.data["message"])
        r = self.ask(self.citra, kind="special", special_reason=rules.MENSTRUAL, start_date="2026-11-02", end_date="2026-11-02")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.ask(self.citra, kind="special", special_reason=rules.MENSTRUAL, start_date="2026-11-04", end_date="2026-11-05")
        self.assertEqual(r.status_code, 400)                             # 1 + 2 > 2 days this month
        self.as_("hr")
        self.client.patch(SETTINGS, {"menstrual_leave": False}, format="json")
        self.as_(self.citra)
        self.assertNotIn(rules.MENSTRUAL, [x["value"] for x in self.client.get(base.MINE).data["special_reasons"]])

    def test_settings_api_and_law_check_rows(self):
        self.as_("hr")
        self.assertEqual(self.client.get(SETTINGS).data["settings"],
                         {"collective_leave_reduces_annual": False, "paternity_extra_days": 3, "menstrual_leave": True})
        self.assertEqual(self.client.patch(SETTINGS, {"paternity_extra_days": 4}, format="json").status_code, 400)
        rows = {r["key"]: r for r in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual([rows[k]["status"] for k in ("collective_leave", "paternity", "menstrual")], ["ok", "ok", "ok"])
        self.assertNotIn("(PP 35/2021)", rows["overtime"]["law"])
        self.client.patch(SETTINGS, {"collective_leave_reduces_annual": True, "menstrual_leave": False}, format="json")
        rows = {r["key"]: r for r in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual((rows["collective_leave"]["status"], rows["menstrual"]["status"]), ("differs", "differs"))
        self.assertEqual(rows["collective_leave"]["changed"], "Diubah oleh Anthony, 28 Okt 2026")

    def test_workers_cannot_change_leave_settings(self):
        self.as_(self.budi)
        self.assertEqual(self.client.patch(SETTINGS, {"menstrual_leave": False}, format="json").status_code, 403)


for _name in [n for n in dir(base.LeaveApiTests) if n.startswith("test_")]:
    setattr(LeaveUu27Tests, _name, None)
