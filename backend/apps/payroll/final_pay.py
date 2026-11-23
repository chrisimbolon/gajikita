# =============================================================================
# === backend/apps/payroll/final_pay.py ===
# =============================================================================
"""
G16-4 (23 Nov 2026) — "Hak akhir": what a leaving worker is owed under UU No. 27/2026 (Pasal 229-250), and the
PPh 21 final on it (PP 68/2009). The pure part (tables, reasons, compute) has no database; the service part
(defaults, attach to the last payslip) is at the bottom.

  Pesangon (Pasal 232 ayat 2)  masa kerja in full years + 1 month of upah, at most 9.
  UPMK     (Pasal 232 ayat 3)  3-6 years 2 months ... 21-24 years 8, 24+ years 10.
  UPH      (Pasal 232 ayat 4)  annual leave not taken x a day's upah (the company's daily divisor), ongkos pulang,
                               other rights in the PK / PP / PKB (typed by HR).
  Uang pisah (Pasal 233)       the company's rule, or at least 1 month of upah (Pengaturan payroll).
  Kompensasi PKWT (Pasal 88)   masa kerja in months / 12 x upah (PP 35/2021 until the new PP: "sementara").
  Upah     (Pasal 234)         gaji pokok + tunjangan tetap; daily pay: 30 x a day; piece rate: average of the last
                               12 months, never below the minimum wage.
  Masa kerja                   from the join date up to and including the last day of work.
  PPh 21 final (PP 68/2009)    0% up to Rp 50 jt, 5% up to 100 jt, 15% up to 500 jt, 25% above; never in TER or the
                               yearly calculation.

The law is the default; HR may change any amount, with a reason, and the statement shows it ("berbeda dari UU").
"""
from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
ZERO = D("0")

# slip codes: earnings that are hak akhir (never in TER bruto) and the final tax deduction
PREFIX = "pesangon_"
TAX_CODE, TAX_LABEL = "pph21_final", "PPh 21 final pesangon (PP 68/2009)"
CODES = {"pesangon": "pesangon_uang", "upmk": "pesangon_upmk", "uph_leave": "pesangon_uph_cuti",
         "uph_travel": "pesangon_uph_ongkos", "separation": "pesangon_pisah", "compensation": "pesangon_kompensasi",
         "other": "pesangon_lain"}


def rupiah(v):
    return D(v).quantize(D("1"), rounding=ROUND_HALF_UP)


def is_final_pay_code(code):
    return str(code or "").startswith(PREFIX)


@dataclass(frozen=True)
class Reason:
    key: str
    label: str
    article: str
    pesangon: Decimal = ZERO      # x Pasal 232 ayat 2
    upmk: Decimal = ZERO          # x Pasal 232 ayat 3
    uph: bool = True
    separation: bool = False      # uang pisah (Pasal 233)
    compensation: bool = False    # uang kompensasi PKWT (Pasal 88)
    note: str = ""


