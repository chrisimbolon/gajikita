"""
G8b part 1 (1 Nov 2026) — payroll settings and the pay run, from real attendance and leave.

Period: October 2026 with the period starting on the 26th = 26 Sep - 25 Oct (25 working days, Mon-Sat).
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings, PayRun
from apps.sites.models import Shift, Site

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class PayRunTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        self.hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.site = Site.objects.create(organization=self.org, name="Batching Plant")
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        PayrollSettings.objects.create(
            organization=self.org, overtime_mode="flat", overtime_rounding="nearest_half",
            flat_overtime_hour=Decimal("12500"), flat_rest_day=Decimal("120000"), meal_rule="overtime_day",
            meal_allowance=Decimal("15000"), late_fine_per_minute=Decimal("500"), late_tolerance_minutes=5,
            jkk_rate=Decimal("0.0089"))

        def emp(no, name, rate, joined=date(2025, 1, 6), **kw):
            return Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=joined,
                                           default_shift=self.shift, base_rate=Decimal(rate), **kw)

        self.andi = emp("B-1", "Andi", "4000000")
        self.budi = emp("B-2", "Budi", "3000000")
        self.citra = emp("B-3", "Citra", "150000", joined=date(2026, 10, 1), pay_type="daily", bpjs_tk_enrolled=False)
        emp("B-4", "Dedi", "3000000", joined=date(2024, 1, 1), end_date=date(2026, 9, 1), status="resigned")

        start = date(2026, 9, 26)
        self.working = [start + timedelta(days=i) for i in range(30) if (start + timedelta(days=i)).isoweekday() != 7]
        assert len(self.working) == 25
        overtime = {date(2026, 10, 3): (21, 36, 276), date(2026, 10, 15): (21, 16, 256), date(2026, 10, 17): (22, 37, 337)}
        for d in self.working:
            if d in overtime:
                h, m, minutes = overtime[d]
                self.work(self.andi, d, out=(h, m), decision="approved", overtime_approved_minutes=minutes)
            elif d == date(2026, 10, 6):
                self.work(self.andi, d, inn=(8, 30))                     # 30 min late, not reviewed yet
            else:
                self.work(self.andi, d)
            if d not in (date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 20), date(2026, 10, 21)):
                self.work(self.budi, d)                                  # 7 and 8 Oct: absent
        for d in (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 6)):
            self.work(self.citra, d)
        LeaveRequest.objects.create(organization=self.org, employee=self.budi, kind="unpaid", start_date=date(2026, 10, 20),
                                    end_date=date(2026, 10, 20), days=1, status="approved")
        LeaveRequest.objects.create(organization=self.org, employee=self.budi, kind="annual", start_date=date(2026, 10, 21),
                                    end_date=date(2026, 10, 21), days=1, status="approved")

    def work(self, emp, d, inn=(7, 55), out=(17, 0), **day_kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **day_kw)
        for kind, (h, m) in (("in", inn), ("out", out)):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, site=self.site,
                                      occurred_at=at(d, h, m), received_at=at(d, h, m))
        return day

    def make_run(self, month="2026-10"):
        resp = self.client.post(RUNS, {"month": month}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["run"]

    def rows(self, run_id):
        data = self.client.get(f"{RUNS}{run_id}/").data
        return {r["employee"]["full_name"]: r for r in data["rows"]}, data

    def line(self, run_id, name):
        rows, _ = self.rows(run_id)
        return self.client.get(f"{RUNS}{run_id}/lines/{rows[name]['id']}/").data["line"]

    # ── the run ──
    def test_numbers_come_from_attendance_and_leave(self):
        run = self.make_run()
        self.assertEqual((run["name"], run["period_start"], run["period_end"], run["pay_date"], run["people"]),
                         ("Payroll Oktober 2026", "2026-09-26", "2026-10-25", "2026-11-05", 3))   # Dedi left before

        andi = self.line(run["id"], "Andi")
        a = andi["auto"]
        self.assertEqual((a["present_days"], a["absent_days"], len(a["overtime"]), a["meal_days"], a["late_minutes"],
                          a["review_days"]), (25, 0, 3, 3, 25, 1))
        # 4,000,000 + 14.5 h x 12,500 + 3 x 15,000 - 25 min x 500 - JHT 2% 80,000
        self.assertEqual(andi["net"], "4133750.00")
        self.assertIn("1 hari absensi belum ditinjau HR di periode ini.", andi["result"]["warnings"])
        self.assertTrue(any("PP 35/2021 Rp" in w for w in andi["result"]["warnings"]))

        budi = self.line(run["id"], "Budi")
        b = budi["auto"]
        self.assertEqual((b["absent_days"], b["unpaid_leave_days"], b["paid_leave_days"], b["unpaid_days"]), (2, 1, 1, 3))
        self.assertEqual(budi["net"], "2640000.00")                     # 3,000,000 - 3 x 100,000 - JHT 60,000

        citra = self.line(run["id"], "Citra")                            # daily worker, joined 1 Oct
        self.assertEqual((citra["auto"]["present_days"], citra["auto"]["outside_days"]), (5, 5))
        self.assertEqual(citra["net"], "750000.00")                     # 5 days x 150,000, no BPJS

    def test_corrections_items_and_recurring_items_carry_to_the_next_run(self):
        run = self.make_run()
        rows, _ = self.rows(run["id"])
        url = f"{RUNS}{run['id']}/lines/{rows['Andi']['id']}/"
        resp = self.client.patch(url, {"override": {"meal_days": 5}, "note": "Laporan mandor"}, format="json")
        self.assertEqual(resp.data["line"]["net"], "4163750.00")          # +2 meal days
        resp = self.client.post(f"{url}items/", {"kind": "earning", "label": "Insentif BPJS Kesehatan", "amount": "35000",
                                                 "recurring": True}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.client.post(f"{url}items/", {"kind": "deduction", "label": "Kasbon", "amount": "500000"}, format="json")
        self.assertEqual(resp.data["line"]["net"], "3698750.00")
        kasbon = next(i for i in resp.data["line"]["items"] if i["label"] == "Kasbon")
        resp = self.client.delete(f"{RUNS}{run['id']}/items/{kasbon['id']}/")
        self.assertEqual(resp.data["line"]["net"], "4198750.00")
        self.assertEqual(AuditEntry.objects.filter(action__startswith="payroll.").count(), 5)  # create, line, 2 adds, delete

        self.client.post(f"{RUNS}{run['id']}/lock/", {"action": "lock"}, format="json")
        nov = self.make_run("2026-11")
        andi_nov = self.line(nov["id"], "Andi")
        self.assertEqual([(i["label"], i["amount"], i["recurring"]) for i in andi_nov["items"]],
                         [("Insentif BPJS Kesehatan", "35000.00", True)])

    def test_locking_locks_attendance_and_blocks_changes(self):
        run = self.make_run()
        resp = self.client.post(f"{RUNS}{run['id']}/lock/", {"action": "lock"}, format="json")
        self.assertEqual(resp.data["run"]["status"], "locked")
        self.assertFalse(AttendanceDay.objects.filter(employee=self.andi, is_locked=False).exists())
        rows, _ = self.rows(run["id"])
        self.assertEqual(self.client.patch(f"{RUNS}{run['id']}/lines/{rows['Andi']['id']}/",
                                           {"override": {"meal_days": 1}}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{RUNS}{run['id']}/recalculate/").status_code, 400)
        late_day = AttendanceDay.objects.get(employee=self.andi, date=date(2026, 10, 6))
        self.assertEqual(self.client.post(f"/api/hr/attendance/days/{late_day.id}/decide/",
                                          {"action": "approve"}, format="json").status_code, 400)

        self.assertEqual(self.client.post(f"{RUNS}{run['id']}/lock/", {"action": "reopen"}, format="json").status_code, 400)
        resp = self.client.post(f"{RUNS}{run['id']}/lock/", {"action": "reopen", "note": "Salah hitung lembur"}, format="json")
        self.assertEqual(resp.data["run"]["status"], "draft")
        self.assertFalse(AttendanceDay.objects.filter(employee=self.andi, is_locked=True).exists())

    def test_one_run_per_period_and_drafts_can_be_deleted(self):
        run = self.make_run()
        resp = self.client.post(RUNS, {"month": "2026-10"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("sudah ada", resp.data["message"])
        self.assertEqual(self.client.delete(f"{RUNS}{run['id']}/").status_code, 200)
        self.assertFalse(PayRun.objects.exists())

    def test_recalculate_picks_up_hr_decisions(self):
        run = self.make_run()
        late_day = AttendanceDay.objects.get(employee=self.andi, date=date(2026, 10, 6))
        self.client.post(f"/api/hr/attendance/days/{late_day.id}/decide/", {"action": "approve", "waive_late": True},
                         format="json")
        self.client.post(f"{RUNS}{run['id']}/recalculate/")
        andi = self.line(run["id"], "Andi")
        self.assertEqual((andi["auto"]["late_minutes"], andi["auto"]["review_days"], andi["net"]), (0, 0, "4146250.00"))

    # ── settings ──
    def test_settings_api(self):
        url = "/api/hr/payroll/settings/"
        self.assertEqual(self.client.get(url).data["settings"]["overtime_mode"], "flat")
        resp = self.client.patch(url, {"overtime_mode": "flat", "flat_overtime_hour": "0"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(url, {"overtime_mode": "pp35", "minimum_wage": "4583221"}, format="json")
        self.assertEqual((resp.status_code, resp.data["settings"]["overtime_mode"]), (200, "pp35"))
        self.assertTrue(AuditEntry.objects.filter(action="payroll.settings").exists())

        run = self.make_run()
        rows, _ = self.rows(run["id"])
        resp = self.client.patch(f"{RUNS}{run['id']}/lines/{rows['Andi']['id']}/", {"override": {"overtime_hours": 3}},
                                 format="json")
        self.assertEqual(resp.status_code, 400)                          # PP 35 needs the daily detail
        andi = self.line(run["id"], "Andi")
        self.assertTrue(any("UMK" in w for w in andi["result"]["warnings"]))

    def test_workers_cannot_open_payroll(self):
        user = CustomUser.objects.create_user(email="w@beton.id", password="pass12345!", full_name="W", role="employee")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(RUNS).status_code, 403)
        self.assertEqual(self.client.get("/api/hr/payroll/settings/").status_code, 403)
