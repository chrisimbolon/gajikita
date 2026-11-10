"""
G12f.3.1 (10 Nov 2026) — HR's notes per day: imported from the recap, matched like the taps, shown beside
the day, and never touching status or money.

The shape is DKCB's October "ESR Edit" (two machines in one sheet: Department DKCB = plant = Mesin utama,
Staf / Manager = Mesin Kantor). Names and IDs are made up except where the scenario needs the real shape.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent, DayNote, EmployeeMachineId, FingerprintMachine
from apps.attendance.tests.test_day_notes import BLUE, PINK, YELLOW, esr_sheet, grid_sheet, workbook
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
IMPORT = "/api/hr/attendance/notes/import/"
DELETE = "/api/hr/attendance/notes/delete/"

OKT = [("32", "SUDIRMAN", "DKCB", "2026-10-12", "Finger in tidak terbaca & mati lampu", BLUE),
       ("32", "SUDIRMAN", "DKCB", "2026-10-14", "Mati lampu", BLUE),
       ("11", "Wawan", "DKCB", "2026-09-29", "UL", YELLOW),
       ("11", "Wawan", "DKCB", "2026-09-30", None, ""),                         # an exception row with no note
       ("3", "Lina", "Staf", "2026-10-05", "Belanja alat", BLUE),              # office ID 3, not plant ID 3
       ("17", "Vino", "DKCB", "2026-10-23", None, ""),                          # finding 16: 23 Okt twice
       ("17", "Vino", "DKCB", "2026-10-23", "Masuk jam 10:00 wib, OT sampai jam 00:01 wib", ""),
       ("99", "Orang Baru", "DKCB", "2026-10-02", "Belum join", PINK)]          # nobody has plant ID 99


def recap(rows=OKT, name="Absen Okt 2026 DKCB.xlsx"):
    return SimpleUploadedFile(name, workbook(grid_sheet(), esr_sheet(rows)))


class NotesBase(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        self.hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda no, name, fp: Employee.objects.create(
            organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6), fingerprint_id=fp,
            default_shift=self.shift, base_rate=Decimal("4000000"))
        self.sudirman = mk("DK19", "Sudirman", "32")
        self.wawan = mk("DK02", "Wawan Setiawan", "11")
        self.vino = mk("DK17", "Vinosius", "17")
        self.rudi = mk("DK03", "Rudi Hartono", "3")                              # plant ID 3: not the office's 3
        self.lina = mk("ST01", "Lina Marlina", "")
        self.kantor = FingerprintMachine.objects.create(organization=self.org, name="Mesin Kantor",
                                                        dept_labels="Staf, Manager")
        EmployeeMachineId.objects.create(organization=self.org, employee=self.lina, machine=self.kantor,
                                         fingerprint_id="3")

    def upload(self, machine="auto", commit="0", file=None, **extra):
        return self.client.post(IMPORT, {"file": file or recap(), "machine": machine, "commit": commit, **extra},
                                format="multipart")

    def notes(self):
        return {(n.employee.full_name, n.date.isoformat()): (n.code, n.text)
                for n in DayNote.objects.select_related("employee")}


class ImportTests(NotesBase):
    def test_preview_matches_each_row_on_its_own_machine_and_saves_nothing(self):
        resp = self.upload()
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data
        self.assertEqual((d["sheet"], d["period"], d["period_in_file"]),
                         ("ESR Edit", {"start": "2026-09-26", "end": "2026-10-25"}, True))
        self.assertEqual([x["label"] for x in d["legend"]], ["UL", "MC", "Minggu", "CT", "Lain", "Libur"])
        self.assertEqual(d["totals"], {"people": 4, "unknown": 1, "unknown_notes": 1, "notes": 5, "new": 5,
                                       "changed": 0, "same": 0, "removed": 0, "locked": 0, "name_mismatch": 0})
        lina = next(p for p in d["people"] if p["employee"]["full_name"] == "Lina Marlina")
        self.assertEqual(lina["machines"], [{"machine": "Mesin Kantor", "machine_id": "3"}])
        self.assertEqual(lina["lines"], [{"date": "2026-10-05", "code": "Lain", "color": BLUE, "text": "Belanja alat",
                                          "state": "new", "before": ""}])
        sud = next(p for p in d["people"] if p["employee"]["full_name"] == "Sudirman")
        self.assertEqual((sud["notes"], sud["codes"]), (2, [{"code": "Lain", "count": 2}]))
        self.assertEqual([(u["machine_id"], u["name"], u["notes"]) for u in d["unknown"]], [("99", "Orang Baru", 1)])
        self.assertEqual(d["repeated"], [{"machine_id": "17", "name": "Vino", "date": "2026-10-23"}])
        self.assertFalse(DayNote.objects.exists())

    def test_save_then_the_same_file_again_changes_nothing(self):
        resp = self.upload(commit="1")
        self.assertEqual(resp.data["applied"], {"added": 5, "changed": 0, "removed": 0})
        self.assertEqual(self.notes(), {
            ("Sudirman", "2026-10-12"): ("Lain", "Finger in tidak terbaca & mati lampu"),
            ("Sudirman", "2026-10-14"): ("Lain", "Mati lampu"),
            ("Wawan Setiawan", "2026-09-29"): ("UL", "UL"),
            ("Lina Marlina", "2026-10-05"): ("Lain", "Belanja alat"),
            ("Vinosius", "2026-10-23"): ("", "Masuk jam 10:00 wib, OT sampai jam 00:01 wib")})
        again = self.upload(commit="1")
        self.assertEqual(again.data["totals"]["same"], 5)
        self.assertEqual(again.data["applied"], {"added": 0, "changed": 0, "removed": 0})
        self.assertEqual(DayNote.objects.count(), 5)
        self.assertEqual(AuditEntry.objects.filter(action="attendance.day_notes_import").count(), 1)

    def test_an_edited_recap_updates_and_removes_only_inside_its_people_and_period(self):
        self.upload(commit="1")
        DayNote.objects.create(organization=self.org, employee=self.sudirman, date=date(2026, 9, 20), text="Agustus")
        edited = [r for r in OKT if r[3] != "2026-10-14"]                        # Mati lampu 14 Okt taken out
        edited = [(i, n, d, day, "Mati lampu total" if day == "2026-10-12" else note, f)
                  for i, n, d, day, note, f in edited]
        edited = [r for r in edited if r[0] != "3"]                               # Lina not in this file at all
        d = self.upload(commit="1", file=recap(edited)).data
        self.assertEqual((d["totals"]["changed"], d["totals"]["removed"]), (1, 1))
        line = next(l for p in d["people"] for l in p["lines"] if l["date"] == "2026-10-12")
        self.assertEqual((line["state"], line["before"], line["text"]),
                         ("changed", "Finger in tidak terbaca & mati lampu", "Mati lampu total"))
        notes = self.notes()
        self.assertEqual(notes[("Sudirman", "2026-10-12")], ("Lain", "Mati lampu total"))
        self.assertNotIn(("Sudirman", "2026-10-14"), notes)
        self.assertIn(("Lina Marlina", "2026-10-05"), notes)                     # not in the file: untouched
        self.assertIn(("Sudirman", "2026-09-20"), notes)                         # outside the period: untouched

    def test_locked_days_are_left_alone(self):
        AttendanceDay.objects.create(organization=self.org, employee=self.sudirman, date=date(2026, 10, 12),
                                     shift=self.shift, is_locked=True)
        d = self.upload(commit="1").data
        self.assertEqual((d["totals"]["new"], d["totals"]["locked"], d["applied"]["added"]), (4, 1, 4))
        self.assertNotIn(("Sudirman", "2026-10-12"), self.notes())
        DayNote.objects.create(organization=self.org, employee=self.sudirman, date=date(2026, 10, 12), text="lama")
        gone = [r for r in OKT if r[3] != "2026-10-12"]
        d = self.upload(commit="1", file=recap(gone)).data
        self.assertEqual(d["totals"]["removed"], 0)
        self.assertIn(("Sudirman", "2026-10-12"), self.notes())                 # a locked day keeps its note

    def test_a_name_that_does_not_match_needs_a_tick(self):
        self.wawan.full_name = "Bambang"
        self.wawan.save()
        resp = self.upload(commit="1")
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "names_unconfirmed"))
        self.assertFalse(DayNote.objects.exists())
        ok = self.upload(commit="1", confirm_names="1")
        self.assertEqual(ok.data["applied"]["added"], 5)

    def test_the_wrong_machine_is_pointed_out(self):
        """Read "Dari Mesin Kantor", the plant IDs find nobody (or the wrong person): Otomatis fits clearly better."""
        d = self.upload(machine=str(self.kantor.pk)).data
        self.assertEqual(d["suggest_machine"]["mode"], "auto")

    def test_files_without_notes_are_refused_plainly(self):
        empty = [(i, n, d, day, None, "") for i, n, d, day, _, _ in OKT]
        resp = self.upload(file=SimpleUploadedFile("mesin.xlsx", workbook(esr_sheet(empty))))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("belum berisi catatan", resp.data["message"])
        resp = self.upload(file=SimpleUploadedFile("1_attlog.dat", b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n"))
        self.assertIn("hanya bisa dibaca dari file Excel", resp.data["message"])


class ShownTests(NotesBase):
    """The notes reach the screens, and change nothing else."""
    def setUp(self):
        super().setUp()
        self.tp12 = self.work(self.sudirman, date(2026, 10, 12), (7, 55), None)   # no clock-out: needs HR
        self.tp13 = self.work(self.sudirman, date(2026, 10, 13), (7, 50), None)
        before = self.client.get("/api/hr/attendance/review/period/", {"month": "2026-10"}).data
        self.before = [(r["date"], r["status"], r["review_reasons"]) for r in before["rows"]]
        self.upload(commit="1")

    def work(self, emp, d, inn, out):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, hm in (("in", inn), ("out", out)):
            if hm:
                t = datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=WIB)
                ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                          occurred_at=t, received_at=t)
        return day

    def test_day_panel_daily_and_rekap(self):
        day = self.client.get(f"/api/hr/attendance/days/{self.tp12.pk}/").data["day"]
        self.assertEqual(day["hr_note"], {"code": "Lain", "color": BLUE, "text": "Finger in tidak terbaca & mati lampu"})
        self.assertIsNone(self.client.get(f"/api/hr/attendance/days/{self.tp13.pk}/").data["day"]["hr_note"])
        daily = self.client.get("/api/hr/attendance/daily/", {"date": "2026-09-29"}).data
        wawan = next(r for r in daily["rows"] if r["employee"]["full_name"] == "Wawan Setiawan")
        self.assertEqual((wawan["status"], wawan["hr_note"]["code"]), ("absent", "UL"))   # status unchanged
        rekap = self.client.get("/api/hr/attendance/rekap/", {"month": "2026-10"}).data
        row = next(r for r in rekap["rows"] if r["employee"]["full_name"] == "Wawan Setiawan")
        cell = next(c for c in row["cells"] if c["d"] == "2026-09-29")
        self.assertEqual((cell["c"], cell["hn"]["text"]), ("A", "UL"))
        self.assertIsNone(next(c for c in row["cells"] if c["d"] == "2026-09-28")["hn"])
        export = self.client.get("/api/hr/attendance/rekap/export/", {"month": "2026-10"})
        self.assertEqual(export.status_code, 200)

    def test_review_queue_unchanged_and_filter_has_note(self):
        url = "/api/hr/attendance/review/period/"
        d = self.client.get(url, {"month": "2026-10"}).data
        self.assertEqual([(r["date"], r["status"], r["review_reasons"]) for r in d["rows"]], self.before)
        self.assertEqual(d["with_note"], 1)
        noted = self.client.get(url, {"month": "2026-10", "has_note": "1"}).data
        self.assertEqual([(r["date"], r["hr_note"]["code"]) for r in noted["rows"]], [("2026-10-12", "Lain")])
        other = self.client.get(url, {"month": "2026-10", "has_note": "0"}).data
        self.assertEqual([r["date"] for r in other["rows"]], ["2026-10-13"])
        bulk = self.client.post("/api/hr/attendance/review/bulk/",
                                {"action": "approve", "month": "2026-10", "has_note": "1", "note": "Sesuai catatan"},
                                format="json")
        self.assertEqual(bulk.data["decided"], 1)                              # only what the filter showed
        self.tp12.refresh_from_db()
        self.tp13.refresh_from_db()
        self.assertEqual((self.tp12.decision, self.tp13.decision), ("approved", ""))


class DeleteTests(NotesBase):
    def test_delete_imported_notes_in_a_range(self):
        self.upload(commit="1")
        AttendanceDay.objects.create(organization=self.org, employee=self.sudirman, date=date(2026, 10, 14),
                                     shift=self.shift, is_locked=True)
        body = {"start": "2026-10-01", "end": "2026-10-25"}
        d = self.client.post(DELETE, body, format="json").data
        self.assertEqual(d["totals"], {"notes": 3, "people": 3, "locked": 1})
        refused = self.client.post(DELETE, {**body, "commit": True}, format="json")
        self.assertEqual(refused.status_code, 400)                              # a reason is required
        done = self.client.post(DELETE, {**body, "commit": True, "reason": "Salah file"}, format="json")
        self.assertEqual(done.data["applied"], {"removed": 3})
        self.assertEqual(set(self.notes()), {("Wawan Setiawan", "2026-09-29"), ("Sudirman", "2026-10-14")})
        audit = AuditEntry.objects.get(action="attendance.day_notes_delete")
        self.assertEqual(audit.data["note"], "Salah file")