_R = [
    Reason("resign", "Mengundurkan diri atas kemauan sendiri", "Pasal 231 huruf i, Pasal 242", separation=True,
           note="Syarat: surat pengunduran diri paling lambat 30 hari sebelumnya."),
    Reason("absent", "Mangkir 5 hari kerja berturut-turut (dianggap mengundurkan diri)", "Pasal 231 huruf j, Pasal 243",
           separation=True, note="Syarat: sudah dipanggil 2 kali secara patut dan tertulis."),
    Reason("contract_end", "Kontrak (PKWT) berakhir", "Pasal 88", compensation=True,
           note="Uang kompensasi memakai rumus PP 35/2021 sampai PP baru terbit (sementara)."),
    Reason("misconduct", "Melanggar PK / PP / PKB setelah SP 1, 2 dan 3", "Pasal 231 huruf k, Pasal 244", D(1), D(1)),
    Reason("retire", "Memasuki usia pensiun", "Pasal 231 huruf n, Pasal 247", D(2), D(1),
           note="Manfaat program pensiun yang iurannya dibayar perusahaan boleh diperhitungkan (Pasal 248)."),
    Reason("death", "Meninggal dunia (dibayar kepada ahli waris)", "Pasal 231 huruf o, Pasal 249", D(2), D(1)),
    Reason("long_sick", "Sakit berkepanjangan / disabilitas akibat kecelakaan kerja lebih dari 12 bulan",
           "Pasal 231 huruf m, Pasal 246", D(2), D(2)),
    Reason("merger_worker", "Penggabungan / pengambilalihan: karyawan tidak bersedia melanjutkan",
           "Pasal 231 huruf a, Pasal 236 ayat 1", D(1), D(1)),
    Reason("merger_company", "Penggabungan / pengambilalihan: perusahaan tidak bersedia menerima",
           "Pasal 231 huruf a, Pasal 236 ayat 2", D(2), D(1)),
    Reason("loss", "Perusahaan tutup karena rugi 2 tahun berturut-turut", "Pasal 231 huruf b, Pasal 237", D(1), D(1)),
    Reason("closure", "Perusahaan tutup permanen (keputusan pemilik)", "Pasal 231 huruf c, Pasal 238", D(1), D("1.5")),
    Reason("force_majeure", "Keadaan memaksa (kahar)", "Pasal 231 huruf d, Pasal 239", D(1), D(1)),
    Reason("pkpu", "Perusahaan dalam penundaan kewajiban pembayaran utang (PKPU)", "Pasal 231 huruf e, Pasal 240",
           D(1), D(1)),
    Reason("bankrupt", "Perusahaan pailit", "Pasal 231 huruf f, Pasal 240", D(1), D(1)),
    Reason("employer_fault", "Permohonan PHK oleh karyawan karena perbuatan pemberi kerja",
           "Pasal 231 huruf g, Pasal 241 ayat 1", D(2), D(1)),
    Reason("employer_fault_rejected", "Permohonan PHK karyawan dinyatakan tidak terbukti oleh lembaga PPHI",
           "Pasal 241 ayat 2", separation=True),
    Reason("detained_loss", "Ditahan 6 bulan dan menyebabkan kerugian perusahaan", "Pasal 231 huruf l, Pasal 245 ayat 3",
           separation=True),
    Reason("detained", "Ditahan 6 bulan dan tidak menyebabkan kerugian perusahaan",
           "Pasal 231 huruf l, Pasal 245 ayat 4", ZERO, D(1)),
]
REASONS = {r.key: r for r in _R}


# ── masa kerja and the two tables ──
def add_months(d, n):
    from calendar import monthrange
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return Date(y, m, min(d.day, monthrange(y, m)[1]))


def service(join_date, end_date):
    """Masa kerja from join_date up to and including end_date -> (years, months, days)."""
    stop = end_date + timedelta(days=1)
    total = (stop.year - join_date.year) * 12 + stop.month - join_date.month
    if add_months(join_date, total) > stop:
        total -= 1
    days = (stop - add_months(join_date, total)).days
    return total // 12, total % 12, days


def service_text(years, months, days=0):
    parts = ([f"{years} tahun"] if years else []) + ([f"{months} bulan"] if months else [])
    if not parts:
        parts = [f"{days} hari"]
    return " ".join(parts)


def pesangon_months(years):
    """Pasal 232 ayat 2: under 1 year 1 month ... 8 years or more 9 months."""
    return D(min(int(years) + 1, 9))


_UPMK = [(24, 10), (21, 8), (18, 7), (15, 6), (12, 5), (9, 4), (6, 3), (3, 2)]


def upmk_months(years):
    """Pasal 232 ayat 3."""
    for floor, months in _UPMK:
        if years >= floor:
            return D(months)
    return ZERO


def compensation_months(years, months, days):
    """Masa kerja in months (a part month counts by its days / 30), for uang kompensasi PKWT."""
    return D(years * 12 + months) + (D(days) / D(30)).quantize(D("0.01"))


