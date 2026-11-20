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
    law = "1/173 upah sebulan; jam lembur pertama 1,5×, berikutnya 2× (PP 35/2021)"
    if mode == "flat":
        return Row("overtime", DIFFERS, "Upah lembur",
                   f"Tarif tetap perusahaan {_rp(flat_hour or 0)} per jam. SeeGaji tetap membandingkan setiap slip "
                   f"dengan PP 35/2021 dan memberi peringatan bila lebih rendah.",
                   law, "Pasal 116 dan 125", changed=changed)
    return Row("overtime", OK, "Upah lembur", "Sesuai PP 35/2021", law, "Pasal 116 dan 125", changed=changed)


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

def _last_change(org, field_name):
    from apps.core.models import AuditEntry
    for entry in (AuditEntry.objects.filter(organization=org, action="payroll.settings")
                  .select_related("actor").order_by("-created_at")[:200]):
        if field_name in ((entry.data or {}).get("after") or {}):
            return changed_text(entry.actor.full_name if entry.actor else "Sistem", entry.created_at)
    return ""


def build(org, today):
    from apps.employees.models import Employee
    from .models import PayrollSettings
    cfg = PayrollSettings.for_org(org)
    people = [(e.full_name, e.join_date, e.base_rate, e.fixed_allowance)
              for e in Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE,
                                               pay_type=Employee.PayType.MONTHLY)]
    below_umk, below_share = people_checks(people, cfg.minimum_wage, today)
    return [
        overtime_row(cfg.overtime_mode, cfg.flat_overtime_hour, _last_change(org, "overtime_mode")),
        annual_leave_row(),
        umk_row(cfg.minimum_wage, below_umk, _last_change(org, "minimum_wage")),
        base_share_row(below_share),
    ]


class LawCheckView(APIView):
    """GET /api/hr/payroll/law-check/"""
    permission_classes = [IsCompanyHR]

    def get(self, request):
        today = timezone.localdate()
        rows = build(request.hr_org, today)
        return Response({"success": True, "law": LAW, "effective": "2026-10-28", "as_of": today.isoformat(),
                         "rows": [asdict(r) for r in rows]})
