# =============================================================================
# === backend/apps/payroll/pph21.py ===
# =============================================================================
"""
G16-0 (19 Nov 2026) — PPh 21 for employees, pure functions (no database). Not used by the payroll yet: the
preview command (pph21_preview) shows what slips would pay; G16-1 wires it in after Pak Holan's answers.

Source: DJP "Cermat Pemotongan PPh Pasal 21/26" (Jan 2024; PP 58/2023, PMK 168/2023), checked on DKCB's October
2026 book: Arief 44.982, Joko 76.243, Togar 140.000, Anthony 151.785, Midun 15.638 all reproduce.
  * Jan-Nov: PPh = bruto of the month x TER of its category (A / B / C by PTKP status), rounded half up.
  * Bruto: every earning (cash meal money, overtime, incentives included) + JKK + JKM (+ BPJS Kesehatan) paid by
    the company; unpaid leave reduces it (Togar). JHT / JP paid by the company are not bruto.
  * December or the last month: the year at Pasal 17 rates, minus what Jan-Nov already took.
Every table has a "berlaku sejak" date: a rule that changes later never moves a month already paid.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
ZERO = D("0")
SINCE_2024 = date(2024, 1, 1)


def _table(rows):
    """[(upper bound in rupiah or None, rate %), ...] -> [(Decimal or None, Decimal fraction)]."""
    return [(D(up) if up is not None else None, D(rate) / 100) for up, rate in rows]


# PP 58/2023 Lampiran: monthly TER. Each row: the upper bound of the bracket (inclusive), the rate in percent.
_A = [(5_400_000, "0"), (5_650_000, "0.25"), (5_950_000, "0.5"), (6_300_000, "0.75"), (6_750_000, "1"),
      (7_500_000, "1.25"), (8_550_000, "1.5"), (9_650_000, "1.75"), (10_050_000, "2"), (10_350_000, "2.25"),
      (10_700_000, "2.5"), (11_050_000, "3"), (11_600_000, "3.5"), (12_500_000, "4"), (13_750_000, "5"),
      (15_100_000, "6"), (16_950_000, "7"), (19_750_000, "8"), (24_150_000, "9"), (26_450_000, "10"),
      (28_000_000, "11"), (30_050_000, "12"), (32_400_000, "13"), (35_400_000, "14"), (39_100_000, "15"),
      (43_850_000, "16"), (47_800_000, "17"), (51_400_000, "18"), (56_300_000, "19"), (62_200_000, "20"),
      (68_600_000, "21"), (77_500_000, "22"), (89_000_000, "23"), (103_000_000, "24"), (125_000_000, "25"),
      (157_000_000, "26"), (206_000_000, "27"), (337_000_000, "28"), (454_000_000, "29"), (550_000_000, "30"),
      (695_000_000, "31"), (910_000_000, "32"), (1_400_000_000, "33"), (None, "34")]
_B = [(6_200_000, "0"), (6_500_000, "0.25"), (6_850_000, "0.5"), (7_300_000, "0.75"), (9_200_000, "1"),
      (10_750_000, "1.5"), (11_250_000, "2"), (11_600_000, "2.5"), (12_600_000, "3"), (13_600_000, "4"),
      (14_950_000, "5"), (16_400_000, "6"), (18_450_000, "7"), (21_850_000, "8"), (26_000_000, "9"),
      (27_700_000, "10"), (29_350_000, "11"), (31_450_000, "12"), (33_950_000, "13"), (37_100_000, "14"),
      (41_100_000, "15"), (45_800_000, "16"), (49_500_000, "17"), (53_800_000, "18"), (58_500_000, "19"),
      (64_000_000, "20"), (71_000_000, "21"), (80_000_000, "22"), (93_000_000, "23"), (109_000_000, "24"),
      (129_000_000, "25"), (163_000_000, "26"), (211_000_000, "27"), (374_000_000, "28"), (459_000_000, "29"),
      (555_000_000, "30"), (704_000_000, "31"), (957_000_000, "32"), (1_405_000_000, "33"), (None, "34")]
_C = [(6_600_000, "0"), (6_950_000, "0.25"), (7_350_000, "0.5"), (7_800_000, "0.75"), (8_850_000, "1"),
      (9_800_000, "1.25"), (10_950_000, "1.5"), (11_200_000, "1.75"), (12_050_000, "2"), (12_950_000, "3"),
      (14_150_000, "4"), (15_550_000, "5"), (17_050_000, "6"), (19_500_000, "7"), (22_700_000, "8"),
      (26_600_000, "9"), (28_100_000, "10"), (30_100_000, "11"), (32_600_000, "12"), (35_400_000, "13"),
      (38_900_000, "14"), (43_000_000, "15"), (47_400_000, "16"), (51_200_000, "17"), (55_800_000, "18"),
      (60_400_000, "19"), (66_700_000, "20"), (74_500_000, "21"), (83_200_000, "22"), (95_600_000, "23"),
      (110_000_000, "24"), (134_000_000, "25"), (169_000_000, "26"), (221_000_000, "27"), (390_000_000, "28"),
      (463_000_000, "29"), (561_000_000, "30"), (709_000_000, "31"), (965_000_000, "32"), (1_419_000_000, "33"),
      (None, "34")]

# dated: (berlaku sejak, tables). The newest one not after the pay date wins.
TER_TABLES = [(SINCE_2024, {"A": _table(_A), "B": _table(_B), "C": _table(_C)})]
CATEGORY = {"TK/0": "A", "TK/1": "A", "K/0": "A", "TK/2": "B", "TK/3": "B", "K/1": "B", "K/2": "B", "K/3": "C"}

# PTKP (PMK 101/2016, unchanged in the 2024 book): 54 jt + 4,5 jt married + 4,5 jt per dependant (max 3)
PTKP_TABLES = [(date(2016, 1, 1), {"base": D(54_000_000), "married": D(4_500_000), "dependant": D(4_500_000)})]
# Pasal 17 (UU HPP, from 2022): (upper bound of the layer or None, rate)
PASAL17_TABLES = [(date(2022, 1, 1), [(D(60_000_000), D("0.05")), (D(250_000_000), D("0.15")),
                                      (D(500_000_000), D("0.25")), (D(5_000_000_000), D("0.30")), (None, D("0.35"))])]
BIAYA_JABATAN_RATE, BIAYA_JABATAN_MONTH = D("0.05"), D(500_000)
DAILY_TABLES = [(SINCE_2024, [(D(450_000), ZERO), (D(2_500_000), D("0.005"))])]


def _dated(tables, on):
    on = on or date.today()
    chosen = None
    for since, value in sorted(tables, key=lambda t: t[0]):
        if since <= on:
            chosen = value
    if chosen is None:
        raise ValueError(f"Tidak ada tarif yang berlaku pada {on}.")
    return chosen


def rupiah(x):
    """Half up to the rupiah (the book: 0,75% x 5.997.600 = 44.982)."""
    return D(x).quantize(D("1"), rounding=ROUND_HALF_UP)


def ter_category(ptkp):
    try:
        return CATEGORY[str(ptkp).strip().upper().replace(" ", "")]
    except KeyError:
        raise ValueError(f"Status PTKP tidak dikenal: {ptkp!r}")


def ter_rate(category, bruto, on=None):
    for upper, rate in _dated(TER_TABLES, on)[category]:
        if upper is None or D(bruto) <= upper:
            return rate
    raise AssertionError("TER table without a last open bracket")


def monthly_pph(bruto, ptkp, on=None):
    """Jan-Nov: (rate, PPh) for one month's bruto."""
    if D(bruto) <= 0:
        return ZERO, ZERO
    rate = ter_rate(ter_category(ptkp), bruto, on)
    return rate, rupiah(D(bruto) * rate)