# ── PP 68/2009 ──
TAX_BANDS = [(D(50_000_000), D("0")), (D(100_000_000), D("0.05")), (D(500_000_000), D("0.15")), (None, D("0.25"))]


def final_tax(gross):
    """-> (tax, steps); steps = [(from, to, rate, tax)] for the statement."""
    gross, low, tax, steps = D(gross), ZERO, ZERO, []
    for top, rate in TAX_BANDS:
        if gross <= low:
            break
        part = (min(gross, top) if top is not None else gross) - low
        t = rupiah(part * rate)
        steps.append((low, top, rate, t))
        tax += t
        if top is None:
            break
        low = top
    return tax, steps


def _band_text(low, top, rate):
    rp = lambda v: f"Rp {int(v):,}".replace(",", ".")
    span = f"di atas {rp(low)}" if top is None else (f"sampai {rp(top)}" if low == 0 else f"{rp(low)} s/d {rp(top)}")
    return f"{span}: {rate * 100:.0f}%"


# ── the calculation ──
@dataclass
class Inputs:
    reason: str
    join_date: Date
    end_date: Date
    upah: Decimal
    daily_divisor: int = 30
    leave_days: Decimal = ZERO
    travel: Decimal = ZERO                          # ongkos pulang
    other_items: list = field(default_factory=list)   # [{"label", "amount"}]
    separation_months: Decimal = D(1)
    overrides: dict = field(default_factory=dict)     # {key: {"amount": "...", "reason": "..."}}
    small_business: bool = False
    is_pkwt: bool = True


def _money(v):
    return str(rupiah(v))


def _num(v):
    """1.50 -> "1,5" (Indonesian decimal comma)."""
    return f"{D(v).normalize():f}".replace(".", ",")


