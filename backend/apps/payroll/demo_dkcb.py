# =============================================================================
# === backend/apps/payroll/demo_dkcb.py ===
# =============================================================================
"""
A real payroll run as test data (G8a, 1 Nov 2026): PT DKCB, period 26 Sep - 25 Oct 2026,
29 permanent staff, from the register Anthony shared on 31 Oct. Names are replaced by
codes K01-K29; the amounts are the real ones. Used by tests/test_engine.py and by
`python manage.py payroll_demo`.
"""
from decimal import Decimal

from .engine import FLAT, NEAREST_HALF, EmployeeTerms, Extra, PayrollRules, PeriodInput, calculate

DKCB = PayrollRules(
    period_start_day=26, pay_day=5, working_days="123456", daily_divisor=30,
    overtime_mode=FLAT, overtime_rounding=NEAREST_HALF,
    flat_overtime_hour=Decimal("12500"), flat_rest_day=Decimal("120000"),
    meal_allowance=Decimal("15000"), late_fine_per_minute=Decimal("500"), late_tolerance_minutes=5,
    jkk=Decimal("0.0089"), minimum_wage=Decimal("4583221"),
)
BPJS_KES = Extra("insentif_bpjs_kes", "Insentif BPJS Kesehatan", Decimal("35000"))

# code, gaji pokok, overtime hours, Kubikasi TM, meal days, Kubikasi CP, Bongkar Semen,
# Insentif BPJS Kes (bool), Insentif lainnya, late minutes, unpaid days, BPJS TK (bool),
# loan, other deduction, net in the register (None = not visible in the screenshots)
OCT_2026 = [
    ("K01", 10000000, 0,    0,      0,  0,     0,      False, 0,      0,   0,   True,  0,       0,      None),
    ("K02", 6000000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  1500000, 0,      None),
    ("K03", 5500000,  0,    0,      0,  0,     0,      True,  169000, 318, 3,   True,  2000000, 0,      None),
    ("K04", 4000000,  28.5, 0,      9,  0,     0,      True,  0,      0,   0,   True,  0,       0,      4446250),
    ("K05", 4500000,  88,   0,      21, 0,     0,      True,  0,      0,   0,   True,  500000,  0,      5360000),
    ("K06", 2950000,  0,    0,      0,  0,     800000, True,  0,      98,  1,   True,  500000,  0,      3078667),
    ("K07", 3200000,  0,    0,      0,  0,     0,      False, 0,      29,  20,  False, 0,       0,      1052167),
    ("K08", 3250000,  93,   0,      25, 21600, 0,      True,  0,      301, 0,   True,  500000,  0,      4128600),
    ("K09", 5350000,  0,    0,      1,  27000, 0,      True,  0,      0,   1,   True,  500000,  0,      4641667),
    ("K10", 2800000,  0,    462000, 10, 0,     0,      True,  0,      92,  8,   True,  0,       0,      2598333),
    ("K11", 7500000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  1000000, 0,      6385000),
    ("K12", 3000000,  70.5, 0,      20, 0,     0,      True,  0,      1,   2,   True,  500000,  241625, 3214125),
    ("K13", 2800000,  0,    700800, 9,  0,     0,      True,  0,      13,  1,   True,  500000,  0,      3014967),
    ("K14", 2800000,  0,    663000, 6,  0,     0,      True,  0,      41,  1,   True,  0,       0,      3418167),
    ("K15", 2500000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  500000,  0,      1985000),
    ("K16", 3500000,  0,    0,      0,  0,     0,      False, 150000, 0,   0,   True,  500000,  0,      3080000),
    ("K17", 4250000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  500000,  0,      3700000),
    ("K18", 2800000,  0,    629400, 10, 0,     0,      True,  0,      0,   1,   True,  500000,  0,      2965067),
    ("K19", 4000000,  14.5, 0,      3,  0,     0,      True,  0,      0,   0,   True,  500000,  0,      3681250),
    ("K20", 3500000,  0,    0,      0,  0,     0,      False, 0,      0,   1,   True,  0,       0,      3313333),
    ("K21", 2800000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  300000,  0,      2479000),
    ("K22", 4500000,  0,    0,      1,  0,     0,      True,  0,      9,   0,   True,  500000,  0,      3955500),
    ("K23", 2800000,  0,    508800, 13, 0,     0,      True,  0,      171, 4,   True,  500000,  0,      2523967),
    ("K24", 2500000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  500000,  0,      1985000),
    ("K25", 2800000,  0,    165000, 5,  0,     0,      True,  0,      0,   2.5, True,  0,       0,      2785667),
    ("K26", 4500000,  0,    0,      0,  0,     0,      True,  0,      0,   0,   True,  0,       0,      None),
    ("K27", 2800000,  0,    713400, 4,  0,     0,      True,  0,      79,  2.5, True,  500000,  0,      None),
    ("K28", 2900000,  0,    0,      0,  0,     600000, False, 0,      148, 1.5, False, 0,       0,      None),
    ("K29", 10000000, 0,    0,      0,  0,     0,      False, 0,      0,   2,   False, 0,       0,      None),
]

# the register's total row (Rekapan Gaji, row 36)
REGISTER_TOTALS = {
    "base": 119800000, "overtime": 3681250, "kubikasi_tm": 3842400, "meal": 2055000, "kubikasi_cp": 48600,
    "bongkar_semen": 1400000, "insentif_bpjs_kes": 805000, "insentif_lain": 319000, "late": 650000,
    "jht_employee": 2074000, "loan": 12300000, "lainnya": 241625,
    # Unpaid leave: the register shows 5,955,000. Excel sums the unrounded cells; GajiKita rounds
    # each line to the rupiah so every slip adds up, which gives 5,954,998 (2 rupiah of display rounding).
    "unpaid_leave": 5954998,
}


def dkcb_slip(row):
    (_, base, ot, tm, meal, cp, semen, kes, lain, late, unpaid, bpjs, loan, other, _net) = row
    D = lambda v: Decimal(str(v))
    terms = EmployeeTerms(base_salary=D(base), monthly_extras=(BPJS_KES,) if kes else (), bpjs_tk=bpjs)
    piece = tuple(x for x in (Extra("kubikasi_tm", "Kubikasi TM", D(tm)), Extra("kubikasi_cp", "Kubikasi CP", D(cp)),
                              Extra("bongkar_semen", "Bongkar Semen", D(semen))) if x.amount)
    period = PeriodInput(
        overtime_hours=D(ot), rest_days_worked=Decimal("0"), meal_days=D(meal), late_minutes=D(late),
        unpaid_days=D(unpaid), piece_work=piece, loan_repayment=D(loan),
        additions=(Extra("insentif_lain", "Insentif lainnya", D(lain)),) if lain else (),
        deductions=(Extra("lainnya", "Pemotongan lainnya", D(other)),) if other else (),
    )
    return calculate(terms, period, DKCB)