def gross_up(bruto, ptkp, on=None, max_rounds=50):
    """
    Company-borne tax treated as income (DJP book p. 76): the T for which T = TER(bruto + T) x (bruto + T).
    -> (rate, T). Converges in a few rounds; at a bracket edge it settles on the higher, safe side.
    """
    cat = ter_category(ptkp)
    tax, seen = ZERO, set()
    for _ in range(max_rounds):
        rate = ter_rate(cat, D(bruto) + tax, on)
        nxt = rupiah((D(bruto) + tax) * rate)
        if nxt == tax:
            return rate, tax
        if nxt in seen:                                    # flip-flop at a bracket edge: take the higher
            tax = max(tax, nxt)
            return ter_rate(cat, D(bruto) + tax, on), tax
        seen.add(nxt)
        tax = nxt
    return ter_rate(cat, D(bruto) + tax, on), tax


@dataclass
class Bruto:
    total: Decimal
    parts: list = field(default_factory=list)              # [(label, amount)], amounts signed


def bruto_from_slip(result, *, late_reduces=False, company_jht_in_bruto=False, company_jp_in_bruto=True,
                    ignore_codes=("pph21_allowance", "pph21_refund")):     # G16-3: the PPh lines are not bruto
    """
    A calculated slip (PayRunLine.result) -> the month's bruto for PPh 21.
    Earnings, minus unpaid leave (proved by Togar), minus late fines only when late_reduces (open question),
    plus JKK + JKM paid by the company (+ "bpjs_kes_company" if a company ever pays BPJS Kesehatan),
    plus the employee's JHT 2% the company pays only when company_jht_in_bruto (open question).
    """
    parts = []
    earnings = sum((D(str(e.get("amount") or 0)) for e in (result or {}).get("earnings", [])
                    if e.get("code") not in ignore_codes
                    and not str(e.get("code") or "").startswith("pesangon_")), ZERO)   # G16-4: final tax, not TER
    parts.append(("Penghasilan", earnings))
    deds = {d.get("code"): D(str(d.get("amount") or 0)) for d in (result or {}).get("deductions", [])}
    if deds.get("unpaid_leave"):
        parts.append(("Potongan izin tanpa upah", -deds["unpaid_leave"]))                # G21-3a (D72)
    if deds.get("maternity_cut"):                                                     # G14-2
        parts.append(("Upah cuti melahirkan bulan ke-5–6", -deds["maternity_cut"]))
    if late_reduces and deds.get("late"):
        parts.append(("Potongan keterlambatan", -deds["late"]))
    emp = {e.get("code"): D(str(e.get("amount") or 0)) for e in (result or {}).get("employer", [])}
    jkk_jkm = emp.get("jkk", ZERO) + emp.get("jkm", ZERO)
    if jkk_jkm:
        parts.append(("JKK + JKM (perusahaan)", jkk_jkm))
    if emp.get("bpjs_kes_company"):
        parts.append(("BPJS Kesehatan (perusahaan)", emp["bpjs_kes_company"]))
    if company_jht_in_bruto and emp.get("jht_employee_company"):
        parts.append(("JHT 2% karyawan dibayar perusahaan", emp["jht_employee_company"]))
    if company_jp_in_bruto and emp.get("jp_employee_company"):                # G16-1: Pak Holan A3
        parts.append(("JP 1% karyawan dibayar perusahaan", emp["jp_employee_company"]))
    return Bruto(sum((a for _, a in parts), ZERO), parts)


