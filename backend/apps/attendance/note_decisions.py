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
  HANDLED    errands, works elsewhere, has left: already decided by Tugas luar, "tidak wajib absen" or the end
             date, so nothing to do here
  OTHER      anything else stays a note
"""
import re

UL, HALF, CUTI, HALF_CUTI, FORGIVE, HANDLED, OTHER = "ul", "half", "cuti", "half_cuti", "forgive", "handled", "other"

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
    (HANDLED, "Sudah ditangani",
     "Belanja (Tugas luar), kerja di lokasi lain (Tidak wajib absen), sudah keluar (tanggal keluar). Tidak perlu "
     "keputusan di sini."),
    (OTHER, "Catatan lain", "Tetap sebagai catatan. Putuskan di Perlu Tinjau bila perlu."),
]
LABELS = {k: label for k, label, _ in GROUPS}
CHOICES = {
    CUTI: [("annual", "Cuti tahunan (dibayar)"), ("unpaid", "Tanpa upah")],
    HALF_CUTI: [("paid", "Dibayar, tanpa potongan"), ("unpaid", "½ hari tanpa upah")],
}
ACTIONABLE = (UL, HALF, CUTI, HALF_CUTI, FORGIVE)

FORGIVE_WORDS = ("mati lampu", "listrik", "tidak terbaca", "tdk terbaca", "mesin rusak", "mesin error")
HANDLED_WORDS = ("belanja", "lobam", "tidak join", "sudah keluar", "resign", "standby", "standbye")
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
    half = bool(_HALF.search(t)) or t.startswith("izin masuk") or t.startswith("izin datang") or "pulang cepat" in t
    if "cuti" in t or c in ("CT", "CUTI"):
        return HALF_CUTI if half else CUTI
    if half:
        return HALF
    if c == "UL" or re.match(r"^ul\b", t) or "tanpa upah" in t or "unpaid" in t:
        return UL
    return OTHER
