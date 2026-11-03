"""
G9d (3 Nov 2026) — importing a company's OWN employee file: map the columns and words once in the
preview, save, and the next import of that file needs no choices at all.
"""
import io
import json
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.employees.models import Employee, EmployeeImportProfile
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Site

URL = "/api/hr/employees/import/"


def own_file(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll Okt"
    ws.append(["PT Beton Bintan"])
    ws.append([])
    ws.append(["NIP", "NAMA PEGAWAI", "TGL MASUK", "GAPOK", "STATUS", "PENEMPATAN", "KODE UNIT"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


DATA = own_file([["B-01", "Andi", "01/02/2023", "4.000.000", "Tetap", "BP Uban", "U1"],
                 ["B-02", "Budi", "15/07/2018", "3.500.000", "Outsourcing", "BP Uban", "U1"],
                 ["B-03", "Citra", "tgl salah", "3.000.000", "Outsourcing", "BP Uban", "U2"]])
MAPPING = {"namapegawai": "full_name", "status": "employment_type", "kodeunit": "-"}
VALUES = {"employment_type": {"outsourcing": "PKWT (kontrak)"}, "site": {"bpuban": "Batching Plant"}}


class ImportOwnFileTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.site = Site.objects.create(organization=self.org, name="Batching Plant")

    def post(self, data=DATA, **extra):
        body = {"file": SimpleUploadedFile("payroll_okt.xlsx", data)}
        for k, v in extra.items():
            body[k] = json.dumps(v) if isinstance(v, dict) else v
        return self.client.post(URL, body, format="multipart")

    def test_first_look_shows_what_to_map(self):
        d = self.post().data
        self.assertEqual((d["sheet"], d["header_row"], d["needs_mapping"]), ("Payroll Okt", 3, False))
        self.assertEqual(d["columns_missing"], ["Nama Lengkap (sesuai KTP)"])
        self.assertEqual([c["title"] for c in d["columns"] if not c["field"]],
                         ["NAMA PEGAWAI", "STATUS", "PENEMPATAN", "KODE UNIT"])
        self.assertEqual(d["columns"][0]["sample"], ["B-01", "B-02", "B-03"])

    def test_map_once_save_and_the_next_import_needs_no_choices(self):
        d = self.post(mapping={**MAPPING, "penempatan": "site"}, values=VALUES).data
        self.assertEqual(d["counts"], {"create": 2, "update": 0, "same": 0, "error": 1, "skip": 0})
        self.assertEqual([(u["raw"], u["mapped"]) for u in d["unknown_values"]],
                         [("Outsourcing", "PKWT (kontrak)"), ("BP Uban", "Batching Plant")])
        self.assertTrue(all(not r["warnings"] for r in d["rows"]))

        saved = self.post(mapping={**MAPPING, "penempatan": "site"}, values=VALUES, commit="1").data
        self.assertEqual(saved["applied"], {"created": 2, "updated": 0})
        budi = Employee.objects.get(employee_no="B-02")
        self.assertEqual((budi.employment_type, budi.default_site, budi.join_date), ("pkwt", self.site, date(2018, 7, 15)))
        profile = EmployeeImportProfile.objects.get(organization=self.org)
        self.assertEqual((profile.column_map["kodeunit"], profile.column_map["namapegawai"]), ("-", "full_name"))

        again = self.post().data                     # next month: same file, no choices sent
        self.assertTrue(again["profile_used"])
        self.assertEqual(again["counts"], {"create": 0, "update": 0, "same": 2, "error": 1, "skip": 0})
        self.assertEqual(self.post(reset="1").data["columns_missing"], ["Nama Lengkap (sesuai KTP)"])

    def test_download_only_the_rows_to_fix(self):
        from openpyxl import load_workbook
        resp = self.post(mapping=MAPPING, values=VALUES, report="1")     # Budi's "Outsourcing" mapped, so only Citra fails
        self.assertIn("Perbaiki_Data_Karyawan.xlsx", resp["Content-Disposition"])
        rows = list(load_workbook(io.BytesIO(resp.content)).active.iter_rows(values_only=True))
        self.assertEqual([(r[0], r[2]) for r in rows[1:]], [(6, "Citra")])
        self.assertIn("Tanggal Masuk", rows[1][-1])

    def test_no_employee_number_column_asks_for_one(self):
        d = self.post(own_file_no_id()).data
        self.assertTrue(d["needs_mapping"])
        self.assertEqual(d["rows"], [])
        d = self.post(own_file_no_id(), mapping={"kode": "employee_no", "pegawai": "full_name"}).data
        self.assertFalse(d["needs_mapping"])

    def test_choices_for_fields_or_places_that_do_not_exist_are_ignored(self):
        d = self.post(mapping={"namapegawai": "salary_hack"}, values={"site": {"bpuban": "Gudang Rahasia"}}).data
        self.assertEqual(d["columns_missing"], ["Nama Lengkap (sesuai KTP)"])


def own_file_no_id():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Kode", "Pegawai", "Tgl Masuk", "Gaji Pokok"])
    ws.append(["Z-1", "Zul", "01/01/2024", "3000000"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