@dataclass
class Monthly:
    bruto: Decimal                                        # including the tax allowance when grossed up
    rate: Decimal
    tax: Decimal
    gross_up: bool
    parts: list


def monthly_for_slip(result, ptkp, *, by_company=False, late_reduces=True, company_jht_in_bruto=True,
                     company_jp_in_bruto=True, on=None):
    """
    G16-1: one slip's PPh 21 for Jan-Nov, per Pak Holan (20 Nov 2026): late fines reduce bruto (A2), JP 1% / JHT 2%
    paid by the company are bruto (A3, B2), tax paid by the company is grossed up (A1).
    """
    b = bruto_from_slip(result, late_reduces=late_reduces, company_jht_in_bruto=company_jht_in_bruto,
                        company_jp_in_bruto=company_jp_in_bruto)
    if by_company:
        rate, tax = gross_up(b.total, ptkp, on)
        return Monthly(b.total + tax, rate, tax, True, b.parts + [("Tunjangan PPh 21 (gross-up)", tax)])
    rate, tax = monthly_pph(b.total, ptkp, on)
    return Monthly(b.total, rate, tax, False, b.parts)


def ptkp_amount(ptkp, on=None):
    t = _dated(PTKP_TABLES, on)
    s = str(ptkp).strip().upper().replace(" ", "")
    married, deps = s.startswith("K/"), int(s.split("/")[1])
    return t["base"] + (t["married"] if married else ZERO) + t["dependant"] * min(deps, 3)


def pasal17(pkp, on=None):
    tax, lower = ZERO, ZERO
    for upper, rate in _dated(PASAL17_TABLES, on):
        if upper is None or pkp > lower:
            layer = (min(pkp, upper) if upper is not None else pkp) - lower
            if layer > 0:
                tax += layer * rate
        if upper is None or pkp <= upper:
            break
        lower = upper
    return rupiah(tax)


@dataclass
class Annual:
    bruto: Decimal
    biaya_jabatan: Decimal
    iuran: Decimal
    netto: Decimal
    ptkp: Decimal
    pkp: Decimal
    tax_year: Decimal
    paid: Decimal
    due: Decimal                                           # < 0 = refund to the employee


def annual_pph(bruto_year, months, iuran_year, ptkp, paid_jan_nov=ZERO, on=None):
    """
    December, or the last month of someone leaving (not annualised; DJP book p. 61-70):
    bruto - biaya jabatan (5%, max 500.000 x months worked) - employee JHT/JP - PTKP = PKP (down to thousands)
    -> Pasal 17 -> minus what Jan-Nov took.
    """
    bruto_year, iuran_year = D(bruto_year), D(iuran_year)
    jabatan = min(rupiah(bruto_year * BIAYA_JABATAN_RATE), BIAYA_JABATAN_MONTH * int(months))
    netto = bruto_year - jabatan - iuran_year
    p = ptkp_amount(ptkp, on)
    pkp = ((netto - p) // 1000) * 1000 if netto > p else ZERO        # PKP rounded down to thousands
    tax = pasal17(pkp, on)
    return Annual(bruto_year, jabatan, iuran_year, netto, p, pkp, tax, D(paid_jan_nov), tax - D(paid_jan_nov))


def daily_rate(daily_bruto, on=None):
    """Daily workers (TER harian): 0% up to 450.000 a day, 0,5% up to 2,5 jt; above that None (monthly TER)."""
    for upper, rate in _dated(DAILY_TABLES, on):
        if D(daily_bruto) <= upper:
            return rate
    return None
