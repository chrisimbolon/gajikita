# =============================================================================
# === backend/apps/attendance/suggestions.py ===
# =============================================================================
"""
G21-3a (25 Nov 2026) — Saran SeeGaji: SeeGaji connects the dots, HR decides (design G21-3 v0.2, D67, D69-D72).

Pure: reads one person's traced period (payrun.collect_numbers(trace=[])), their raw taps per day and HR's notes,
and returns suggestions. Nothing is written here; G21-3b adds the preview and the buttons.

  s1  a night tap (00:00-04:59) is the first tap of day D, D has its real clock-in hours later, and D-1 has no
      clock-out: the tap is D-1's pulang. (What the import does since G20-2.2, for older files and phone taps.)
  s3  the same, but the night tap is D's only tap: after the move D has no tap left (the sentence says the cost).
  s2  approved overtime on a day with no clock-out (and no night tap next morning to be its pulang): fill in the
      pulang, prefilled from HR's note when it names an hour, otherwise shift end + the overtime (a form, D70).
  s4  leave on a day with taps (G20-2 "Tidak cocok"), shown here as a suggestion; the step stays in Siap gajian?.

Strength (D-v0.2): "kuat" = D-1 has approved overtime, or an HR note on D-1 / D names that hour (±15 min): the card
says it as a statement. "lemah" = no evidence: the card asks it as a question. Both get the same two buttons.

Never suggested: locked days, days HR already fixed (Ubah jam), leave on D-1, night-shift people (a shift that
starts before 06:00 or crosses midnight: a 02:00 tap is their normal clock-in), dismissed ones ("Bukan", G21-3b).
"""
import re
from datetime import timedelta

from django.utils import timezone

NIGHT_END_HOUR = 5             # a tap 00:00-04:59 can be last night's pulang (same window as the G20-2.2 import)
REAL_IN_GAP = timedelta(hours=3)
NOTE_MATCH_MINUTES = 15
MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
KINDS = {"s1": "Tap malam milik hari sebelumnya", "s2": "Lembur tanpa jam pulang",
         "s3": "Tap malam satu-satunya", "s4": "Cuti tapi ada tap"}

_HHMM = re.compile(r"(?<!\d)([01]?\d|2[0-3])[.:]([0-5]\d)(?!\d)")
_JAM = re.compile(r"\bjam\s+([01]?\d|2[0-3])\b(?![.:]\d)", re.IGNORECASE)


def day_text(d):
    return f"{d.day} {MON[d.month - 1]}"


def _hm(minutes):
    h, m = divmod(int(minutes or 0), 60)
    return f"{h} j {m} mnt" if h and m else (f"{h} j" if h else f"{m} mnt")


def _dot(amount):
    return f"{int(amount):,}".replace(",", ".")


def note_times(note):
    """'Masuk jam 13.00 wib, OT sampai jam 02.00 wib' -> [780, 120] (minutes of the day, in order)."""
    text = (note or {}).get("text") or ""
    out = [int(h) * 60 + int(m) for h, m in _HHMM.findall(text)]
    out += [int(h) * 60 for h in _JAM.findall(text)]
    return out


def _near(a, b, limit=NOTE_MATCH_MINUTES):
    d = abs(a - b) % 1440
    return min(d, 1440 - d) <= limit


def night_shift(shift):
    if shift is None:
        return False
    return shift.start_time.hour < 6 or shift.end_time <= shift.start_time


def _shift_end(shift, d):
    end = shift.saturday_end_time if (d.isoweekday() == 6 and shift.saturday_end_time) else shift.end_time
    return end.hour * 60 + end.minute


def _local(dt):
    return timezone.localtime(dt)


def _mins(dt):
    t = _local(dt)
    return t.hour * 60 + t.minute


