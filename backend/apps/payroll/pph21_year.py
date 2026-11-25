# =============================================================================
# === backend/apps/payroll/pph21_year.py ===
# =============================================================================
"""
G16-2 (21 Nov 2026) — PPh 21 for the whole year (Pasal 17), still switched off.

  saldo awal (Pph21Opening: the tax months before SeeGaji, from the old book or Coretax)
+ the SeeGaji pay runs whose masa pajak falls in that year (Pengaturan payroll -> "Masa pajak ikut")
= bruto, months and the employee's JHT/JP for the year -> pph21.annual_pph -> minus what was withheld.

The payroll whose masa pajak is December settles the year; its own monthly TER is not counted as withheld.
Tax paid by the company is grossed up in that month too (annual_gross_up).

Pure parts at the top (tested without a database): parse_amount, parse_opening_csv, tax_month, withheld_from_slip.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import pph21 as P

ZERO = Decimal("0")
PAID, PERIOD_END, EARLIEST = "paid", "period_end", "earliest"
# G16-5a (D76): the law is "whichever comes first" (PMK 168/2023 Pasal 19: terutang pada saat dibayar atau saat
# terutangnya penghasilan); the two others are a company's own choice, shown as such
MODE_LABELS = {EARLIEST: "yang lebih dulu: dibayar atau periode selesai (PMK 168 Pasal 19)",
               PERIOD_END: "bulan periode berakhir", PAID: "bulan dibayar"}
MONTHS_LONG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
               "November", "Desember"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
TEMPLATE_HEADER = ["no_karyawan", "nama", "bulan", "bruto", "pph21", "iuran_jht_jp"]
_ALIASES = {
    "no_karyawan": ("no_karyawan", "no karyawan", "no. karyawan", "nomor karyawan", "employee_no", "nik karyawan"),
    "nama": ("nama", "nama karyawan", "name"),
    "bulan": ("bulan", "jumlah bulan", "months"),
    "bruto": ("bruto", "penghasilan bruto", "total bruto"),
    "pph21": ("pph21", "pph 21", "pph", "pph21 dipotong", "pph 21 dipotong"),
    "iuran_jht_jp": ("iuran_jht_jp", "iuran", "iuran jht jp", "jht jp", "iuran pensiun"),
}


# ── pure ─────────────────────────────────────────────────────────────────────

def parse_amount(text):
    """'Rp 1.234.567' / '1,234,567' / '1234567' / '' -> Decimal rupiah. Anything with a letter other than Rp -> None."""
    s = str(text if text is not None else "").strip()
    if s in ("", "-"):
        return ZERO
    s = re.sub(r"^rp\.?", "", s, flags=re.I).strip()
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = re.sub(r"[\s().\-]", "", s)
    if "," in s:                                    # 1,234,567 (thousands) or 1234,50 (decimal, cents dropped)
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + ("" if len(tail) <= 2 else tail)
    if not s.isdigit():
        return None
    return -Decimal(s) if negative else Decimal(s)


def _key(header):
    h = re.sub(r"\s+", " ", str(header or "").strip().lower().replace("_", " "))
    for key, names in _ALIASES.items():
        if h in (n.replace("_", " ") for n in names):
            return key
    return None


def decode(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_opening_csv(text):
    """
    The saldo-awal CSV (';' or ',' separated, as Excel saves it) -> rows:
      {"line", "employee_no", "name", "months", "bruto", "pph", "iuran", "errors": [..]}
    Columns by name (see _ALIASES); "no_karyawan" and "bulan" are required, the rest default to 0.
    """
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = next(reader, None)
    if not header:
        return [], ["File kosong."]
    cols = {}
    for i, h in enumerate(header):
        k = _key(h)
        if k and k not in cols:
            cols[k] = i
    missing = [k for k in ("no_karyawan", "bulan") if k not in cols]
    if missing:
        return [], [f"Kolom wajib tidak ada: {', '.join(missing)}. Pakai template dari halaman ini."]
    rows = []
    for n, rec in enumerate(reader, start=2):
        if not any(c.strip() for c in rec):
            continue
        get = lambda k: rec[cols[k]].strip() if k in cols and cols[k] < len(rec) else ""
        errors = []
        no = get("no_karyawan")
        if not no:
            errors.append("no_karyawan kosong")
        months_text = get("bulan")
        months = int(months_text) if months_text.isdigit() else None
        if months is None or not 0 <= months <= 12:
            errors.append("bulan harus 0 sampai 12")
        amounts = {}
        for k, out in (("bruto", "bruto"), ("pph21", "pph"), ("iuran_jht_jp", "iuran")):
            v = parse_amount(get(k))
            if v is None or v < 0:
                errors.append(f"{k} bukan angka rupiah")
                v = ZERO
            amounts[out] = v
        rows.append({"line": n, "employee_no": no, "name": get("nama"), "months": months or 0, **amounts,
                     "errors": errors})
    return rows, []


def tax_month(period_end, pay_date, mode):
    """
    (year, month) of a pay run's masa pajak. earliest (the law, G16-5a): the earlier of the pay date and the period
    end; paid: the month it is paid; period_end: the month its period ends. No pay date: the period end.
    """
    if mode == PAID and pay_date:
        d = pay_date
    elif mode == EARLIEST and pay_date:
        d = min(pay_date, period_end)
    else:
        d = period_end
    return d.year, d.month


def masa_text(year, month):
    return f"{MONTHS[month - 1]} {year}"


def masa_long(year, month):
    return f"{MONTHS_LONG[month - 1]} {year}"


# ── G16-5a: which rule a pay run follows (dated, so a change never moves an earlier payroll) ──

def rules(cfg):
    """[(since or None, mode)] in date order: the history (earlier rules), then the rule in force now."""
    out = []
    for h in (getattr(cfg, "pph21_tax_month_history", None) or []):
        since = h.get("since")
        out.append((_date(since), h.get("mode") or PAID))
    out.append((getattr(cfg, "pph21_tax_month_since", None), cfg.pph21_tax_month))
    out.sort(key=lambda r: (r[0] is not None, r[0] or 0))
    return out


def _date(value):
    from datetime import date
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def mode_for(cfg, period_end, rule_list=None):
    """The rule a period follows: the latest one whose "berlaku sejak" is on or before the period's end."""
    chosen = None
    for since, mode in (rule_list if rule_list is not None else rules(cfg)):
        if since is None or since <= period_end:
            chosen = mode
    return chosen or PAID


