# =============================================================================
# === backend/apps/payroll/law_check.py ===
# =============================================================================
"""
G18-1 (19 Nov 2026) — "Aturan perusahaan vs UU": where a company's settings and data stand against
UU No. 27 Tahun 2026 (berlaku 28 Oktober 2026). Information only: never blocks, never scores.

Each row: status OK ("sesuai"), DIFFERS (a company setting chosen differently from the law), FOUND (people in the
data the law would treat differently), MISSING (a setting the check needs is empty). The row builders are pure;
build() reads the database once and asks each of them. A new feature adds its row builder to build().
"""
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from .engine import BASE_SHARE_MIN, serves_under_one_year

LAW = "UU No. 27 Tahun 2026"
OK, DIFFERS, FOUND, MISSING = "ok", "differs", "found", "missing"
SETTINGS_LINK = "/dashboard/payroll/pengaturan"
LEAVE_LINK = "/dashboard/cuti/pengaturan"              # G14-1
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


@dataclass
class Row:
    key: str
    status: str
    title: str
    company: str
    law: str
    article: str
    link: str = SETTINGS_LINK
    link_text: str = "Ubah"
    people: list = field(default_factory=list)
    changed: str = ""                     # "Diubah oleh Anthony, 20 Nov 2026"


def _rp(value):
    return "Rp " + f"{Decimal(value):,.0f}".replace(",", ".")


def _names(people):
    return sorted(people)


# ── row builders (pure) ──

def overtime_row(mode, flat_hour, changed=""):
    law = "1/173 upah sebulan; jam lembur pertama 1,5×, berikutnya 2×"
    article = "PP 35/2021, Pasal 116 dan 125"                       # G14-1: one bracket on the page, not two
    if mode == "flat":
        return Row("overtime", DIFFERS, "Upah lembur",
                   f"Tarif tetap perusahaan {_rp(flat_hour or 0)} per jam. SeeGaji tetap membandingkan setiap slip "
                   f"dengan PP 35/2021 dan memberi peringatan bila lebih rendah.",
                   law, article, changed=changed)
    return Row("overtime", OK, "Upah lembur", "Sesuai PP 35/2021", law, article, changed=changed)


def overtime_order_row(source, changed=""):
    """G17-E1: overtime needs a written / digital order and the worker's consent (Pasal 116 ayat 1)."""
    law = "Perintah lembur tertulis atau digital dan persetujuan karyawan; paling lama 4 jam sehari, 18 jam seminggu"
    article = "Pasal 116 ayat 1"
    if source == "spl":
        return Row("overtime_order", OK, "Perintah lembur",
                   "SPL dicatat di SeeGaji; lembur dibayar bila ada SPL, jam dari finger", law, article,
                   link="/dashboard/lembur/spl", link_text="Lembur → SPL", changed=changed)
    return Row("overtime_order", DIFFERS, "Perintah lembur",
               "Lembur diputuskan HR per hari; SPL kertas disimpan di luar SeeGaji (boleh dicatat di Lembur → SPL)",
               law, article, link=SETTINGS_LINK, changed=changed)


def collective_row(reduces, changed=""):
    """G14-1: cuti bersama and annual leave."""
    law = "Cuti bersama dari pemerintah tidak mengurangi cuti tahunan"
    if reduces:
        return Row("collective_leave", DIFFERS, "Cuti bersama", "Mengurangi cuti tahunan karyawan", law,
                   "Pasal 118 ayat 6", link=LEAVE_LINK, changed=changed)
    return Row("collective_leave", OK, "Cuti bersama", "Tidak mengurangi cuti tahunan", law, "Pasal 118 ayat 6",
               link=LEAVE_LINK, changed=changed)


def paternity_row(extra, changed=""):
    """G14-1: the 3 extra days are the company's choice ("dapat diberikan"), so any setting follows the law."""
    company = f"Istri melahirkan 2 + {extra} hari" if extra else "Istri melahirkan 2 hari"
    return Row("paternity", OK, "Cuti pendampingan istri", company + "; istri keguguran 2 hari",
               "Istri melahirkan 2 hari, dapat ditambah paling lama 3 hari; istri keguguran 2 hari", "Pasal 124",
               link=LEAVE_LINK, changed=changed)


def menstrual_row(on, changed=""):
    """G14-1: cuti haid."""
    law = "Pekerja perempuan yang sakit saat haid tidak wajib bekerja paling lama 2 hari, tetap dibayar"
    if on:
        return Row("menstrual", OK, "Cuti haid", "Paling lama 2 hari sebulan, dibayar", law,
                   "Pasal 120 dan 149 ayat 2", link=LEAVE_LINK, changed=changed)
    return Row("menstrual", DIFFERS, "Cuti haid", "Tidak bisa diajukan di SeeGaji", law, "Pasal 120 dan 149 ayat 2",
               link=LEAVE_LINK, changed=changed)