def find(emp, trace, taps, notes, rates, dismissed=frozenset(), conflicts=None):
    """
    emp: the employee (pay_type, default_shift, id). trace: collect_numbers' trace (one dict per day in employment).
    taps: {date: [aware datetimes, sorted]} of raw taps as stored per day, including the day after the period.
    notes: {date: {"code", "text"}} HR's notes. rates: attendance_log.Rates. dismissed: {(date_iso, kind)}.
    conflicts: [(date_iso, kind, kind_label, text)] from G20-2 (already without dismissed / locked).
    -> suggestions, ordered by date.
    """
    shift = emp.default_shift
    if night_shift(shift):
        return _s4(conflicts)
    by_date = {t["date"]: t for t in trace}
    daily = getattr(emp, "pay_type", "monthly") == "daily"
    out, pulled = [], set()

    # s1 / s3: a night tap on D that is D-1's pulang
    for t in trace:
        d = t["date"]
        prev = by_date.get(d - timedelta(days=1))
        day_taps = taps.get(d) or []
        if prev is None or not day_taps or t["locked"] or prev["locked"] or t["hr_fixed"]:
            continue
        first = _local(day_taps[0])
        if first.hour >= NIGHT_END_HOUR:
            continue
        if prev["last_out"] is not None or prev["status"] == "leave" or prev["exempt"]:
            continue                                         # D-1 has its pulang, or nothing to fix there
        if not prev["working"] and not prev["present"] and not prev["overtime"]:
            continue                                         # an idle day off: as the G20-2.2 import rule
        later = [x for x in day_taps[1:] if x - day_taps[0] >= REAL_IN_GAP]
        if len(day_taps) > 1 and not later:
            continue                                         # taps close together at night: not ours to guess
        kind = "s1" if later else "s3"
        if (d.isoformat(), kind) in dismissed:
            continue
        hhmm = first.strftime("%H:%M")
        evidence = []
        if prev["overtime"]:
            evidence.append(f"lembur {_hm(prev['overtime'])} disetujui di {day_text(prev['date'])}"
                            + (" (sekarang tanpa tap: dihitung tidak masuk)" if prev["absent"] else ""))
        for nd in (prev["date"], d):
            n = notes.get(nd)
            if n and any(_near(m, _mins(day_taps[0])) for m in note_times(n)):
                evidence.append(f"catatan HR {day_text(nd)}: “{n.get('text') or n.get('code')}”")
        strong = bool(evidence)
        to = day_text(prev["date"])
        if strong:
            text = f"Tap {hhmm} di {day_text(d)} adalah jam pulang {to}."
        else:
            text = f"Apakah tap {hhmm} di {day_text(d)} jam pulang {to}? {to} tidak ada tap pulang."
        cost = ""
        if kind == "s1":
            cost = f"Masuk {day_text(d)} jadi {_local(later[0]).strftime('%H:%M')}."
        elif t["working"] and t["status"] != "leave":
            cost = (f"Kalau dipindah, {day_text(d)} tidak ada tap lagi: bisa dihitung tidak hadir"
                    + (" (upah harian hari itu tidak dibayar)." if daily else
                       f" (potong 1 hari, Rp {_dot(rates.per_day)}). Ada cuti atau izin hari itu?"))
        else:
            cost = f"Kalau dipindah, {day_text(d)} tidak ada tap lagi (hari libur, tidak dipotong)."
        pulled.add(prev["date"])
        out.append({"id": f"{kind}:{d.isoformat()}", "kind": kind, "kind_label": KINDS[kind],
                    "date": d.isoformat(), "to_date": prev["date"].isoformat(), "tap": hhmm,
                    "strength": "kuat" if strong else "lemah", "question": not strong,
                    "text": text, "evidence": evidence, "cost": cost, "prefill": None})

    # s2: approved overtime with no clock-out
    for t in trace:
        d = t["date"]
        if not t["overtime"] or t["last_out"] is not None or t["locked"] or d in pulled or shift is None:
            continue
        nxt = taps.get(d + timedelta(days=1)) or []
        if nxt and _local(nxt[0]).hour < NIGHT_END_HOUR:
            continue                                         # tomorrow's night tap may be its pulang (s1/s3)
        if (d.isoformat(), "s2") in dismissed:
            continue
        end = _shift_end(shift, d)
        named = [m for m in note_times(notes.get(d)) if m >= end or m < NIGHT_END_HOUR * 60]
        if named:
            out_min, source = named[-1], "catatan HR"
        else:
            out_min, source = (end + t["overtime"]) % 1440, "perkiraan: jam pulang shift + lembur"
        clock_out = f"{out_min // 60:02d}:{out_min % 60:02d}"
        clock_in = None if t["first_in"] else shift.start_time.strftime("%H:%M")
        text = (f"Lembur {_hm(t['overtime'])} disetujui di {day_text(d)}, tapi tidak ada jam pulang. "
                f"Jam pulang {clock_out} ({source}).")
        out.append({"id": f"s2:{d.isoformat()}", "kind": "s2", "kind_label": KINDS["s2"], "date": d.isoformat(),
                    "to_date": None, "tap": None, "strength": "kuat" if named else "lemah", "question": False,
                    "text": text, "evidence": ([f"catatan HR: “{notes[d].get('text')}”"] if named else []),
                    "cost": "Lembur yang disetujui tidak berubah; jam pulang mengatur uang makan dan jam masuk besok.",
                    "prefill": {"clock_in": clock_in, "clock_out": clock_out, "source": source,
                                "clock_in_source": "perkiraan: jam masuk shift" if clock_in else ""}})

    # G21-3a.1: "lembur dibayar padahal tidak masuk" on a day whose pulang is the night tap is the same story as
    # its s1/s3 card (after the move the day has a pulang), so it is not shown twice
    explained = {d.isoformat() for d in pulled}
    out += _s4([c for c in (conflicts or []) if not (c[1] == "overtime_on_leave" and c[0] in explained)])
    out.sort(key=lambda s: (s["date"], s["kind"]))
    return out