def compute(i):
    """Inputs -> the statement (a JSON-ready dict). Raises ValueError on an unknown reason or bad dates."""
    reason = REASONS.get(i.reason)
    if reason is None:
        raise ValueError("Pilih alasan berakhirnya hubungan kerja.")
    if i.end_date < i.join_date:
        raise ValueError("Tanggal keluar sebelum tanggal masuk.")
    upah = rupiah(i.upah)
    years, months, days = service(i.join_date, i.end_date)
    per_day = rupiah(upah / D(i.daily_divisor or 30))
    lines, notes = [], []

    def add(key, label, law, basis, article):
        o = (i.overrides or {}).get(key) or {}
        amount = rupiah(D(str(o["amount"]))) if o.get("amount") not in (None, "") else rupiah(law)
        changed = amount != rupiah(law)
        lines.append({"key": key, "code": CODES[key.split(":")[0]], "label": label, "basis": basis,
                      "article": article, "law_amount": _money(law), "amount": _money(amount),
                      "changed": changed, "reason": (o.get("reason") or "") if changed else ""})

    if reason.pesangon:
        n = pesangon_months(years)
        mult = _num(reason.pesangon)
        add("pesangon", "Uang pesangon", upah * n * reason.pesangon,
            f"{mult} × {n} bulan upah", "Pasal 232 ayat 2")
    if reason.upmk:
        n = upmk_months(years)
        mult = _num(reason.upmk)
        if n:
            add("upmk", "Uang penghargaan masa kerja", upah * n * reason.upmk, f"{mult} × {n} bulan upah",
                "Pasal 232 ayat 3")
        else:
            notes.append("Uang penghargaan masa kerja: belum ada (masa kerja kurang dari 3 tahun).")
    if reason.compensation:
        n = compensation_months(years, months, days)
        add("compensation", "Uang kompensasi PKWT", upah * n / D(12), f"{_num(n)} bulan / 12 × upah",
            "Pasal 88 (rumus PP 35/2021, sementara)")
        if not i.is_pkwt:
            notes.append("Karyawan ini tidak tercatat PKWT di data Karyawan. Periksa jenis hubungan kerjanya.")
    if reason.separation:
        add("separation", "Uang pisah", upah * D(i.separation_months), f"{_num(i.separation_months)} bulan upah",
            "Pasal 233")
        if D(i.separation_months) < 1:
            notes.append(f"Uang pisah perusahaan {_num(i.separation_months)} bulan upah. Bila PK / PP / PKB tidak "
                         f"mengatur, UU menyebut paling sedikit 1 bulan (Pasal 233 ayat 2).")
    if reason.uph:
        if D(i.leave_days) > 0:
            add("uph_leave", "Uang penggantian hak: cuti tahunan belum diambil",           # G16-4.1: round once
                upah * D(i.leave_days) / D(i.daily_divisor or 30),
                f"{_num(i.leave_days)} hari × upah ÷ {int(i.daily_divisor or 30)}", "Pasal 232 ayat 4 huruf a")
        if D(i.travel) > 0:
            add("uph_travel", "Uang penggantian hak: ongkos pulang", D(i.travel), "diisi HR", "Pasal 232 ayat 4 huruf b")
        for n, item in enumerate(i.other_items or []):
            amount = D(str(item.get("amount") or 0))
            label = (item.get("label") or "").strip() or "Hak lain"
            if amount > 0:
                add(f"other:{n}", f"Uang penggantian hak: {label}", amount, "sesuai PK / PP / PKB",
                    "Pasal 232 ayat 4 huruf c")
    if reason.note:
        notes.append(reason.note)
    if i.small_business:
        notes.append("Usaha mikro / kecil: besaran sesuai kesepakatan dengan karyawan (Pasal 250). Angka UU sebagai "
                     "acuan.")
    if any(l["changed"] for l in lines):
        notes.append("Ada angka yang berbeda dari UU (diubah HR, dengan alasan).")

    total = sum((D(l["amount"]) for l in lines), ZERO)
    tax, steps = final_tax(total)
    return {
        "reason": reason.key, "reason_label": reason.label, "article": reason.article,
        "service": {"years": years, "months": months, "days": days, "text": service_text(years, months, days)},
        "upah": _money(upah), "per_day": _money(per_day), "daily_divisor": int(i.daily_divisor or 30),
        "lines": lines, "total": _money(total),
        "tax": {"amount": _money(tax), "steps": [{"text": _band_text(lo, hi, r), "tax": _money(t)}
                                                 for lo, hi, r, t in steps]},
        "net": _money(total - tax), "notes": notes,
    }


# ── service: defaults from the database, and the last payslip ──
def upah_for(employee, cfg, end_date):
    """Pasal 234 -> (upah, how it was found)."""
    from apps.employees.models import Employee
    base, allowance = D(employee.base_rate or 0), D(employee.fixed_allowance or 0)
    if employee.pay_type == Employee.PayType.DAILY:
        return rupiah(base * 30 + allowance), "30 × upah sehari (Pasal 234 ayat 2)"
    if employee.pay_type == Employee.PayType.PIECE:
        from .models import PayRunLine
        lines = list(PayRunLine.objects.filter(employee=employee, run__status="locked", run__period_end__lte=end_date,
                                               run__period_end__gt=end_date - timedelta(days=366))
                     .values_list("gross", flat=True))
        avg = rupiah(sum(lines, ZERO) / len(lines)) if lines else ZERO
        floor = rupiah(cfg.minimum_wage or 0)
        if avg < floor:
            return floor, "upah minimum (rata-rata 12 bulan lebih rendah, Pasal 234 ayat 4)"
        return avg, f"rata-rata {len(lines)} bulan terakhir (Pasal 234 ayat 3)"
    return rupiah(base + allowance), "gaji pokok + tunjangan tetap (Pasal 234 ayat 1)"


def leave_left(employee, end_date):
    from apps.leave.services import annual_balance
    try:
        return D(annual_balance(employee, end_date)["left"])
    except Exception:                       # no leave data yet: HR types it
        return ZERO