def maternity_row(pct, changed=""):
    """G14-2: the pay for months 5 and 6 of cuti melahirkan (paying more than the law is fine)."""
    law = "3 bulan dibayar penuh; perpanjangan sampai 3 bulan dengan surat dokter: bulan ke-4 penuh, ke-5 dan ke-6 75%"
    article = "Pasal 121 dan 123"
    company = f"Bulan ke-5 dan ke-6 dibayar {pct}%; istirahat keguguran 1,5 bulan dibayar penuh"
    return Row("maternity", OK if pct >= 75 else DIFFERS, "Cuti melahirkan", company, law, article,
               link=LEAVE_LINK, changed=changed)


def long_rest_row(on, due, changed=""):
    """G14-2: istirahat panjang; due = names who have earned it and not taken it yet."""
    law = ("30 hari kalender setelah 5 tahun bekerja berturut-turut (dan kelipatannya), dibayar; "
           "tahun itu tanpa cuti tahunan")
    article = "Pasal 118 ayat 2 huruf c dan ayat 4"
    if not on:
        return Row("long_rest", DIFFERS, "Istirahat panjang", "Tidak diberikan di SeeGaji", law, article,
                   link=LEAVE_LINK, changed=changed)
    company = "30 hari kalender setiap 5 tahun"
    if due:
        company += f"; {len(due)} karyawan berhak dan belum mengambil"
    return Row("long_rest", OK, "Istirahat panjang", company, law, article, link=LEAVE_LINK, people=_names(due),
               changed=changed)


def separation_row(months, changed=""):
    """G16-4: uang pisah when the company's PK / PP / PKB has no rule (Pasal 233 ayat 2: at least 1 month)."""
    law = "Bila PK / PP / PKB tidak mengatur: paling sedikit 1 bulan upah (untuk mengundurkan diri, mangkir, dll.)"
    n = f"{Decimal(months).normalize():f}".replace(".", ",")
    return Row("separation", OK if Decimal(months) >= 1 else DIFFERS, "Uang pisah", f"{n} bulan upah", law,
               "Pasal 233", link=SETTINGS_LINK, changed=changed)


def annual_leave_row(days=12):
    return Row("annual_leave", OK, "Cuti tahunan", f"{days} hari kerja setelah 12 bulan bekerja",
               "Paling sedikit 12 hari kerja setelah 12 bulan bekerja terus-menerus", "Pasal 118 ayat 5",
               link="/dashboard/cuti", link_text="Lihat")


def umk_row(minimum_wage, below, changed=""):
    """below: names of active monthly people with masa kerja < 1 tahun and pokok + tunjangan tetap < UMK."""
    law = "UMK berlaku untuk masa kerja kurang dari 1 tahun (gaji pokok + tunjangan tetap)"
    umk = Decimal(minimum_wage or 0)
    if umk <= 0:
        return Row("umk", MISSING, "UMK", "Belum diisi. Isi UMK di Pengaturan payroll agar SeeGaji bisa memberi catatan.",
                   law, "Pasal 140", changed=changed)
    if below:
        return Row("umk", FOUND, "Upah di bawah UMK",
                   f"{len(below)} karyawan masa kerja < 1 tahun di bawah UMK {_rp(umk)}", law, "Pasal 140",
                   link="/dashboard/karyawan", link_text="Lihat", people=_names(below), changed=changed)
    return Row("umk", OK, "UMK", f"Karyawan masa kerja < 1 tahun ≥ UMK {_rp(umk)}", law, "Pasal 140", changed=changed)


def base_share_row(below):
    """below: names of active monthly people whose gaji pokok is under 75% of pokok + tunjangan tetap."""
    law = "Gaji pokok paling sedikit 75% dari gaji pokok + tunjangan tetap"
    if below:
        return Row("base_share", FOUND, "Gaji pokok di bawah 75%", f"{len(below)} karyawan", law, "Pasal 150",
                   link="/dashboard/karyawan", link_text="Lihat", people=_names(below))
    return Row("base_share", OK, "Gaji pokok ≥ 75%", "Semua karyawan bulanan", law, "Pasal 150",
               link="/dashboard/karyawan", link_text="Lihat")


def bpjs_wage_row(below):
    """G16-1: people whose wage reported to BPJS is under gaji pokok + tunjangan tetap."""
    law = "Iuran BPJS Ketenagakerjaan dihitung dari upah sebulan: gaji pokok + tunjangan tetap"
    if below:
        return Row("bpjs_wage", FOUND, "Upah BPJS di bawah gaji",
                   f"{len(below)} karyawan dilaporkan ke BPJS dengan upah lebih kecil dari gaji pokok + tunjangan tetap",
                   law, "PP 44/2015 dan PP 46/2015", link="/dashboard/karyawan", link_text="Lihat",
                   people=_names(below))
    return Row("bpjs_wage", OK, "Upah BPJS", "Sama dengan gaji pokok + tunjangan tetap", law,
               "PP 44/2015 dan PP 46/2015", link="/dashboard/karyawan", link_text="Lihat")


