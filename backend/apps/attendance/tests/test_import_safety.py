"""
G12f.2 (9 Nov 2026) — the import protects HR from the wrong machine and the wrong person.

The case it was built for (Chris's screen, 9 Nov): the plant machine's file imported "Dari Mesin
Kantor". Plant ID 2 (Feny) matched office ID 2 (Apriyani "Dila"), so Feny's days would have been
saved on Apriyani. Now: the names are checked, a better machine is suggested, Simpan needs a
"Saya sudah cek" when names disagree, and unknown IDs come with a proposed employee and can be
linked from the preview. Names are anonymised where they are not part of the scenario.
"""
import io
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.attendance.models import ClockEvent, EmployeeMachineId, FingerprintMachine
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
IMPORT = "/api/hr/attendance/fingerprint/import/"
LINK = "/api/hr/attendance/fingerprint/link/"
DAYS = [26, 27, 28, 29, 30] + list(range(1, 26))


def plant_xlsx(blocks):
    """The plant machine's report: [(id, name, {column: taps})], Dept. DKCB. Column 6 = 1 Okt, 7 = 2 Okt."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Att.log report"
    ws["A1"], ws["A3"], ws["C3"] = "Attendance Record Report", "Att. Time", "2026-09-26 ~ 2026-10-25"
    for i, d in enumerate(DAYS):
        ws.cell(row=4, column=1 + i, value=d)
    r = 5
    for fid, name, cells in blocks:
        ws.cell(row=r, column=1, value="ID:"), ws.cell(row=r, column=3, value=fid)
        ws.cell(row=r, column=9, value="Name:"), ws.cell(row=r, column=11, value=name)
        ws.cell(row=r, column=19, value="Dept.:"), ws.cell(row=r, column=21, value="DKCB")
        for col, text in cells.items():
            ws.cell(row=r + 1, column=col, value=text)
        r += 2
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


PLANT = [("12", "HERIANTO", {6: "07:5517:01"}), ("2", "Feny", {6: "07:4917:02", 7: "07:5117:05"}),
         ("14", "Dila", {7: "07:48"}), ("7", "AMSAR", {6: "07:3017:00"}), ("1", "Risman", {6: "06:5519:01"})]


class SafetyBase(APITestCase):
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
        self.herianto, self.feny = mk("DK22", "Herianto", "12"), mk("DK03", "Feny Saputra", "2")
        self.apriyani, self.tari = mk("DK16", "Apriyani Fadhilah", "14"), mk("DK30", "Mentari Rezeki", "")
        self.amsar = mk("DK14", "Amsar Sormin", "")
        self.kantor = FingerprintMachine.objects.create(organization=self.org, name="Mesin Kantor",
                                                        dept_labels="Staf, Manager")
        EmployeeMachineId.objects.create(organization=self.org, employee=self.apriyani, machine=self.kantor,
                                         fingerprint_id="2")
        EmployeeMachineId.objects.create(organization=self.org, employee=self.tari, machine=self.kantor,
                                         fingerprint_id="12")

    def upload(self, machine, commit="0", confirm=None, data=None):
        body = {"file": SimpleUploadedFile("Absen DKCB Admin.xlsx", data or plant_xlsx(PLANT)), "commit": commit,
                "machine": machine}
        if confirm is not None:
            body["confirm_names"] = confirm
        return self.client.post(IMPORT, body, format="multipart")


class WrongMachineTests(SafetyBase):
    def test_plant_file_read_on_the_office_machine_is_caught(self):
        d = self.upload(str(self.kantor.pk)).data
        self.assertEqual(d["suggest_machine"]["name"], "Mesin utama")
        self.assertEqual(d["suggest_machine"]["value"], "main")
        self.assertEqual(d["totals"]["name_mismatch"], 2)
        bad = [(p["employee"]["full_name"], p["mismatch_name"]) for p in d["people"] if p["name_check"] == "bad"]
        self.assertCountEqual(bad, [("Apriyani Fadhilah", "Feny"), ("Mentari Rezeki", "HERIANTO")])
        self.assertEqual(d["people"][0]["name_check"], "bad")                  # the problems come first

    def test_the_right_machine_has_no_warning(self):
        d = self.upload("main").data
        self.assertIsNone(d["suggest_machine"])
        self.assertEqual(d["totals"]["name_mismatch"], 0)
        self.assertEqual({p["employee"]["full_name"]: p["name_check"] for p in d["people"]},
                         {"Herianto": "ok", "Feny Saputra": "ok", "Apriyani Fadhilah": "ok"})
        self.assertEqual(d["file_period"], {"start": "2026-10-01", "end": "2026-10-02", "days": 2})

    def test_saving_with_wrong_names_needs_a_confirmation(self):
        resp = self.upload(str(self.kantor.pk), commit="1")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "names_unconfirmed")
        self.assertEqual(ClockEvent.objects.count(), 0)                         # nothing saved
        resp = self.upload(str(self.kantor.pk), commit="1", confirm="1")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertGreater(resp.data["applied"]["events"], 0)

    def test_a_file_without_names_has_nothing_to_check(self):
        dat = b"    12\t2026-10-01 07:55:00\t1\t0\t1\t0\n    12\t2026-10-01 17:01:00\t1\t1\t1\t0\n"
        resp = self.client.post(IMPORT, {"file": SimpleUploadedFile("attlog.dat", dat), "commit": "1"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.data["people"][0]["name_check"], resp.data["suggest_machine"]), ("none", None))


class LinkTests(SafetyBase):
    def test_unknown_ids_come_with_a_proposed_employee(self):
        d = self.upload("main").data
        unknown = {u["machine_id"]: u for u in d["unknown"]}
        self.assertEqual(unknown["7"]["suggest"]["full_name"], "Amsar Sormin")
        self.assertEqual(unknown["7"]["link_machine"], "main")
        self.assertIsNone(unknown["1"]["suggest"])                              # nobody looks like Risman

    def test_no_suggestions_while_the_machine_looks_wrong(self):
        """G12f.2b: linking under the wrong machine would store plant numbers as office IDs."""
        d = self.upload(str(self.kantor.pk)).data
        self.assertIsNotNone(d["suggest_machine"])
        self.assertEqual([u["suggest"] for u in d["unknown"]], [None] * len(d["unknown"]))

    def test_link_from_the_preview_then_the_id_is_known(self):
        resp = self.client.post(LINK, {"links": [{"machine": "main", "fingerprint_id": "007",
                                                  "employee": str(self.amsar.pk)}]}, format="json")
        self.assertEqual((resp.status_code, resp.data["linked"]), (200, 1))
        self.amsar.refresh_from_db()
        self.assertEqual(self.amsar.fingerprint_id, "7")
        self.assertIn("ID 7 di Mesin utama dihubungkan ke Amsar Sormin",
                      AuditEntry.objects.get(action="employees.machine_link").summary)
        self.assertNotIn("7", [u["machine_id"] for u in self.upload("main").data["unknown"]])

    def test_link_on_another_machine(self):
        kamarol = Employee.objects.create(organization=self.org, employee_no="DK40", full_name="M. Kamarol",
                                          join_date=date(2025, 1, 6), base_rate=Decimal("6000000"))
        resp = self.client.post(LINK, {"links": [{"machine": str(self.kantor.pk), "fingerprint_id": "15",
                                                  "employee": str(kamarol.pk)}]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(EmployeeMachineId.objects.filter(machine=self.kantor, employee=kamarol, fingerprint_id="15").exists())

    def test_nothing_is_overwritten_and_one_problem_stops_all(self):
        other = Organization.objects.create(name="PT Lain")
        stranger = Employee.objects.create(organization=other, employee_no="X1", full_name="Orang Lain",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("1"))
        resp = self.client.post(LINK, {"links": [
            {"machine": "main", "fingerprint_id": "7", "employee": str(self.amsar.pk)},          # fine on its own
            {"machine": "main", "fingerprint_id": "12", "employee": str(self.tari.pk)},          # 12 is Herianto's
            {"machine": "main", "fingerprint_id": "30", "employee": str(self.feny.pk)},          # Feny already has 2
            {"machine": str(self.kantor.pk), "fingerprint_id": "2", "employee": str(self.amsar.pk)},  # Apriyani's
            {"machine": "main", "fingerprint_id": "40", "employee": str(stranger.pk)},           # another company
        ]}, format="json")
        self.assertEqual(resp.status_code, 400)
        text = resp.data["message"]
        for part in ("ID 12 di Mesin utama sudah dipakai Herianto (DK22)", "Feny Saputra sudah punya ID 2",
                     "ID 2 di Mesin Kantor sudah dipakai Apriyani Fadhilah (DK16)", "Baris 5: karyawan tidak ditemukan"):
            self.assertIn(part, text)
        self.amsar.refresh_from_db()
        self.assertEqual(self.amsar.fingerprint_id, "")                        # the good line was not saved either

    def test_the_same_link_twice_changes_nothing(self):
        resp = self.client.post(LINK, {"links": [{"machine": "main", "fingerprint_id": "12",
                                                  "employee": str(self.herianto.pk)}]}, format="json")
        self.assertEqual((resp.status_code, resp.data["linked"]), (200, 0))
        self.assertFalse(AuditEntry.objects.filter(action="employees.machine_link").exists())
