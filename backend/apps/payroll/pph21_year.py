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

Pure parts at the top (tested without a database): parse_amount, parse_opening_csv, tax_month, withheld_from_slip,
parse_month, opening_checks.

G16-5b (26 Nov 2026, D77): a saldo awal says which masa it covers (masa_from..masa_to). Checked against the masa of
the person's own SeeGaji payrolls: an overlap is red (that person's yearly PPh 21 waits until it is fixed), a gap,
a start before the join month, or a saldo awal with only a count of months are amber.
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
TEMPLATE_HEADER = ["no_karyawan", "nama", "masa_dari", "masa_sampai", "bulan", "bruto", "pph21", "iuran_jht_jp"]
_ALIASES = {
    "no_karyawan": ("no_karyawan", "no karyawan", "no. karyawan", "nomor karyawan", "employee_no", "nik karyawan"),
    "nama": ("nama", "nama karyawan", "name"),
    "masa_dari": ("masa_dari", "masa dari", "dari masa", "masa awal", "bulan dari"),            # G16-5b
    "masa_sampai": ("masa_sampai", "masa sampai", "sampai masa", "masa akhir", "bulan sampai"),
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


_MONTH_WORDS = {w: i + 1 for i, names in enumerate([
    ("jan", "januari", "january"), ("feb", "februari", "pebruari", "february"), ("mar", "maret", "march"),
    ("apr", "april"), ("mei", "may"), ("jun", "juni", "june"), ("jul", "juli", "july"),
    ("agu", "agt", "agus", "agustus", "aug", "august"), ("sep", "sept", "september"),
    ("okt", "oktober", "oct", "october"), ("nov", "nopember", "november"), ("des", "desember", "dec", "december"),
]) for w in names}


def parse_month(text):
    """G16-5b: '9', '09', 'Sep', 'September', '9/2026', 'Sep 2026' -> 9; '' -> None; anything else -> 0 (bad)."""
    s = str(text if text is not None else "").strip().lower()
    if not s:
        return None
    s = re.split(r"[\s/\-.]+", s)[0]
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 12 else 0
    return _MONTH_WORDS.get(s, 0)


def range_text(masa_from, masa_to, year=None):
    """'Jan–Sep 2026', 'Sep 2026', or '' when there is no range."""
    if not masa_from or not masa_to:
        return ""
    text = MONTHS[masa_from - 1] if masa_from == masa_to else f"{MONTHS[masa_from - 1]}–{MONTHS[masa_to - 1]}"
    return f"{text} {year}" if year else text


def _month_list(months):
    names = [MONTHS_LONG[m - 1] for m in months]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " dan " + names[-1]


def opening_checks(masa_from, masa_to, months, seegaji_months, join_month=None):
    """
    G16-5b (D77): one saldo awal against the masa of the person's own SeeGaji payrolls in the same year.
      masa_from/masa_to  the range (1-12) or None;  months  the count kept with it
      seegaji_months     the masa months (1-12) of the payrolls this person has a slip in
      join_month         the join month when they joined in that year, else None
    -> [{"kind", "level", "text"}]: overlap (red: the yearly PPh 21 waits), gap / before_join / no_range (amber).
    """
    out, seegaji = [], sorted(set(seegaji_months or ()))
    if not masa_from or not masa_to:
        if months:
            out.append({"kind": "no_range", "level": "amber",
                        "text": "Rentang masa belum diisi (hanya jumlah bulan): tumpang tindih belum bisa dicek."})
        return out
    covered = range(masa_from, masa_to + 1)
    both = [m for m in seegaji if m in covered]
    if both:
        out.append({"kind": "overlap", "level": "red",
                    "text": f"Masa {_month_list(both)} ada di saldo awal dan di payroll SeeGaji. Perbaiki rentang "
                            f"saldo awal; sampai itu PPh 21 setahun orang ini belum dihitung."})
    if seegaji and masa_to < seegaji[0] - 1:
        missing = list(range(masa_to + 1, seegaji[0]))
        if join_month:
            missing = [m for m in missing if m >= join_month]
        if missing:
            out.append({"kind": "gap", "level": "amber",
                        "text": f"Masa {_month_list(missing)} tidak ada di saldo awal maupun di payroll SeeGaji."})
    if join_month and masa_from < join_month:
        out.append({"kind": "before_join", "level": "amber",
                    "text": f"Saldo awal mulai {MONTHS_LONG[masa_from - 1]}, padahal masuk kerja "
                            f"{MONTHS_LONG[join_month - 1]}."})
    return out


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
    G16-5b: optional "masa_dari" / "masa_sampai" (1-12 or Jan..Des). With them "bulan" may be empty (it is the
    range); when both are filled they must agree. Rows also carry "masa_from" / "masa_to" (None without a range).
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
    ranged = "masa_dari" in cols and "masa_sampai" in cols
    missing = [k for k in ("no_karyawan",) + (() if ranged else ("bulan",)) if k not in cols]
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
        masa_from, masa_to = parse_month(get("masa_dari")), parse_month(get("masa_sampai"))
        if masa_from == 0 or masa_to == 0:
            errors.append("masa_dari / masa_sampai harus bulan 1 sampai 12 (atau Jan sampai Des)")
            masa_from = masa_to = None
        elif (masa_from is None) != (masa_to is None):
            errors.append("isi masa_dari dan masa_sampai, atau kosongkan keduanya")
            masa_from = masa_to = None
        elif masa_from and masa_from > masa_to:
            errors.append("masa_dari sesudah masa_sampai")
            masa_from = masa_to = None
        span = masa_to - masa_from + 1 if masa_from else None
        months_text = get("bulan")
        months = int(months_text) if months_text.isdigit() else None
        if months is None and not months_text and span:
            months = span
        if months is None or not 0 <= months <= 12:
            errors.append("bulan harus 0 sampai 12")
        elif span and months != span:
            errors.append(f"bulan ({months}) tidak sama dengan masa {range_text(masa_from, masa_to)} ({span} bulan)")
        amounts = {}
        for k, out in (("bruto", "bruto"), ("pph21", "pph"), ("iuran_jht_jp", "iuran")):
            v = parse_amount(get(k))
            if v is None or v < 0:
                errors.append(f"{k} bukan angka rupiah")
                v = ZERO
            amounts[out] = v
        rows.append({"line": n, "employee_no": no, "name": get("nama"), "months": months or 0, **amounts,
                     "masa_from": masa_from, "masa_to": masa_to, "errors": errors})
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
    problem: str = ""                        # G16-5b: why the year is not settled (an overlap), for the slip
    seegaji_months: set = field(default_factory=set)


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


def person_months(runs, cfg, rule_list=None):
    """G16-5b: {employee_id: {masa month, ...}} for the pay runs given (each run's own masa)."""
    from .models import PayRunLine
    month_of = {r.pk: run_masa(r, cfg, rule_list)[1] for r in runs}
    out = {}
    for emp_id, run_id in PayRunLine.objects.filter(run__in=[r.pk for r in runs]).values_list("employee_id", "run_id"):
        out.setdefault(emp_id, set()).add(month_of[run_id])
    return out


def join_month(employee, year):
    """The join month when the employee joined in `year`, else None."""
    j = getattr(employee, "join_date", None)
    return j.month if j and j.year == year else None


def apply_opening_checks(row, year):
    """G16-5b: the saldo-awal checks on a YearRow (needs row.opening and row.seegaji_months). Red blocks the year."""
    o = row.opening
    if o is None:
        return []
    found = opening_checks(o.masa_from, o.masa_to, o.months, row.seegaji_months, join_month(row.employee, year))
    for c in found:
        if c["level"] == "red":
            row.incomplete, row.problem = True, c["text"]
            row.notes.insert(0, "TUMPANG TINDIH: " + c["text"])
        else:
            row.notes.append(c["text"])
    return found


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
    rule_list = rules(cfg)
    for run in runs:
        on = run.pay_date or run.period_end
        run_month = run_masa(run, cfg, rule_list)[1]
        for line in run.lines.select_related("employee"):
            e = line.employee
            r = rows.setdefault(e.pk, YearRow(e))
            r.seegaji_months.add(run_month)                                          # G16-5b
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
        apply_opening_checks(r, year)                                                  # G16-5b
        if r.incomplete:                                       # an overlap: shown, not calculated, not in the totals
            out.append(r)
            continue
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
