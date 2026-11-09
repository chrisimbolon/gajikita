"""
G12f.1a (9 Nov 2026) — several fingerprint machines per company, through the API and the database.

DKCB: the plant machine is the main machine (IDs on the employee); the office machine is "Mesin
Kantor" with Dept. labels "Staf, Manager". 12 = Herianto on the plant and Tari in the office;
Dila is on both machines (plant 14, office 2). Names are anonymised.
"""
import io
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent, EmployeeMachineId, FingerprintMachine
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
MACHINES = "/api/hr/fingerprint/machines/"
IMPORT = "/api/hr/attendance/fingerprint/import/"
DELETE = "/api/hr/attendance/fingerprint/delete/"
PLANT_DAT = (b"    12\t2026-10-01 07:55:00\t1\t0\t1\t0\n"
             b"    12\t2026-10-01 17:01:00\t1\t1\t1\t0\n"
             b"    14\t2026-10-02 07:48:00\t1\t0\t1\t0\n")
OFFICE_DAT = (b"    12\t2026-10-01 07:56:00\t1\t0\t1\t0\n"
              b"    12\t2026-10-01 12:02:00\t1\t1\t1\t0\n"
              b"     2\t2026-10-02 17:04:00\t1\t1\t1\t0\n"
              b"    15\t2026-10-02 08:00:00\t1\t0\t1\t0\n")
DAYS = [26, 27, 28, 29, 30] + list(range(1, 26))


