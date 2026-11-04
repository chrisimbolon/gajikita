"""G11 (4 Nov 2026) — the kinds of review reasons, and the overtime cap. Pure."""
from django.test import SimpleTestCase

from apps.attendance.review_kinds import capped_overtime, kinds_of


class ReviewKindsTests(SimpleTestCase):
    def test_kinds_from_reasons(self):
        self.assertEqual(kinds_of(["Terlambat 20 menit", "Lembur 180 menit menunggu persetujuan"]), ["overtime", "late"])
        self.assertEqual(kinds_of(["Tidak absen pulang"]), ["no_clock_out"])
        self.assertEqual(kinds_of(["Masuk padahal sakit", "Di luar lokasi kerja"]), ["leave_work", "other"])

    def test_overtime_cap(self):
        self.assertEqual((capped_overtime(390, 240), capped_overtime(180, 240), capped_overtime(390, None),
                          capped_overtime(0, 240)), (240, 180, 390, None))
