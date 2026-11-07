# =============================================================================
# === backend/apps/attendance/night_rules.py ===
# =============================================================================
"""
G12e (7 Nov 2026) — coming in later after overtime that ran past midnight. Pure Python.

A company writes its rule as rows, checked top to bottom against the time the previous
day's work ended (DKCB's "OTW memo"):

    previous day ended between 00:00 and 01:59  ->  start at 10:00
    previous day ended at 02:00 up to 04:00     ->  start at 13:00
    previous day ended later than that          ->  day off (no absence, no fine)

Stored as JSON on PayrollSettings.night_ot_rules:
    [{"until": "01:59", "start": "10:00"}, {"until": "04:00", "start": "13:00"}, {"until": "", "start": ""}]
  until  "HH:MM", inclusive (the minute counts, seconds don't); "" = any later time (last row only)
  start  "HH:MM" = the new start time that day; "" = a day off
An empty list switches the rule off.

Only overtime runs past midnight count: a night shift that ends in the morning by design
(security 19:00 - 07:00) never moves the next day's start.
"""
from dataclasses import dataclass
from datetime import datetime, time

MAX_ROWS = 6

DKCB_EXAMPLE = [{"until": "01:59", "start": "10:00"}, {"until": "04:00", "start": "13:00"},
                {"until": "", "start": ""}]


class RuleError(ValueError):
    pass


def _hhmm(text, what):
    try:
        h, m = str(text).strip().split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise RuleError(f"{what} harus berupa jam, misalnya 02:00 (sekarang: {text!r}).")


def parse_rules(raw):
    """JSON rows -> ((until or None, start or None), ...). Raises RuleError in plain Indonesian."""
    if raw in (None, "", []):
        return ()
    if not isinstance(raw, list):
        raise RuleError("Aturan lembur malam harus berupa daftar baris.")
    if len(raw) > MAX_ROWS:
        raise RuleError(f"Paling banyak {MAX_ROWS} baris.")
    rows, last_until = [], None
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise RuleError(f"Baris {i} tidak lengkap.")
        until_text = str(item.get("until") or "").strip()
        start_text = str(item.get("start") or "").strip()
        until = _hhmm(until_text, f"Baris {i}: 'sampai jam'") if until_text else None
        start = _hhmm(start_text, f"Baris {i}: 'masuk jam'") if start_text else None
        if until is None and i != len(raw):
            raise RuleError(f"Baris {i}: 'sampai jam' kosong hanya boleh di baris terakhir.")
        if until is not None and last_until is not None and until <= last_until:
            raise RuleError(f"Baris {i}: jam harus lebih besar dari baris sebelumnya.")
        if until is not None and until >= time(12, 0):
            raise RuleError(f"Baris {i}: 'sampai jam' harus sebelum 12:00 siang (lewat tengah malam).")
        rows.append((until, start))
        last_until = until if until is not None else last_until
    return tuple(rows)


@dataclass(frozen=True)
class NightStart:
    prev_out: datetime          # when the previous day's work ended (local time)
    start: time = None          # the new start time; None = a day off

    @property
    def day_off(self):
        return self.start is None

    @property
    def note(self):
        ended = self.prev_out.strftime("%H:%M")
        if self.day_off:
            return f"Lembur malam sampai {ended}: hari ini libur"
        return f"Lembur malam sampai {ended}: masuk jam {self.start:%H:%M}"


def night_start(day, prev_out, prev_crosses_midnight, rules):
    """
    day                    the working date being evaluated
    prev_out               the previous day's last clock-out, local aware datetime (None = none)
    prev_crosses_midnight  the previous day's SHIFT ends after midnight (a night shift): never applies
    rules                  parse_rules() output
    -> NightStart, or None when the normal start applies
    """
    if not rules or prev_out is None or prev_crosses_midnight or prev_out.date() != day:
        return None
    hm = prev_out.time().replace(second=0, microsecond=0)
    for until, start in rules:
        if until is None or hm <= until:
            return NightStart(prev_out=prev_out, start=start)
    return None
