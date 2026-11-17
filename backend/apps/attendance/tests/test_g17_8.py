"""
G17-8 (17 Nov 2026) — overtime decided from HR's recap file ("ASR Edit": an overtime row under each person's taps).
Made-up people and numbers.
"""
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from openpyxl import Workbook
from rest_framework.test import APITestCase

from apps.attendance import overtime_sheet as S
from apps.attendance.fingerprint import FileError
from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
START, END = date(2026, 9, 26), date(2026, 10, 25)
DAYS = [START + timedelta(days=k) for k in range((END - START).days + 1)]
URL = "/api/hr/attendance/overtime/import/"


def grid(people, total_label="OT"):
    """people: [(id, name, dept, {date: taps text}, {date: overtime value} or None, total or None)] -> rows."""
    rows = [["Attendance Record Report"], [],
            ["Att. Time", None, f"{START} ~ {END}", None, None, None, None, None, None, "Tabulation"],
            [d.day for d in DAYS] + [None, total_label, "SR", "UM"]]
    for pid, name, dept, taps, ot, total in people:
        rows.append(["ID:", None, pid] + [None] * 5 + ["Name:", None, name] + [None] * 7 + ["Dept.:", None, dept])
        rows.append([taps.get(d) for d in DAYS])
        if ot is not None:
            rows.append([ot.get(d) for d in DAYS] + [None, total])
    return rows


