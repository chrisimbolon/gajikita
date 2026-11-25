"""
G16-2 (21 Nov 2026) — saldo awal PPh 21, the yearly calculation (Pasal 17), masa pajak, PTKP sudah dicek.
Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase

from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.payroll import pph21 as P
from apps.payroll import pph21_year as Y
from apps.payroll.models import Pph21Opening
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/payroll/pph21-opening/"


class PureTests(SimpleTestCase):
    def test_amounts_as_excel_writes_them(self):
        self.assertEqual([Y.parse_amount(x) for x in ("Rp 1.234.567", "1,234,567", "1234567", "", "-", "1234567,00")],
                         [D("1234567"), D("1234567"), D("1234567"), D("0"), D("0"), D("1234567")])
        self.assertIsNone(Y.parse_amount("satu juta"))

    def test_csv_semicolon_and_comma(self):
        rows, problems = Y.parse_opening_csv("no_karyawan;nama;bulan;bruto;pph21;iuran_jht_jp\nB-1;Andi;9;36.000.000;0;720.000\n")
        self.assertEqual(problems, [])
        self.assertEqual((rows[0]["employee_no"], rows[0]["months"], rows[0]["bruto"], rows[0]["iuran"]),
                         ("B-1", 9, D("36000000"), D("720000")))
        rows, _ = Y.parse_opening_csv("No Karyawan,Bulan,PPh 21\nB-2,13,abc\n")
        self.assertEqual(rows[0]["errors"], ["bulan harus 0 sampai 12", "pph21 bukan angka rupiah"])
        self.assertTrue(Y.parse_opening_csv("nama;bruto\nAndi;1\n")[1])          # no no_karyawan / bulan column

    def test_masa_pajak(self):
        self.assertEqual(Y.tax_month(date(2026, 11, 25), date(2026, 12, 5), Y.PAID), (2026, 12))
        self.assertEqual(Y.tax_month(date(2026, 11, 25), date(2026, 12, 5), Y.PERIOD_END), (2026, 11))
        self.assertEqual(Y.tax_month(date(2026, 12, 25), date(2027, 1, 5), Y.PAID), (2027, 1))

    def test_annual_gross_up_settles_itself(self):
        a, t = Y.annual_gross_up(D("121428000"), 12, D("0"), "K/2", D("1650000"))
        self.assertEqual((t, a.due), (D("785650"), D("785650")))                 # the allowance pays exactly what is due
        for bruto in range(60_000_000, 900_000_000, 1_234_567):                  # thousands rounding can bounce:
            a, t = Y.annual_gross_up(D(bruto), 12, D("0"), "K/2", D("1650000"))  # the allowance still covers the tax
            if a.due > 0:
                self.assertTrue(D("0") <= t - a.due < 1000, bruto)
            else:
                self.assertEqual(t, D("0"))                                      # a refund is not an allowance

    def test_withheld_and_iuran_from_a_slip(self):
        res = {"deductions": [{"code": "jht_employee", "amount": "80000"}, {"code": "item", "label": "PPh 21", "amount": "44982"}],
               "employer": [{"code": "jp_employee_company", "amount": "40000"}]}
        self.assertEqual(Y.withheld_from_slip(res), D("44982"))
        self.assertIsNone(Y.withheld_from_slip({"deductions": []}))
        self.assertEqual(Y.iuran_from_slip(res), D("120000"))


class OpeningApiTests(base.PayRunTests):
    def test_type_in_one_row_then_remove_it(self):
        r = self.client.patch(URL, {"employee_id": str(self.andi.pk), "year": 2026, "months": 9, "bruto": "36000000",
                                    "pph": "0", "iuran": "720000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        row = next(x for x in r.data["rows"] if x["employee"]["full_name"] == "Andi")
        self.assertEqual((row["months"], row["bruto"], row["saved"]), (9, "36000000", True))
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="payroll.pph21_opening").exists())
        r = self.client.patch(URL, {"employee_id": str(self.andi.pk), "year": 2026, "months": 0, "bruto": "0", "pph": "0"},
                              format="json")
        self.assertFalse(Pph21Opening.objects.filter(employee=self.andi).exists())
        self.assertEqual(self.client.patch(URL, {"employee_id": str(self.andi.pk), "year": 2026, "months": 13,
                                                 "bruto": "1", "pph": "0"}, format="json").status_code, 400)

    def test_csv_is_checked_before_it_is_saved(self):
        bad = "no_karyawan;nama;bulan;bruto;pph21;iuran_jht_jp\nB-1;Andi;9;36.000.000;0;720.000\nX-9;Siapa;9;1;0;0\n"
        r = self.client.post(f"{URL}import/", {"year": "2026", "commit": "1",
                                               "file": SimpleUploadedFile("s.csv", bad.encode())}, format="multipart")
        self.assertEqual((r.data["errors"], r.data["saved"]), (1, False))
        self.assertEqual(Pph21Opening.objects.count(), 0)                        # one bad row: nothing saved
        good = "no_karyawan;nama;bulan;bruto;pph21;iuran_jht_jp\nb-1;Andi;9;36.000.000;0;720.000\nB-2;Budi;9;27.000.000;0;540.000\n"
        r = self.client.post(f"{URL}import/", {"year": "2026", "commit": "0",
                                               "file": SimpleUploadedFile("s.csv", good.encode())}, format="multipart")
        self.assertEqual((r.data["errors"], r.data["saved"], r.data["totals"]["bruto"]), (0, False, "63000000"))
        r = self.client.post(f"{URL}import/", {"year": "2026", "commit": "1",
                                               "file": SimpleUploadedFile("s.csv", good.encode())}, format="multipart")
        self.assertTrue(r.data["saved"])
        self.assertEqual(Pph21Opening.objects.filter(year=2026).count(), 2)

    def test_workers_cannot_see_it(self):
        user = CustomUser.objects.create_user(email="w9@beton.id", password="pass12345!", full_name="W", role="employee")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_yearly_preview_and_settings(self):
        s = self.client.get("/api/hr/payroll/settings/").data["settings"]
        self.assertEqual(s["pph21_tax_month"], "earliest")                    # G16-5a (D79): the law for new companies
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=10,
                                    bruto=D("40000000"), pph=D("0"), iuran=D("800000"))
        self.make_run()                                           # Oct (ends 25 Okt), paid 5 Nov: masa Okt 2026
        out = StringIO()
        call_command("pph21_annual_preview", year=2026, org="Beton", stdout=out)
        text = out.getvalue()
        self.assertIn("masa Okt 2026", text)
        self.assertIn("Payroll masa Desember: belum ada", text)
        self.assertIn("Andi", text)
        self.assertIn("BELUM LENGKAP: isi saldo awal", text)                     # Budi: joined 2025, none yet
        self.assertIn("Belum lengkap, tidak dijumlah: 1 orang", text)

    def test_people_who_joined_in_a_seegaji_month_need_no_saldo_awal(self):
        from apps.employees.models import Employee
        Employee.objects.filter(pk=self.budi.pk).update(join_date=date(2026, 9, 26))
        self.make_run()
        out = StringIO()
        call_command("pph21_annual_preview", year=2026, org="Beton", stdout=out)
        text = out.getvalue()
        self.assertIn("saldo awal tidak perlu", text)
        self.assertIn("Belum lengkap, tidak dijumlah: 1 orang", text)            # Andi still is

    def test_ptkp_checked_on_the_employee(self):
        r = self.client.patch(f"/api/hr/employees/{self.andi.pk}/", {"ptkp_checked": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.andi.refresh_from_db()
        self.assertTrue(self.andi.ptkp_checked)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(OpeningApiTests, _name, None)