def run_masa(run, cfg, rule_list=None):
    """(year, month, frozen) of a pay run: the masa frozen when it was locked, else what its rule gives."""
    if getattr(run, "masa_year", None) and getattr(run, "masa_month", None):
        return run.masa_year, run.masa_month, True
    y, m = tax_month(run.period_end, run.pay_date, mode_for(cfg, run.period_end, rule_list))
    return y, m, False


def masa_checks(runs, cfg, rule_list=None):
    """
    Pay runs in period order -> warnings [{"kind", "masa", "text"}]: a masa holding two payrolls ("double"), or a
    month left without any between two payrolls ("gap"). Never blocks; HR sees it before and after a change.
    """
    seen, out, prev = {}, [], None
    for r in sorted(runs, key=lambda r: r.period_start):
        y, m, _ = run_masa(r, cfg, rule_list)
        seen.setdefault((y, m), []).append(r.name)
        if prev is not None:
            step = (y - prev[0]) * 12 + (m - prev[1])
            for k in range(1, step):
                gy, gm = divmod(prev[1] - 1 + k, 12)
                miss = (prev[0] + gy, gm + 1)
                out.append({"kind": "gap", "masa": masa_text(*miss),
                            "text": f"Masa {masa_long(*miss)} tidak berisi payroll mana pun."})
        prev = (y, m)
    for (y, m), names in seen.items():
        if len(names) > 1:
            out.append({"kind": "double", "masa": masa_text(y, m),
                        "text": f"Masa {masa_long(y, m)} berisi {len(names)} payroll: {', '.join(names)}."})
    out.sort(key=lambda w: (w["masa"][-4:], MONTHS.index(w["masa"][:3]), w["kind"]))
    return out


def withheld_from_slip(result):
    """PPh 21 actually taken on a slip (a 'pph21' line or an item called PPh), or None when there is none."""
    found = None
    for d in (result or {}).get("deductions", []):
        text = f"{d.get('code') or ''} {d.get('label') or ''}".lower()
        if d.get("code") == "pph21_final":                               # G16-4: final tax on hak akhir
            continue
        if d.get("code") in ("pph21", "pph_21") or "pph" in text or "pajak" in text:
            found = (found or ZERO) + Decimal(str(d.get("amount") or 0))
    return found