def xlsx(rows, title="ASR Edit"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    extra = wb.create_sheet("Note")
    extra.append(["Perhitungan jam lembur"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class SheetTests(SimpleTestCase):
    def test_cells(self):
        cases = {3.5: 210, 10: 600, "3,5": 210, "3.5": 210, "3:30": 210, "3j30": 210, "3 jam 30 mnt": 210,
                 0: 0, "0:00": 0, None: None, "": None, "-": None, "abc": S.BAD, 25: S.BAD, -1: S.BAD, True: S.BAD}
        for value, want in cases.items():
            self.assertEqual(S.ot_minutes(value), want, value)
        self.assertEqual(S.ot_minutes("88", max_hours=S.MAX_TOTAL_HOURS), 88 * 60)

    def test_blocks(self):
        d1, d2, d3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
        rows = grid([("8", "Arif", "DKCB", {d1: "07:5020:05", d2: "07:3819:01"}, {d1: 3, d2: "2,5", d3: "SPL?"}, "5.5"),
                     ("30", "Marganda", "DKCB", {}, {}, 0),                       # no overtime this month: in the file
                     ("2", "Dila", "Staf", {d1: "07:4817:00"}, None, None)])     # a machine block: no overtime row
        of = S.parse_overtime_grid(rows, "ASR Edit")
        arif, marganda, dila = of.blocks
        self.assertEqual((arif.minutes, arif.total, arif.total_file), ({d1: 180, d2: 150}, 330, 330))
        self.assertEqual(arif.unreadable, [(d3, "SPL?")])
        self.assertEqual((marganda.has_row, marganda.total, marganda.total_file), (True, 0, 0))
        self.assertEqual((dila.has_row, dila.dept), (False, "Staf"))
        self.assertEqual([b.name for b in of.people], ["Arif", "Marganda"])

    def test_machine_export_has_no_overtime(self):
        rows = grid([("8", "Arif", "DKCB", {date(2026, 10, 1): "07:5020:05"}, None, None),
                     ("5", "Hadi", "DKCB", {date(2026, 10, 1): "07:5617:00"}, None, None)])
        self.assertIsNone(S.parse_overtime_grid(rows))
        with self.assertRaisesMessage(FileError, "Tidak ada baris lembur"):
            S.read_overtime("mesin.xlsx", xlsx(rows))

    def test_best_sheet_is_read(self):
        of = S.read_overtime("rekap.xlsx", xlsx(grid([("8", "Arif", "DKCB", {}, {date(2026, 10, 1): 4}, 4)])))
        self.assertEqual((of.sheet, of.period, of.people[0].total), ("ASR Edit", (START, END), 240))


class ImportTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Lembur")
        hr = CustomUser.objects.create_user(email="hr@lembur.id", password="pass12345!", full_name="HR Lembur")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda fp, name, **kw: Employee.objects.create(organization=self.org, employee_no=f"K-{fp}", full_name=name,
                                                            fingerprint_id=fp, join_date=date(2025, 1, 6),
                                                            default_shift=self.shift, base_rate=Decimal("3000000"), **kw)
        self.arif, self.yuda = mk("8", "Arif Contoh"), mk("6", "Yuda Contoh")
        self.driver = mk("11", "Supri Contoh", overtime_eligible=False)
        self.lock = mk("22", "Ganda Contoh")
        self.work(self.arif, date(2026, 10, 1), (8, 0), (20, 30))          # proposes 3 h 30
        self.work(self.arif, date(2026, 10, 2), (8, 0), (19, 1))           # proposes 2 h, no SPL in the file
        self.work(self.yuda, date(2026, 10, 5), (8, 0), (19, 0),
                  decision="approved", overtime_approved_minutes=120)      # paid before, the file says none
        self.work(self.yuda, date(2026, 10, 6), (8, 0), (19, 0))
        self.work(self.lock, date(2026, 10, 8), (8, 0), (20, 0), is_locked=True)

    def work(self, emp, d, t_in, t_out, **day_fields):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **day_fields)
        for kind, (h, m) in (("in", t_in), ("out", t_out)):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)
        return day

    def file(self, arif_name="Arif Contoh"):
        rows = grid([
            ("8", arif_name, "DKCB", {}, {date(2026, 10, 1): 3.5, date(2026, 10, 14): 9}, 12.5),   # 14 Okt: no taps (power cut)
            ("6", "Yuda Contoh", "DKCB", {}, {date(2026, 10, 6): 2}, 2),
            ("11", "Supri Contoh", "DKCB", {}, {date(2026, 10, 7): 2}, 2),
            ("22", "Ganda Contoh", "DKCB", {}, {date(2026, 10, 8): 3}, 3),
            ("99", "Orang Lain", "DKCB", {}, {date(2026, 10, 9): 3}, 3),
        ])
        return SimpleUploadedFile("1026 Absensi.xlsx", xlsx(rows))

    def post(self, commit=False, **kw):
        return self.client.post(URL, {"file": kw.pop("f", None) or self.file(), "commit": "1" if commit else "0", **kw},
                                format="multipart")

    def day(self, emp, d):
        return AttendanceDay.objects.get(employee=emp, date=d)

    def test_preview_then_save_then_undo(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.data)
        t = r.data["totals"]
        self.assertEqual((t["pay"], t["none"], t["unpay"], t["not_eligible"], t["locked"], t["unknown_with_overtime"]),
                         (3, 1, 1, 1, 1, 1))
        arif = next(p for p in r.data["people"] if p["employee"]["full_name"] == "Arif Contoh")
        self.assertEqual([(l["date"], l["state"], l["book"], l["proposed"]) for l in arif["lines"]],
                         [("2026-10-01", "pay", 210, 210), ("2026-10-02", "none", 0, 121), ("2026-10-14", "pay", 540, 0)])
        self.assertEqual((arif["file_minutes"], arif["file_total"], arif["total_mismatch"]), (750, 750, False))
        self.assertFalse(AttendanceDay.objects.filter(employee=self.arif, date=date(2026, 10, 14)).exists())

        r = self.post(commit=True)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["applied"]["decided"], r.data["applied"]["minutes"]), (5, 210 + 540 + 120))
        self.assertEqual((self.day(self.arif, date(2026, 10, 1)).decision, self.day(self.arif, date(2026, 10, 1)).overtime_approved_minutes),
                         ("approved", 210))
        self.assertEqual(self.day(self.arif, date(2026, 10, 14)).overtime_approved_minutes, 540)
        self.assertEqual((self.day(self.arif, date(2026, 10, 2)).decision, self.day(self.arif, date(2026, 10, 2)).overtime_approved_minutes),
                         ("approved", None))
        self.assertIsNone(self.day(self.yuda, date(2026, 10, 5)).overtime_approved_minutes)
        self.assertEqual(self.day(self.yuda, date(2026, 10, 6)).overtime_approved_minutes, 120)
        self.assertEqual(self.day(self.lock, date(2026, 10, 8)).decision, "")              # locked: untouched
        self.assertFalse(AttendanceDay.objects.filter(employee=self.driver).exists())       # not entitled: untouched

        again = self.post()
        self.assertEqual(again.data["totals"]["todo"], 0)                                  # the same file changes nothing
        self.assertEqual(self.post(commit=True).status_code, 400)

        u = self.client.post("/api/hr/attendance/review/undo/", {"batch": r.data["applied"]["batch"]}, format="json")
        self.assertEqual((u.status_code, u.data["undone"]), (200, 5))
        self.assertEqual(self.day(self.arif, date(2026, 10, 1)).decision, "")
        self.assertEqual(self.day(self.yuda, date(2026, 10, 5)).overtime_approved_minutes, 120)

    def test_a_name_that_does_not_match_needs_a_tick(self):
        r = self.post(commit=True, f=self.file("Budi Lain Sekali"))
        self.assertEqual((r.status_code, r.data["code"]), (400, "names_unconfirmed"))
        r = self.post(commit=True, f=self.file("Budi Lain Sekali"), confirm_names="1")
        self.assertEqual(r.status_code, 200, r.data)

    def test_a_machine_export_is_refused(self):
        rows = grid([("8", "Arif Contoh", "DKCB", {date(2026, 10, 1): "08:0020:30"}, None, None)])
        r = self.post(f=SimpleUploadedFile("mesin.xlsx", xlsx(rows, "Att.log report")))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Tidak ada baris lembur", r.data["message"])