def jp_row(enrolled, cap, changed=""):
    """G16-1: Jaminan Pensiun; no row when nobody is in JP."""
    if not enrolled:
        return None
    law = "Iuran JP 1% karyawan + 2% perusahaan, sampai batas upah yang ditetapkan BPJS setiap tahun"
    if Decimal(cap or 0) <= 0:
        return Row("jp", MISSING, "Jaminan Pensiun",
                   f"{enrolled} karyawan ikut JP, batas upah JP belum diisi di Pengaturan payroll", law, "PP 45/2015",
                   changed=changed)
    return Row("jp", OK, "Jaminan Pensiun", f"{enrolled} karyawan ikut JP, batas upah {_rp(cap)}", law, "PP 45/2015",
               changed=changed)


def bpjs_below(rows):
    """rows: (name, reported wage or None, gaji pokok + tunjangan tetap) -> names reported lower."""
    return [name for name, reported, wage in rows if reported and Decimal(reported) < Decimal(wage or 0)]


def people_checks(people, minimum_wage, today):
    """people: (name, join_date, base, fixed_allowance). -> (below_umk, below_share), lists of names."""
    umk = Decimal(minimum_wage or 0)
    below_umk, below_share = [], []
    for name, joined, base, allowance in people:
        base, allowance = Decimal(base or 0), Decimal(allowance or 0)
        total = base + allowance
        if umk > 0 and joined and serves_under_one_year(joined, today) and total < umk:
            below_umk.append(name)
        if base > 0 and allowance > 0 and base < total * BASE_SHARE_MIN:
            below_share.append(name)
    return below_umk, below_share


def changed_text(actor, at):
    if not at:
        return ""
    local = timezone.localtime(at)
    return f"Diubah oleh {actor}, {local.day} {MONTHS[local.month - 1]} {local.year}"


# ── the database ──

def _last_change(org, field_name, action="payroll.settings"):
    from apps.core.models import AuditEntry
    for entry in (AuditEntry.objects.filter(organization=org, action=action)
                  .select_related("actor").order_by("-created_at")[:200]):
        if field_name in ((entry.data or {}).get("after") or {}):
            return changed_text(entry.actor.full_name if entry.actor else "Sistem", entry.created_at)
    return ""


def build(org, today):
    from apps.employees.models import Employee
    from apps.leave.models import LeaveSettings
    from .models import PayrollSettings
    cfg = PayrollSettings.for_org(org)
    leave = LeaveSettings.for_org(org)                                                       # G14-1
    people = [(e.full_name, e.join_date, e.base_rate, e.fixed_allowance)
              for e in Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE,
                                               pay_type=Employee.PayType.MONTHLY)]
    below_umk, below_share = people_checks(people, cfg.minimum_wage, today)
    active = Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE)                    # G16-1
    reported = bpjs_below([(e.full_name, e.bpjs_wage, Decimal(e.base_rate or 0) + Decimal(e.fixed_allowance or 0))
                           for e in active.filter(pay_type=Employee.PayType.MONTHLY, bpjs_tk_enrolled=True,
                                                  bpjs_wage__isnull=False)])
    in_jp = active.filter(bpjs_tk_enrolled=True, jp_enrolled=True).count()
    from apps.leave import rules as leave_rules                                               # G14-2
    from apps.leave.models import LeaveRequest
    rests = list(LeaveRequest.objects.filter(organization=org, kind=leave_rules.LONG_REST,
                                             status__in=(LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED))
                 .values_list("employee_id", "start_date"))
    due = []
    for e in active.exclude(join_date__isnull=True):
        since = leave_rules.long_rest_since(e.join_date, today)
        if since and not any(who == e.id and start >= since for who, start in rests):
            due.append(e.full_name)
    return [
        overtime_row(cfg.overtime_mode, cfg.flat_overtime_hour, _last_change(org, "overtime_mode")),
        overtime_order_row(cfg.overtime_source, _last_change(org, "overtime_source")),               # G17-E1
        separation_row(cfg.separation_pay_months, _last_change(org, "separation_pay_months")),       # G16-4
        annual_leave_row(),
        collective_row(leave.collective_leave_reduces_annual,
                       _last_change(org, "collective_leave_reduces_annual", "leave.settings")),
        paternity_row(leave.paternity_extra_days, _last_change(org, "paternity_extra_days", "leave.settings")),
        menstrual_row(leave.menstrual_leave, _last_change(org, "menstrual_leave", "leave.settings")),
        maternity_row(leave.maternity_extension_pay,                                          # G14-2
                      _last_change(org, "maternity_extension_pay", "leave.settings")),
        long_rest_row(leave.long_rest, due, _last_change(org, "long_rest", "leave.settings")),
        umk_row(cfg.minimum_wage, below_umk, _last_change(org, "minimum_wage")),
        base_share_row(below_share),
        bpjs_wage_row(reported),                                                              # G16-1
        jp_row(in_jp, cfg.jp_wage_cap, _last_change(org, "jp_wage_cap")),
    ]


class LawCheckView(APIView):
    """GET /api/hr/payroll/law-check/"""
    permission_classes = [IsCompanyHR]

    def get(self, request):
        today = timezone.localdate()
        rows = [r for r in build(request.hr_org, today) if r is not None]                   # G16-1: jp_row may be None
        return Response({"success": True, "law": LAW, "effective": "2026-10-28", "as_of": today.isoformat(),
                         "rows": [asdict(r) for r in rows]})
