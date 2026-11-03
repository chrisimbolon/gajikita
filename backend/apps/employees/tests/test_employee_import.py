"""
G9 (1 Nov 2026) — importing employees from the GajiKita template: preview first, then save.
"""
import io
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.importer import build_template
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift, Site

URL = "/api/hr/employees/import/"


def template_with(rows):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(build_template()))
    ws = wb["Data Karyawan"]
    for r, row in enumerate(rows, start=5):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def row(no, name, join="01/01/2025", base="3000000", **kw):
    cells = [no, name, kw.get("position"), None, None, "TK/0", join, None, None, "PKWTT (tetap)", "Bulanan", base,
             None, "Ya", "Ya", None, None, kw.get("bank"), kw.get("account"), None, None, kw.get("fp"), kw.get("shift"),
             kw.get("site"), kw.get("mandor")]
    return cells


class EmployeeImportTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time="08:00", end_time="17:00")
        self.site = Site.objects.create(organization=self.org, name="Batching Plant")
        Employee.objects.create(organization=self.org, employee_no="DK-001", full_name="Andi Wijaya",
                                join_date=date(2023, 1, 26), base_rate=Decimal("7500000"), fingerprint_id="26")
        self.data = template_with([
            row("DK-001", "Andi Wijaya", join="26/01/2023", base="7.500.000", position="Kepala Plant"),
            row("DK-002", "Budi Santoso", join="15/07/2018", base="2800000", fp="0015", shift="Pagi",
                site="Batching Plant", mandor="DK-001", bank="BCA", account="0123456789", position="Driver TM"),
            row("DK-003", "Citra", join=None, shift="Malam"),
            row("DK-004", "Dedi", fp="26"),
        ])

    def post(self, commit):
        return self.client.post(URL, {"file": SimpleUploadedFile("karyawan.xlsx", self.data), "commit": commit},
                                format="multipart")

    def test_preview_saves_nothing_and_explains_every_row(self):
        resp = self.post("0")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["counts"], {"create": 1, "update": 1, "same": 0, "error": 2, "skip": 3})
        self.assertEqual(resp.data["columns_missing"], [])
        rows = {r["employee_no"]: r for r in resp.data["rows"] if r["employee_no"]}
        self.assertEqual(rows["DK-001"]["changes"], [{"field": "Jabatan", "old": "-", "new": "Kepala Plant"}])
        self.assertIn("Wajib diisi untuk karyawan baru: Tanggal Masuk", rows["DK-003"]["errors"])
        self.assertIn("Shift \"Malam\" belum ada; dikosongkan. Pilih di \"Isi yang belum dikenali\" di atas, "
                      "atau buat dulu di menu Shift.", rows["DK-003"]["warnings"])
        self.assertEqual(rows["DK-004"]["errors"], ["ID fingerprint 26 sudah dipakai karyawan DK-001"])
        self.assertEqual(Employee.objects.count(), 1)

    def test_commit_saves_good_rows_links_shift_site_mandor_and_is_repeatable(self):
        resp = self.post("1")
        self.assertEqual(resp.data["applied"], {"created": 1, "updated": 1})
        budi = Employee.objects.get(employee_no="DK-002")
        self.assertEqual((budi.default_shift, budi.default_site, budi.mandor.employee_no, budi.fingerprint_id,
                          budi.bank_account_no, budi.base_rate, budi.position),
                         (self.shift, self.site, "DK-001", "15", "0123456789", Decimal("2800000.00"), "Driver TM"))
        self.assertEqual(Employee.objects.get(employee_no="DK-001").position, "Kepala Plant")
        self.assertFalse(Employee.objects.filter(employee_no__in=["DK-003", "DK-004"]).exists())
        self.assertTrue(AuditEntry.objects.filter(action="employees.import").exists())
        again = self.post("1")
        self.assertEqual((again.data["applied"], again.data["counts"]["same"]), ({"created": 0, "updated": 0}, 2))

    def test_template_download_and_bad_files(self):
        resp = self.client.get(f"{URL}template/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        bad = self.client.post(URL, {"file": SimpleUploadedFile("lama.xls", b"\xd0\xcf\x11\xe0"), "commit": "0"},
                               format="multipart")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Save As", bad.data["message"])

    def test_workers_cannot_import(self):
        self.client.force_authenticate(CustomUser.objects.create_user(email="w@b.id", password="pass12345!",
                                                                      full_name="W", role="employee"))
        self.assertEqual(self.client.get(f"{URL}template/").status_code, 403)