def iuran_from_slip(result, *, company_jht_in_bruto=True, company_jp_in_bruto=True):
    """The employee's JHT 2% + JP 1% for the yearly deduction: taken from pay, or paid by the company when it is
    counted in bruto (it is the employee's contribution either way)."""
    ded = {d.get("code"): Decimal(str(d.get("amount") or 0)) for d in (result or {}).get("deductions", [])}
    emp = {e.get("code"): Decimal(str(e.get("amount") or 0)) for e in (result or {}).get("employer", [])}
    total = ded.get("jht_employee", ZERO) + ded.get("jp_employee", ZERO)
    if company_jht_in_bruto:
        total += emp.get("jht_employee_company", ZERO)
    if company_jp_in_bruto:
        total += emp.get("jp_employee_company", ZERO)
    return total


def annual_gross_up(bruto_year, months, iuran_year, ptkp, withheld, on=None, max_rounds=60):
    """
    Tax paid by the company, settled in the last month: the allowance T added to bruto must cover what is still
    due on bruto + T (equal to it, or a few rupiah above when the thousands rounding makes it bounce).
    -> (Annual, T). T is never negative (a refund is not an allowance).
    """
    due = lambda t: P.annual_pph(Decimal(bruto_year) + t, months, iuran_year, ptkp, withheld, on)
    t, seen = ZERO, []
    for _ in range(max_rounds):
        nt = max(due(t).due, ZERO)
        if nt == t:
            return due(t), t
        if nt in seen:                     # PKP is rounded down to thousands: it can bounce between two values;
            t = max(seen[seen.index(nt):] + [t])          # take the higher one, so the allowance covers the tax
            return due(t), t
        seen.append(t)
        t = nt
    return due(t), t


# ── the database ─────────────────────────────────────────────────────────────

@dataclass
class YearRow:
    employee: object
    opening: object = None
    months: int = 0
    bruto: Decimal = ZERO
    iuran: Decimal = ZERO
    withheld: Decimal = ZERO
    december_ter: Decimal = ZERO             # the monthly TER the December payroll would have taken (for comparison)
    in_december: bool = False
    annual: object = None
    allowance: Decimal = ZERO                # gross-up in the December payroll (tax paid by the company)
    notes: list = field(default_factory=list)
    incomplete: bool = False                 # G16-2.1: worked before SeeGaji this year but no saldo awal yet


def plan_masa_change(runs, cfg, new_mode, new_since):
    """
    G16-5a (D80): what changing the masa rule would do, before anything is saved.
    runs: every pay run of the company (locked ones carry their frozen masa, see freeze_locked).
    -> {"history", "rules", "moves": [{"run", "before", "after"}], "warnings": [...]}
    The old rule becomes history from its own "since" up to the new one; rules starting on or after the new
    "since" are superseded. No "since" = the new rule for every period (only frozen payrolls keep their masa).
    """
    old_rules = rules(cfg)
    history = [h for h in (getattr(cfg, "pph21_tax_month_history", None) or [])]
    if new_since is None:
        history = []
    else:
        if new_mode != cfg.pph21_tax_month or (cfg.pph21_tax_month_since or None) != new_since:
            old_since = getattr(cfg, "pph21_tax_month_since", None)
            history.append({"mode": cfg.pph21_tax_month, "since": old_since.isoformat() if old_since else None})
        history = [h for h in history if _date(h.get("since")) is None or _date(h.get("since")) < new_since]
    new_rules = sorted([(_date(h.get("since")), h.get("mode") or PAID) for h in history] + [(new_since, new_mode)],
                       key=lambda r: (r[0] is not None, r[0] or 0))
    moves = []
    for r in sorted(runs, key=lambda r: r.period_start):
        before, after = run_masa(r, cfg, old_rules)[:2], run_masa(r, cfg, new_rules)[:2]
        if before != after:
            moves.append({"run": r.name, "before": masa_text(*before), "after": masa_text(*after)})
    warnings = [w for w in masa_checks(runs, cfg, new_rules) if w not in masa_checks(runs, cfg, old_rules)]
    if new_since is not None and new_since.month != 1:
        warnings.insert(0, {"kind": "midyear", "masa": masa_text(new_since.year, new_since.month),
                            "text": f"Aturan baru mulai di tengah tahun ({masa_long(new_since.year, new_since.month)}): "
                                    f"periksa masa yang berisi dua payroll atau kosong di bawah ini."})
    return {"history": history, "rules": new_rules, "moves": moves, "warnings": warnings}