def run_for(employee, end_date):
    """The draft payroll whose period holds the last day of work (where hak akhir is paid)."""
    from .models import PayRun
    return (PayRun.objects.filter(organization=employee.organization, period_start__lte=end_date,
                                  period_end__gte=end_date).first())


def loan_balance(employee, run=None):
    """What is still owed on active loans: before `run` when given (its own instalment not yet counted)."""
    from django.db.models import Sum
    from .loans import balance_before
    from .models import EmployeeLoan, PayRunItem
    total = ZERO
    for loan in EmployeeLoan.objects.filter(employee=employee, status=EmployeeLoan.Status.ACTIVE):
        if run is not None:
            total += balance_before(loan, run)
        else:
            paid = PayRunItem.objects.filter(loan=loan).aggregate(s=Sum("amount"))["s"] or ZERO
            total += max(ZERO, loan.amount - paid)
    return rupiah(total)


class AttachError(Exception):
    pass


def attach(record, cfg):
    """Put the hak akhir on the leaver's payslip in the draft payroll that holds the last day; fill the employee's
    end date; pay off loans when HR ticked it. Replaces what an earlier attach put there. -> the run."""
    from .loans import balance_before, sync_line
    from .models import PayRunItem, PayRunLine
    from .payrun import calculate_line
    employee = record.employee
    run = run_for(employee, record.end_date)
    if run is None:
        raise AttachError(f"Belum ada payroll untuk periode yang berisi tanggal keluar {record.end_date:%d-%m-%Y}. "
                          f"Buat payroll periode itu dulu.")
    if run.is_locked:
        raise AttachError(f"{run.name} sudah dikunci. Hak akhir tidak bisa dimasukkan ke slip.")
    line = PayRunLine.objects.filter(run=run, employee=employee).first()
    if line is None:
        raise AttachError(f"{employee.full_name} tidak ada di {run.name}.")
    result = record.result or {}
    PayRunItem.objects.filter(line=line).filter(code__startswith=PREFIX).delete()
    PayRunItem.objects.filter(line=line, code=TAX_CODE).delete()
    for l in result.get("lines", []):
        if D(l["amount"]) > 0:
            PayRunItem.objects.create(organization=line.organization, line=line, kind=PayRunItem.Kind.EARNING,
                                      code=l["code"], label=l["label"][:80], amount=D(l["amount"]),
                                      note="Hak akhir")
    tax = D((result.get("tax") or {}).get("amount") or 0)
    if tax > 0:
        PayRunItem.objects.create(organization=line.organization, line=line, kind=PayRunItem.Kind.DEDUCTION,
                                  code=TAX_CODE, label=TAX_LABEL, amount=tax, note="Hak akhir")
    if employee.end_date != record.end_date:
        employee.end_date = record.end_date
        employee.save(update_fields=["end_date"])
    sync_line(line, run)
    if record.deduct_loan:
        for item in PayRunItem.objects.filter(line=line, loan__isnull=False).select_related("loan"):
            before = balance_before(item.loan, run)
            if item.amount != before:
                item.amount = before
                item.save(update_fields=["amount"])
        sync_line(line, run)
    calculate_line(line, cfg).save()
    return run


def detach(record):
    """Take the hak akhir off a draft payslip (the record is being deleted). Locked payrolls are never changed."""
    from .models import PayRunItem, PayRunLine
    from .payrun import calculate_line
    from .models import PayrollSettings
    run = record.run
    if run is None:
        return
    if run.is_locked:
        raise AttachError(f"{run.name} sudah dikunci. Hak akhir di slip itu tidak bisa dihapus.")
    line = PayRunLine.objects.filter(run=run, employee=record.employee).first()
    if line is None:
        return
    PayRunItem.objects.filter(line=line).filter(code__startswith=PREFIX).delete()
    PayRunItem.objects.filter(line=line, code=TAX_CODE).delete()
    calculate_line(line, PayrollSettings.for_org(run.organization)).save()
