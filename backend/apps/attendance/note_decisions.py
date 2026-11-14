# =============================================================================
# === backend/apps/attendance/note_decisions.py ===
# =============================================================================
"""
HR's notes -> decisions (G17-4, 14 Nov 2026). Pure Python, no Django.

DKCB keeps its leave in the Note column of the attendance recap ("ESR Edit"), imported as DayNotes (G12f.3):
"UL", "UL 1/2 hari", "Izin pulang cepat ...", "Cuti sakit mata". Until now they were information only, so HR
had to make every decision again by hand. October 2026: those notes explain the book's unpaid-leave days
exactly (Eko 8, Syaiful 4, Edi 2.5, Taufik 1.5, Togar 2, Vinsen 2.5, Prayuda 2, Feny 3, Tari 1).

  classify(code, text) -> one of the groups below
  UL         a whole day without pay                 -> unpaid leave that day
  HALF       "UL 1/2", "Izin masuk ...", "Izin pulang cepat ..." -> ½ day without pay, no late / early minutes
  CUTI       "Cuti ..." a whole day                  -> HR chooses each time: annual leave or unpaid
  HALF_CUTI  "Cuti 1/2 hari ..."                     -> HR chooses each time: paid (no cut) or ½ day unpaid
  FORGIVE    "Mati lampu", "Finger ... tidak terbaca": the machine failed, not the person -> approve the day and
             forgive late / single tap (days already covered by a Kejadian show as done)
  AWAY       "Belanja alat", "Standbye di office BSP", "Kerja di Lobam": company work away from the machine ->
             each day a one-day "tidak wajib absen" (Tugas luar): counted as worked (G17-5; before that these sat
             under HANDLED and a day without taps stayed absent: Ramawan 5-10 Okt, Feny 1 and 24 Okt)
  HANDLED    has left ("Sudah tidak join"): the end date decides, so nothing to do here
  OTHER      anything else stays a note
"""
import re

UL, HALF, CUTI, HALF_CUTI, FORGIVE, HANDLED, OTHER = "ul", "half", "cuti", "half_cuti", "forgive", "handled", "other"
AWAY = "away"                                                                        # G17-5

GROUPS = [
    (UL, "Tidak masuk tanpa upah (UL)",
     "Satu hari penuh tidak dibayar. Jadi Cuti & Izin: izin tanpa upah di tanggal itu."),
    (HALF, "Izin ½ hari tanpa upah",
     "Datang siang atau pulang cepat dengan izin. Dipotong ½ hari upah, tanpa potongan terlambat atau pulang cepat."),
    (CUTI, "Cuti",
     "Pilih untuk setiap baris: cuti tahunan (dibayar, mengurangi sisa cuti) atau tanpa upah (mis. sisa cuti habis)."),
    (HALF_CUTI, "Cuti ½ hari",
     "Pilih untuk setiap baris: dibayar (tanpa potongan) atau ½ hari tanpa upah."),
    (FORGIVE, "Mesin / listrik bermasalah",
     "Mati lampu atau sidik jari tidak terbaca: hari disetujui, terlambat dan tap sekali dimaafkan. Hari tanpa tap "
     "sama sekali: pakai Kejadian atau Ubah jam."),
    (AWAY, "Tugas luar",
     "Belanja alat, standby atau kerja di lokasi lain untuk perusahaan: hari dihitung hadir penuh (Tidak wajib "
     "absen 1 hari), tanpa potongan dan tanpa lembur / uang makan otomatis."),
    (HANDLED, "Sudah keluar",
     "Karyawan sudah tidak bekerja: isi Tanggal keluar di halaman Karyawan. Tidak perlu keputusan di sini."),
    (OTHER, "Catatan lain", "Tetap sebagai catatan. Putuskan di Perlu Tinjau bila perlu."),
]
LABELS = {k: label for k, label, _ in GROUPS}
CHOICES = {
    CUTI: [("annual", "Cuti tahunan (dibayar)"), ("unpaid", "Tanpa upah")],
    HALF_CUTI: [("paid", "Dibayar, tanpa potongan"), ("unpaid", "½ hari tanpa upah")],
}
ACTIONABLE = (UL, HALF, CUTI, HALF_CUTI, FORGIVE, AWAY)

FORGIVE_WORDS = ("mati lampu", "listrik", "tidak terbaca", "tdk terbaca", "mesin rusak", "mesin error")
AWAY_WORDS = ("belanja", "standby", "standbye", "lobam", "kerja di", "tugas luar", "dinas luar")
HANDLED_WORDS = ("tidak join", "tdk join", "sudah keluar", "resign")
_HALF = re.compile(r"1\s*/\s*2|½|setengah")


def _norm(text):
    return " ".join(str(text or "").lower().split())


def classify(code, text):
    t, c = _norm(text), str(code or "").strip().upper()
    if not t and not c:
        return OTHER
    if any(w in t for w in FORGIVE_WORDS):
        return FORGIVE
    if any(w in t for w in HANDLED_WORDS):
        return HANDLED
    if any(w in t for w in AWAY_WORDS):
        return AWAY
    half = bool(_HALF.search(t)) or t.startswith("izin masuk") or t.startswith("izin datang") or "pulang cepat" in t
    if "cuti" in t or c in ("CT", "CUTI"):
        return HALF_CUTI if half else CUTI
    if half:
        return HALF
    if c == "UL" or re.match(r"^ul\b", t) or "tanpa upah" in t or "unpaid" in t:
        return UL
    return OTHER