def freeze_locked(organization, cfg):
    """Locked payrolls keep the masa they were locked (and reported) with, whatever the rule becomes."""
    from .models import PayRun
    rule_list = rules(cfg)
    for r in PayRun.objects.filter(organization=organization, status=PayRun.Status.LOCKED,
                                   masa_year__isnull=True):
        r.masa_year, r.masa_month, _ = run_masa(r, cfg, rule_list)
        r.save(update_fields=["masa_year", "masa_month"])


def year_runs(organization, year, cfg):
    """The pay runs whose masa falls in `year` and the one whose masa is December (G16-5a: by each run's rule)."""
    from .models import PayRun
    rule_list = rules(cfg)
    runs, december = [], None
    for r in PayRun.objects.filter(organization=organization).order_by("period_start"):
        y, m, _ = run_masa(r, cfg, rule_list)
        if y == year:
            runs.append(r)
            if m == 12 and december is None:
                december = r
    return runs, december


def year_rows(organization, year):
    """Everyone with a saldo awal or a SeeGaji slip in that tax year -> [YearRow], plus the runs and the December run."""
    from .models import PayrollSettings, Pph21Opening
    cfg = PayrollSettings.for_org(organization)
    runs, december = year_runs(organization, year, cfg)
    rows = {}
    for o in Pph21Opening.objects.filter(organization=organization, year=year).select_related("employee"):
        r = rows.setdefault(o.employee_id, YearRow(o.employee))
        r.opening = o
        r.months += o.months
        r.bruto += o.bruto
        r.iuran += o.iuran
        r.withheld += o.pph
    for run in runs:
        on = run.pay_date or run.period_end
        for line in run.lines.select_related("employee"):
            e = line.employee
            r = rows.setdefault(e.pk, YearRow(e))
            try:
                plain = P.monthly_for_slip(line.result, e.ptkp_status, by_company=False,
                                           late_reduces=cfg.pph21_late_reduces_bruto,
                                           company_jht_in_bruto=cfg.pph21_company_jht_in_bruto,
                                           company_jp_in_bruto=cfg.pph21_company_jp_in_bruto, on=on)
                m = P.monthly_for_slip(line.result, e.ptkp_status, by_company=e.pph21_by_company,
                                       late_reduces=cfg.pph21_late_reduces_bruto,
                                       company_jht_in_bruto=cfg.pph21_company_jht_in_bruto,
                                       company_jp_in_bruto=cfg.pph21_company_jp_in_bruto, on=on)
            except ValueError as err:
                r.notes.append(str(err))
                continue
            r.months += 1
            r.iuran += iuran_from_slip(line.result, company_jht_in_bruto=cfg.pph21_company_jht_in_bruto,
                                       company_jp_in_bruto=cfg.pph21_company_jp_in_bruto)
            if run is december:                       # settled by the year: no monthly gross-up, no monthly TER
                r.in_december = True
                r.bruto += plain.bruto
                r.december_ter = m.tax
                continue
            r.bruto += m.bruto                         # includes that month's tax allowance when grossed up
            taken = withheld_from_slip(line.result)
            if taken is None:                          # G16-3: a PPh line on the slip is what was withheld
                r.withheld += m.tax
                if "PPh bulan SeeGaji = perkiraan TER" not in r.notes:
                    r.notes.append("PPh bulan SeeGaji = perkiraan TER")
            else:
                r.withheld += taken
    out = []
    for r in rows.values():
        e = r.employee
        if r.months > 12:
            r.notes.append(f"{r.months} bulan: saldo awal tumpang tindih dengan payroll SeeGaji?")
        first = runs[0].period_start if runs else None                                 # G16-2.1
        if r.opening is None:
            if first and e.join_date and e.join_date < first:
                r.incomplete = True
                r.notes.insert(0, "BELUM LENGKAP: isi saldo awal")
            else:
                r.notes.append("saldo awal tidak perlu (masuk di bulan SeeGaji)")
        try:
            if e.pph21_by_company and r.in_december:
                r.annual, r.allowance = annual_gross_up(r.bruto, min(r.months, 12) or 1, r.iuran, e.ptkp_status,
                                                        r.withheld)
                r.notes.append("ditanggung perusahaan, gross-up di Desember")
            else:
                r.annual = P.annual_pph(r.bruto, min(r.months, 12) or 1, r.iuran, e.ptkp_status, r.withheld)
        except ValueError as err:
            r.notes.append(str(err))
            continue
        if getattr(e, "status", "") == "resigned":
            r.notes.append("sudah keluar: hitung setahun di bulan terakhirnya")
        out.append(r)
    out.sort(key=lambda r: r.employee.full_name.lower())
    return out, runs, december, cfg