def combined_xlsx():
    """Anthony's "ASR Edit": both machines in one sheet, told apart by Dept. (1 Okt = column F, 2 Okt = G)."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "ASR Edit"
    ws["A1"], ws["A3"], ws["C3"] = "Attendance Record Report", "Att. Time", "2026-09-26 ~ 2026-10-25"
    for i, d in enumerate(DAYS):
        ws.cell(row=4, column=1 + i, value=d)
    blocks = [("12", "HERIANTO", "DKCB", {6: "07:5517:01"}), ("14", "Dila", "DKCB", {7: "07:48"}),
              ("12", "Tari", "Staf", {6: "07:5612:02"}), ("2", "Dila", "Staf", {7: "17:04"}),
              ("15", "Kamarol", "Staf", {7: "08:00"})]
    r = 6
    for fid, name, dept, cells in blocks:
        ws.cell(row=r, column=1, value="ID:"), ws.cell(row=r, column=3, value=fid)
        ws.cell(row=r, column=9, value="Name:"), ws.cell(row=r, column=11, value=name)
        ws.cell(row=r, column=19, value="Dept.:"), ws.cell(row=r, column=21, value=dept)
        for col, text in cells.items():
            ws.cell(row=r + 1, column=col, value=text)
        r += 3
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class MachineBase(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     working_days="123456")
        mk = lambda no, name, fp: Employee.objects.create(
            organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6), fingerprint_id=fp,
            default_shift=shift, base_rate=Decimal("4000000"))
        self.herianto, self.dila, self.tari = mk("DK20", "Herianto", "12"), mk("DK16", "Dila", "14"), mk("DK30", "Tari", "")
        self.kantor = FingerprintMachine.objects.create(organization=self.org, name="Mesin Kantor",
                                                        dept_labels="Staf, Manager")
        EmployeeMachineId.objects.create(organization=self.org, employee=self.tari, machine=self.kantor,
                                         fingerprint_id="12")
        EmployeeMachineId.objects.create(organization=self.org, employee=self.dila, machine=self.kantor,
                                         fingerprint_id="2")

    def upload(self, data, name, machine=None, commit="0"):
        body = {"file": SimpleUploadedFile(name, data), "commit": commit}
        if machine is not None:
            body["machine"] = machine
        return self.client.post(IMPORT, body, format="multipart")

    def taps(self, emp):
        return [(e.occurred_at.astimezone(WIB).strftime("%d %H:%M"), e.machine_id)
                for e in ClockEvent.objects.filter(employee=emp).order_by("occurred_at")]


class MachineApiTests(MachineBase):
    def test_list_shows_the_main_machine_and_the_others(self):
        d = self.client.get(MACHINES).data
        self.assertEqual((d["main"]["name"], d["main"]["employees"]), ("Mesin utama", 2))
        self.assertEqual([(m["name"], m["dept_labels"], m["employees"], m["taps"]) for m in d["machines"]],
                         [("Mesin Kantor", "Staf, Manager", 2, 0)])

    def test_add_rename_and_audit(self):
        resp = self.client.post(MACHINES, {"name": "  Mesin   Gudang ", "dept_labels": "gudang; Gudang"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        m = FingerprintMachine.objects.get(pk=resp.data["id"])
        self.assertEqual((m.name, m.dept_labels), ("Mesin Gudang", "gudang"))
        resp = self.client.patch(f"{MACHINES}{m.pk}/", {"name": "Mesin Silo"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertCountEqual(AuditEntry.objects.filter(target_id=str(m.pk)).values_list("action", flat=True),
                              ["attendance.machine_create", "attendance.machine_update"])

    def test_names_and_dept_labels_are_checked(self):
        for body, field in [({"name": "mesin utama"}, "name"), ({"name": "mesin kantor"}, "name"),
                            ({"name": "Mesin Lain", "dept_labels": "Manager"}, "dept_labels")]:
            resp = self.client.post(MACHINES, body, format="json")
            self.assertEqual(resp.status_code, 400, body)
            self.assertIn(field, resp.data)
        self.client.patch(f"{MACHINES}{self.kantor.pk}/", {"is_active": False}, format="json")
        resp = self.client.post(MACHINES, {"name": "Mesin Baru", "dept_labels": "Manager"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)          # an inactive machine claims no Dept.

    def test_a_machine_in_use_is_turned_off_not_deleted(self):
        resp = self.client.delete(f"{MACHINES}{self.kantor.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("2 ID karyawan", resp.data["message"])
        spare = FingerprintMachine.objects.create(organization=self.org, name="Cadangan")
        self.assertEqual(self.client.delete(f"{MACHINES}{spare.pk}/").status_code, 200)
        self.assertFalse(FingerprintMachine.objects.filter(pk=spare.pk).exists())
        self.assertTrue(AuditEntry.objects.filter(action="attendance.machine_delete").exists())

    def test_another_company_cannot_see_or_touch_the_machines(self):
        other = Organization.objects.create(name="PT Lain")
        theirs = FingerprintMachine.objects.create(organization=other, name="Mesin Kantor")
        self.assertEqual(self.client.patch(f"{MACHINES}{theirs.pk}/", {"name": "X"}, format="json").status_code, 404)
        self.assertEqual(len(self.client.get(MACHINES).data["machines"]), 1)
        url = f"/api/hr/employees/{self.herianto.pk}/machine-ids/"
        resp = self.client.put(url, {"machine_ids": [{"machine": str(theirs.pk), "fingerprint_id": "9"}]}, format="json")
        self.assertEqual(resp.status_code, 400)


class EmployeeMachineIdTests(MachineBase):
    def url(self, emp):
        return f"/api/hr/employees/{emp.pk}/machine-ids/"

    def test_get_and_replace_ids(self):
        d = self.client.get(self.url(self.dila)).data
        self.assertEqual((d["main"]["fingerprint_id"], d["machine_ids"][0]["fingerprint_id"]), ("14", "2"))
        resp = self.client.put(self.url(self.dila), {"machine_ids": [{"machine": str(self.kantor.pk),
                                                                      "fingerprint_id": "0003"}]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["machine_ids"][0]["fingerprint_id"], "3")      # leading zeros dropped
        entry = AuditEntry.objects.get(action="employees.machine_ids")
        self.assertEqual((entry.data["before"], entry.data["after"]), ({"Mesin Kantor": "2"}, {"Mesin Kantor": "3"}))

    def test_an_empty_id_removes_it(self):
        resp = self.client.put(self.url(self.dila), {"machine_ids": [{"machine": str(self.kantor.pk),
                                                                      "fingerprint_id": ""}]}, format="json")
        self.assertEqual((resp.status_code, resp.data["machine_ids"]), (200, []))

    def test_same_id_on_the_same_machine_is_refused_with_the_name(self):
        resp = self.client.put(self.url(self.herianto), {"machine_ids": [{"machine": str(self.kantor.pk),
                                                                          "fingerprint_id": "12"}]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ID 12 di Mesin Kantor sudah dipakai Tari (DK30)", resp.data["message"])

    def test_the_employee_screen_shows_the_ids(self):
        rows = {e["full_name"]: e for e in self.client.get("/api/hr/employees/").data["employees"]}
        self.assertEqual(rows["Dila"]["machine_ids"],
                         [{"machine": str(self.kantor.pk), "machine_name": "Mesin Kantor", "fingerprint_id": "2"}])
        self.assertEqual(rows["Herianto"]["machine_ids"], [])


class MachineImportTests(MachineBase):
    def test_the_same_id_goes_to_the_person_on_the_chosen_machine(self):
        resp = self.upload(OFFICE_DAT, "kantor.dat", machine=str(self.kantor.pk), commit="1")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["machine"], {"mode": "one", "id": str(self.kantor.pk), "name": "Mesin Kantor"})
        self.assertEqual(self.taps(self.tari), [("01 07:56", self.kantor.pk), ("01 12:02", self.kantor.pk)])
        self.assertEqual(self.taps(self.herianto), [])
        self.assertEqual([(u["machine"], u["machine_id"]) for u in resp.data["unknown"]], [("Mesin Kantor", "15")])

        resp = self.upload(PLANT_DAT, "pabrik.dat", commit="1")                  # no choice = main machine
        self.assertEqual(resp.data["machine"]["mode"], "main")
        self.assertEqual(self.taps(self.herianto), [("01 07:55", None), ("01 17:01", None)])

    def test_auto_reads_both_machines_from_anthony_workbook(self):
        resp = self.upload(combined_xlsx(), "1026 Absensi DKCB.xlsx", machine="auto", commit="1")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual([(d["dept"], d["machine"]) for d in resp.data["depts"]],
                         [("DKCB", "Mesin utama"), ("Staf", "Mesin Kantor")])
        self.assertEqual(self.taps(self.herianto), [("01 07:55", None), ("01 17:01", None)])
        self.assertEqual(self.taps(self.tari), [("01 07:56", self.kantor.pk), ("01 12:02", self.kantor.pk)])
        # Dila: in on the plant, out in the office -> one day with both taps
        day = AttendanceDay.objects.get(employee=self.dila)
        self.assertEqual(day.date, date(2026, 10, 2))
        self.assertEqual([(e.kind, e.machine_id) for e in day.events.order_by("occurred_at")],
                         [("in", None), ("out", self.kantor.pk)])
        dila = next(p for p in resp.data["people"] if p["employee"]["full_name"] == "Dila")
        self.assertEqual(dila["machines"], [{"machine": "Mesin utama", "machine_id": "14"},
                                            {"machine": "Mesin Kantor", "machine_id": "2"}])
        self.assertEqual([(u["machine"], u["machine_id"], u["name"]) for u in resp.data["unknown"]],
                         [("Mesin Kantor", "15", "Kamarol")])

    def test_auto_needs_a_file_with_dept(self):
        resp = self.upload(PLANT_DAT, "pabrik.dat", machine="auto")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Dept.", resp.data["message"])

    def test_a_wrong_or_inactive_machine_is_refused(self):
        self.assertEqual(self.upload(PLANT_DAT, "p.dat", machine="not-a-machine").status_code, 400)
        self.kantor.is_active = False
        self.kantor.save()
        resp = self.upload(OFFICE_DAT, "k.dat", machine=str(self.kantor.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("nonaktif", resp.data["message"])

    def test_people_with_only_a_machine_id_are_linked(self):
        d = self.upload(PLANT_DAT, "pabrik.dat").data
        self.assertNotIn("DK30", [n["employee_no"] for n in d["not_linked"]])


class MachineDeleteTests(MachineBase):
    def test_deleting_one_machine_keeps_the_other_machines_taps(self):
        self.upload(combined_xlsx(), "1026.xlsx", machine="auto", commit="1")
        body = {"start": "2026-10-01", "end": "2026-10-02", "machine": str(self.kantor.pk)}
        preview = self.client.post(DELETE, body, format="json").data
        self.assertEqual((preview["machine"], preview["totals"]["taps"]), ("Mesin Kantor", 3))
        resp = self.client.post(DELETE, {**body, "commit": True, "reason": "Salah file kantor"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.taps(self.tari), [])
        self.assertEqual(self.taps(self.herianto), [("01 07:55", None), ("01 17:01", None)])
        self.assertEqual(self.taps(self.dila), [("02 07:48", None)])              # the plant half of her day stays
        self.assertIn("Mesin Kantor", AuditEntry.objects.get(action="attendance.fingerprint_delete").summary)

    def test_main_only_and_all_machines(self):
        self.upload(combined_xlsx(), "1026.xlsx", machine="auto", commit="1")
        main = self.client.post(DELETE, {"start": "2026-10-01", "end": "2026-10-02", "machine": "main"}, format="json")
        self.assertEqual(main.data["totals"]["taps"], 3)
        every = self.client.post(DELETE, {"start": "2026-10-01", "end": "2026-10-02"}, format="json")
        self.assertEqual((every.data["machine"], every.data["totals"]["taps"]), ("Semua mesin", 6))