def _s4(conflicts):
    return [{"id": f"s4:{iso}:{kind}", "kind": "s4", "kind_label": label, "date": iso, "to_date": None, "tap": None,
             "strength": "kuat", "question": False, "text": text, "evidence": [],
             "cost": "Cek di Cuti & Izin, atau tandai sudah benar.", "prefill": None, "conflict_kind": kind}
            for iso, kind, label, text in (conflicts or [])]


def taps_by_day(org, employee_ids, start, end):
    """{employee_id: {date: [aware datetimes]}} of the raw taps as stored per day, start .. end + 1 day."""
    from collections import defaultdict
    from .models import ClockEvent
    out = defaultdict(lambda: defaultdict(list))
    rows = (ClockEvent.objects.filter(organization=org, employee_id__in=employee_ids, day__date__gte=start,
                                      day__date__lte=end + timedelta(days=1))
            .order_by("occurred_at").values_list("employee_id", "day__date", "occurred_at"))
    for emp_id, d, at in rows:
        out[emp_id][d].append(at)
    return out


def notes_by_day(org, employee_ids, start, end):
    from .day_notes_import import notes_for
    out = {}
    for (emp_id, d), n in notes_for(org, employee_ids, start, end).items():
        out.setdefault(emp_id, {})[d] = n
    return out


def for_period(org, start, end, traced, rates_for, conflicts_by_emp=None):
    """Siap gajian?: s1-s3 for everyone (s4 has its own "Tidak cocok" step). -> {count, people}."""
    ids = [emp.id for emp, _, _ in traced]
    taps = taps_by_day(org, ids, start, end)
    notes = notes_by_day(org, ids, start, end)
    people = []
    for emp, _, trace in traced:
        found = [s for s in find(emp, trace, taps.get(emp.id, {}), notes.get(emp.id, {}), rates_for(emp))
                 if s["kind"] != "s4"]
        if found:
            people.append({"employee": {"id": str(emp.id), "employee_no": emp.employee_no, "full_name": emp.full_name},
                           "count": len(found), "first_date": found[0]["date"],
                           "items": [{"date": s["date"], "kind": s["kind"], "strength": s["strength"], "text": s["text"]}
                                     for s in found]})
    people.sort(key=lambda p: (-p["count"], p["employee"]["full_name"]))
    return {"count": sum(p["count"] for p in people), "people": people}
