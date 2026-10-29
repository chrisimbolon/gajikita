# =============================================================================
# === backend/apps/payroll/overtime.py ===
# =============================================================================
"""
Overtime pay under PP 35/2021 (G4a, 28 Oct 2026). Pure Python, no Django:
minutes + the wage go in, rupiah and the working come out.

  Hourly rate   = 1/173 x monthly wage.
                  Monthly wage = gaji pokok + tunjangan tetap. A daily worker's
                  monthly wage = day rate x 25 (6-day week) or x 21 (5-day week).
  Working day   = 1.5x for the first hour, 2x for every hour after.
  Rest day      = 6-day week: 2x for hours 1-7, 3x for hour 8, 4x for hours 9-11.
                  5-day week: 2x for hours 1-8, 3x for hour 9, 4x for hours 10-12.
  Limits        = 4 hours on a working day, 18 hours a week: shown as warnings, never blocked.

Minutes count pro rata (30 minutes = half an hour). Each line is rounded to the
nearest rupiah. Not yet covered: public holidays (rest days are the shift's days
off for now), the "shortest working day" holiday variant, and piece-rate workers.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

HOURS_PER_MONTH = Decimal("173")
DAILY_TO_MONTHLY = {6: 25, 5: 21}
WEEKDAY_TIERS = [(60, Decimal("1.5")), (None, Decimal("2"))]
REST_DAY_TIERS = {
    6: [(7 * 60, Decimal("2")), (60, Decimal("3")), (None, Decimal("4"))],
    5: [(8 * 60, Decimal("2")), (60, Decimal("3")), (None, Decimal("4"))],
}
WEEKDAY_MAX_MINUTES = 4 * 60
WEEK_MAX_MINUTES = 18 * 60
REST_DAY_MAX_MINUTES = {6: 11 * 60, 5: 12 * 60}


def week_pattern(working_days):
    """'123456' -> 6-day week, '12345' -> 5-day week (anything shorter counts as 5)."""
    return 6 if len(set(working_days or "")) >= 6 else 5


def monthly_basis(pay_type, base_rate, fixed_allowance, pattern):
    """The monthly wage overtime is measured against, or None when PP 35's hourly rule doesn't apply here."""
    base, allowance = Decimal(base_rate or 0), Decimal(fixed_allowance or 0)
    if pay_type == "monthly":
        return base + allowance
    if pay_type == "daily":
        return base * DAILY_TO_MONTHLY[pattern] + allowance
    return None            # piece-rate: PP 35 uses a 12-month average; not built yet


def hourly_rate(basis):
    return basis / HOURS_PER_MONTH


def rupiah(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass
class Line:
    minutes: int
    multiplier: Decimal
    amount: Decimal


@dataclass
class OvertimePay:
    minutes: int
    rest_day: bool
    hourly_rate: Decimal
    lines: list = field(default_factory=list)
    amount: Decimal = Decimal("0")
    warnings: list = field(default_factory=list)


def overtime_pay(minutes, rest_day, pattern, hourly):
    """Split the minutes into PP 35's tiers and price each tier."""
    result = OvertimePay(minutes=int(minutes), rest_day=rest_day, hourly_rate=hourly)
    tiers = REST_DAY_TIERS[pattern] if rest_day else WEEKDAY_TIERS
    left = int(minutes)
    for size, multiplier in tiers:
        if left <= 0:
            break
        take = left if size is None else min(left, size)
        amount = rupiah(hourly * Decimal(take) / Decimal(60) * multiplier)
        result.lines.append(Line(minutes=take, multiplier=multiplier, amount=amount))
        left -= take
    result.amount = sum((l.amount for l in result.lines), Decimal("0"))
    limit = REST_DAY_MAX_MINUTES[pattern] if rest_day else WEEKDAY_MAX_MINUTES
    if minutes > limit:
        result.warnings.append(
            f"Lembur {minutes // 60} jam {minutes % 60} menit melebihi batas {limit // 60} jam "
            f"{'hari libur' if rest_day else 'per hari'} (PP 35/2021)")
    return result


def week_warnings(entries):
    """
    entries: (date, minutes, rest_day) for one person. PP 35's 18-hour weekly limit
    counts working-day overtime; returns one warning per ISO week over the limit.
    """
    weeks = {}
    for day, minutes, rest_day in entries:
        if not rest_day:
            key = day.isocalendar()[:2]
            weeks[key] = weeks.get(key, 0) + int(minutes)
    return [f"Minggu ke-{w}: lembur {m // 60} jam {m % 60} menit, melebihi 18 jam per minggu (PP 35/2021)"
            for (_, w), m in sorted(weeks.items()) if m > WEEK_MAX_MINUTES]
