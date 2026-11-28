# =============================================================================
# === backend/apps/attendance/ringkasan.py ===
# =============================================================================
"""
G21-1 (25 Nov 2026) — Ringkasan Karyawan: one person, one period, one page (design G21 v0.1, D66-D68).

HR thinks by person ("what happened with Prayuda this month, and why is his pay what it is?"), but the numbers
live in modules (Harian, Rekap, Log, Tinjau, SPL, Payroll). This endpoint puts one person's period together:

  * employee   who, shift, pay type, meal rule
  * money      the payroll line's own slip (earnings, deductions, net) and whether it still matches the attendance
               ("same" / "stale" = Hitung ulang / "override" = HR corrected numbers on the line). No payroll yet:
               only the attendance parts, marked as an estimate.
  * totals     the month in numbers (present, absent, late, overtime, meals...)
  * days       every day of the period: a colour kind for the month tiles, the time bar, chips, the day's rupiah
               and "Kenapa begini": each rule that decided the day, in one plain sentence
  * attention  what HR should look at (no basis, not reviewed, overtime not decided, conflicts). G21-3 adds the
               suggestions with a button; this step only shows.

Read-only. One source of truth, like the Log (G20-1): every day comes from payrun.collect_numbers(trace=[],
cells=[]), the function the payroll counts with, so the page can never disagree with the slip. Day rupiah use the
engine's rates (overtime priced as the day panel prices it), shown per day for the reader; the slip stays the
total that is paid.

GET /api/hr/attendance/ringkasan/?employee=<id>&month=YYYY-MM
"""
import uuid
from datetime import date as Date
from decimal import Decimal

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from . import attendance_log as log

ZERO = Decimal("0")
DOW = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
PAY_TYPES = {"monthly": "Bulanan", "daily": "Harian", "piece": "Per pekerjaan"}

# the keys of the payroll's numbers that move money; a difference = the slip needs Hitung ulang
MONEY_KEYS = ("late_minutes", "unpaid_days", "meal_days", "breakfast_days", "present_days", "paid_leave_days",
              "sick_days", "long_leave_days", "reduced_pay_days")
KEY_LABELS = {"late_minutes": "menit terlambat", "unpaid_days": "hari potong gaji", "meal_days": "uang makan",
              "breakfast_days": "uang sarapan", "present_days": "hari hadir", "paid_leave_days": "hari cuti dibayar",
              "sick_days": "hari sakit", "long_leave_days": "hari istirahat panjang",
              "reduced_pay_days": "hari upah dikurangi", "overtime": "lembur",
              "overtime_hours": "jam lembur", "rest_days_worked": "hari lembur libur"}

# the day's money, grouped for "Belum ada payroll" (what attendance moves; the slip adds the rest)
GROUPS = {"wage": "Upah harian", "overtime": "Lembur", "meal": "Uang makan",
          "late": "Denda terlambat / pulang cepat", "cut": "Potongan hari (tidak hadir, ½ hari, tanpa upah)"}

# the tile colours of "Ritme bulan ini" (the page has the legend)
KINDS = {
    "present": "Hadir", "late": "Terlambat / ½ hari", "absent": "Tanpa keterangan", "unpaid": "Tidak dibayar",
    "leave": "Cuti / izin dibayar", "sick": "Sakit", "event": "Kejadian", "exempt": "Tidak wajib absen",
    "off": "Libur", "pending": "Belum terjadi", "outside": "Di luar masa kerja",
}


def _r(value):
    """Decimal -> 'Rp 12.500' style number string the page formats ("12500")."""
    return log.rupiah(value)


def _id(value):
    return value if isinstance(value, str) else str(value)


def _minutes_of(dt, day):
    """Minutes from 00:00 of `day` in local time (past midnight > 1440), or None."""
    if dt is None:
        return None
    local = timezone.localtime(dt)
    return (local.date() - day).days * 1440 + local.hour * 60 + local.minute


def _hm(minutes):
    """540 -> '9 j', 545 -> '9 j 5 mnt', 25 -> '25 mnt' (as the day panel writes it)."""
    minutes = int(minutes or 0)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} j {m} mnt"
    return f"{h} j" if h else f"{m} mnt"


def _dot(amount):
    """12500 -> '12.500' (rupiah in sentences)."""
    return f"{int(Decimal(amount)):,}".replace(",", ".")


def _shift_window(shift, d):
    """(start, end) minutes of the shift on that date; end past 1440 for a night shift; None without a shift."""
    if shift is None:
        return None
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end_t = shift.saturday_end_time if (d.isoweekday() == 6 and shift.saturday_end_time) else shift.end_time
    end = end_t.hour * 60 + end_t.minute
    if end <= start:
        end += 1440
    return {"start": start, "end": end}


# ── pure: one traced day -> its kind, chips, rupiah and reasons ──

def day_kind(t, cell):
    if cell["c"] == "-":
        return "outside"
    if t is None:
        return "off"
    if t["holiday"] and not t["present"]:
        return "event"
    if t["status"] == "not_yet":
        return "pending"
    if t["unpaid_leave"] or (t["rejected"] and t["working"]):
        return "unpaid"
    if t["absent"]:
        return "absent"
    if t["status"] == "leave":
        return "sick" if t["leave_kind"] == "sick" else "leave"
    if t["exempt"]:
        return "exempt"
    if t["disrupted"]:
        return "event"
    if t["present"]:
        if (t["late_tag"] and t["late"]) or t["late_half"] or t["early_half"] or t["one_tap"] or t["permit"] \
                or (t["early_tag"] and t["early"]):
            return "late"
        return "present"
    return "off"


def overtime_text(price):
    """The day panel's pricing (services.price_overtime) -> 'tarif perusahaan 9 j × Rp 12.500'."""
    if not price:
        return ""
    if price.get("not_paid"):
        return price["not_paid"]
    if price.get("mode") == "flat":
        if price.get("rest_day"):
            return f"tarif hari libur Rp {_dot(price['rate'])}"
        return f"tarif perusahaan {_hm(price['rounded_minutes'])} × Rp {_dot(price['rate'])}/jam"
    return "menurut PP 35/2021"


def explain_day(t, cell, rows, rates, cfg, emp, price, note):
    """
    -> (chips, money, why). Pure (no queries): t = the trace dict, cell = the Rekap cell, rows = the Log rows of
    that date {"late", "early", "absent", "meal"}, price = services.price_overtime() or None, note = HR's note.
    money = [{"label", "amount"}] signed rupiah (as strings), the day's effect on the slip.
    """
    chips, money, why = [], [], []
    daily = getattr(emp, "pay_type", "monthly") == "daily"
    after = cfg.meal_late_after.strftime("%H:%M") if cfg.meal_late_after else ""

    def chip(key, label, tone):
        chips.append({"key": key, "label": label, "tone": tone})

    def add(label, amount, group):
        if amount:
            money.append({"label": label, "amount": _r(amount), "group": group})

    if cell["c"] == "-":
        why.append("Di luar masa kerja (sebelum masuk / sesudah keluar)."
                   + ("" if daily else " Gaji bulan ini dihitung sebagian: dipotong 1 hari."))
        if not daily:
            add("Di luar masa kerja", -rates.per_day, "cut")
        return chips, money, why

    if t["event"]:
        chip("event", t["event"], "violet")
        why.append(f"{t['event']}.")
    if t["holiday"]:
        why.append("Hari kerja ini jadi hari libur: " + ("masuk dihitung lembur hari libur." if t["present"]
                                                          else "tidak masuk, tidak dipotong."))

    # the day itself
    if t["status"] == "not_yet":
        why.append("Belum terjadi.")
    elif t["status"] == "leave":
        chip("leave", t["leave_label"] or "Cuti", "indigo")
        if t["unpaid_leave"]:
            why.append(f"{t['leave_label'] or 'Izin tanpa upah'} (disetujui): tidak dibayar"
                       + ("." if daily else ", potong 1 hari."))
            if not daily:
                add(t["leave_label"] or "Izin tanpa upah", -rates.per_day, "cut")
        else:
            why.append(f"{t['leave_label'] or 'Cuti'} (disetujui): dibayar penuh.")
            if daily:
                add("Upah harian (cuti dibayar)", rates.per_day, "wage")
    elif t["rejected"] and t["working"]:
        chip("rejected", "Ditolak HR", "red")
        why.append("Ditolak HR: hari ini tidak dihitung masuk" + ("." if daily else ", potong 1 hari."))
        if not daily:
            add("Ditolak HR", -rates.per_day, "cut")
    elif t["absent"]:
        chip("absent", "Tanpa keterangan", "red")
        why.append("Hari kerja tanpa tap, cuti atau izin: dihitung tidak hadir"
                   + (" (upah harian tidak dibayar)." if daily else f", potong 1 hari (Rp {_dot(_r(rates.per_day))})."))
        if not daily:
            add("Tidak hadir", -rates.per_day, "cut")
    elif t["exempt"]:
        chip("exempt", "Tidak wajib absen", "sky")
        why.append("Tidak wajib absen: dihitung hadir tanpa melihat tap.")
        if daily:
            add("Upah harian", rates.per_day, "wage")
    elif t["present"]:
        fi, lo = log.hhmm(t["first_in"]), log.hhmm(t["last_out"])
        if fi and lo:
            why.append(f"Hadir: masuk {fi}, pulang {lo}" + (f" ({_hm(t['worked_minutes'])} kerja)."
                                                            if t["worked_minutes"] else "."))
        elif lo:
            why.append(f"Hanya ada tap pulang ({lo}): dihitung hadir.")
        elif fi:
            why.append(f"Hanya ada tap masuk ({fi}): belum ada jam pulang.")
        elif t["disrupted"]:
            why.append("Tidak ada tap, tapi ada gangguan absen: dihitung hadir.")
        if not t["working"] and not t["holiday"]:
            chip("rest_day", "Masuk di hari libur", "amber")
        if daily:
            add("Upah harian", rates.per_day, "wage")
    elif not t["working"]:
        why.append("Libur.")

    if t["hr_fixed"]:
        chip("hr_time", "Jam dikoreksi HR", "amber")
        why.append("Jam masuk / pulang dikoreksi HR (Ubah jam): jam HR yang dipakai, bukan tap mesin.")
    if t["decision"] == "approved" and not t["hr_fixed"]:
        why.append("Disetujui HR.")
    if t["forgiven"]:
        chip("forgiven", "Dimaafkan HR", "green")

    # the G12e night rule: allowed to start later after a long night
    night = t.get("night_rule") or t["night_note"]
    if night and t["status"] == "day_off":                                  # pulang very late: today off
        chip("night", "Boleh tidak masuk", "sky")
        why.append(f"Aturan pulang malam ({night}): hari ini tidak dihitung tidak hadir.")
    elif night:
        chip("night", "Boleh masuk siang", "sky")
        why.append(f"Aturan pulang malam ({night}): jam masuk hari ini dihitung dari jam itu.")

    # late / early (the Log's own rows, so the words and the money are the Log's)
    for r in rows.get("late", []):
        if r["basis"] == "grace":
            why.append(f"Masuk {r['minutes']} menit setelah jam mulai: masih dalam toleransi shift, tidak dihitung.")
            continue
        if r["basis"] == "night":
            why.append(f"Masuk {_hm(r['minutes'])} setelah jam mulai biasa, tapi karena aturan pulang malam tidak "
                       f"dihitung terlambat.")
            continue
        chip("late", f"Telat {r['minutes']} mnt", "amber")
        text = f"Terlambat {r['minutes']} menit ({r['label']})"
        if r["half"]:
            text += ": potong ½ hari"
        elif r["charged"]:
            text += (f": denda {r['charged']} menit × Rp {_dot(_r(rates.fine))}"
                     + (f" (setelah toleransi payroll {rates.tolerance} menit)" if rates.tolerance else ""))
        else:
            text += ": tidak didenda"
        why.append(text + ".")
        add(f"Terlambat {r['minutes']} mnt", -Decimal(r["amount"]), "late")
    for r in rows.get("early", []):
        chip("early", f"Pulang cepat {r['minutes']} mnt", "amber")
        text = f"Pulang {r['minutes']} menit lebih cepat ({r['label']})"
        if r["half"]:
            text += ": potong ½ hari"
        elif r["charged"]:
            text += f": denda {r['charged']} menit × Rp {_dot(_r(rates.fine))}"
        else:
            text += ": tidak didenda"
        why.append(text + ".")
        add(f"Pulang cepat {r['minutes']} mnt", -Decimal(r["amount"]), "late")

    # ½ days that are not late / early
    if t["one_tap"]:
        chip("half", "½ hari", "amber")
        why.append("Hanya satu tap di hari ini: dihitung ½ hari (aturan perusahaan)"
                   + ("." if rates.half_day else ", tanpa potongan untuk jenis upah ini."))
        add("½ hari (satu tap)", -rates.half_day, "cut")
    if t["permit"]:
        chip("half", "Izin ½ hari", "amber")
        why.append("Izin ½ hari tanpa upah" + (": potong ½ hari." if rates.half_day else "."))
        add("Izin ½ hari", -rates.half_day, "cut")
    elif t["half_leave"] == "paid":
        chip("half_leave", "Cuti ½ hari", "indigo")
        why.append("Cuti ½ hari (dibayar).")

    # overtime
    if t["overtime"]:
        chip("overtime", f"Lembur {_hm(t['overtime'])}", "blue")
        source = "disetujui HR" if t["decision"] == "approved" else (f"dari SPL ({t['spl']})" if t["spl"] else "dari SPL")
        how = overtime_text(price)
        amount = Decimal(price["amount"]) if price and price.get("amount") else ZERO
        why.append(f"Lembur {_hm(t['overtime'])} {source}"
                   + (f": Rp {_dot(amount)} ({how})." if amount else (f": {how}." if how else ".")))
        add(f"Lembur {_hm(t['overtime'])}", amount, "overtime")
    if cell.get("otp"):
        chip("overtime_open", f"Lembur {_hm(cell['otp'])} belum diputuskan", "amber")
        why.append(f"Ada lembur {_hm(cell['otp'])} di tap yang belum diputuskan HR: belum dibayar.")

    # meals
    for r in rows.get("meal", []):
        if r["missed"]:
            why.append(f"Tidak dapat uang makan: {r['label']}.")
            continue
        label = f"Makan {r['meals']}×" if r["meals"] else "Sarapan"
        chip("meal", label, "green")
        rp = f" Rp {_dot(r['amount'])}." if r["amount"] != "0" else ""
        lead = f"Uang makan {r['meals']}×: " if r["meals"] else ""            # G12h.2: no brackets in brackets
        text = r["label"][0].lower() + r["label"][1:] if lead else r["label"]
        why.append(f"{lead}{text}." + rp)
        add(label, Decimal(r["amount"]), "meal")
    if t.get("meal_wait"):                                                           # G23-1
        lo = log.hhmm(t["last_out"])
        if t.get("overtime_open"):
            chip("meal_wait", "Makan menunggu lembur", "amber")
            why.append(f"Uang makan menunggu lembur disetujui: pulang {lo}, tetapi lembur hari itu belum diputuskan HR.")
        else:
            why.append(f"Tidak dapat uang makan: pulang {lo}, tetapi tidak ada lembur yang disetujui hari itu "
                       f"(aturan: uang makan pulang malam hanya jika lembur disetujui).")
    elif not rows.get("meal") and t["meal_rule"] == "late_out" and t["present"] and t["working"] and after \
            and t["status"] not in ("leave", "exempt"):
        lo = log.hhmm(t["last_out"])
        why.append(f"Tidak dapat uang makan: pulang {lo or '-'} (aturan: pulang jam {after} atau lebih).")

    # HR's note from the rekap file (information only)
    if note:
        chip("note", "Catatan HR", "slate")
        why.append(f"Catatan HR: {note.get('text') or note.get('code') or '-'} (hanya keterangan).")
    if cell.get("rv"):
        chip("review", "Belum ditinjau", "amber")
        why.append("Hari ini belum ditinjau HR.")
    if t.get("locked"):
        why.append("Hari ini sudah dikunci (payroll dikunci).")
    return chips, money, why


def build_days(emp, trace, cells, rates, cfg, notes, price_for, dismissed=frozenset()):
    """Every day of the period, in order. Pure apart from price_for(t) (overtime pricing, no queries)."""
    by_date = {t["date"].isoformat(): t for t in trace}
    rows = {}
    for tab, fn in (("late", log.late_days), ("early", log.early_days), ("absent", log.absent_days)):
        for r in log._money(fn(trace, rates)):
            rows.setdefault(r["date"], {}).setdefault(tab, []).append(r)
    for r in log._money(log.meal_days(trace, rates, cfg.meal_late_after, cfg.breakfast_before)):
        rows.setdefault(r["date"], {}).setdefault("meal", []).append(r)

    shift = emp.default_shift
    out = []
    for cell in cells:
        iso = cell["d"]
        t = by_date.get(iso)
        d = Date.fromisoformat(iso)
        kind = day_kind(t, cell)
        if t is None:
            chips, money, why = explain_day({}, cell, {}, rates, cfg, emp, None, None) if cell["c"] == "-" \
                else ([], [], [])
            first = last = None
        else:
            price = price_for(t) if t["overtime"] else None
            chips, money, why = explain_day(t, cell, rows.get(iso, {}), rates, cfg, emp, price,
                                            notes.get((emp.id, d)))
            first, last = t["first_in"], t["last_out"]
        conflicts = []
        if t is not None and not t.get("locked"):
            conflicts = [{"kind": k, "kind_label": log.CONFLICT_KINDS[k], "text": text}
                         for k, text in log.day_conflicts(t, rates.long_limit)
                         if (str(emp.id), iso, k) not in dismissed]
        total = sum((Decimal(m["amount"]) for m in money), ZERO)
        out.append({
            "date": iso, "dow": DOW[d.weekday()], "day": d.day, "day_id": cell.get("day"),
            "code": cell["c"], "status": cell["s"], "status_label": cell["l"], "kind": kind,
            "working": bool(t and t["working"]),
            "in": log.hhmm(first), "out": log.hhmm(last),
            "in_min": _minutes_of(first, d), "out_min": _minutes_of(last, d),
            "shift": _shift_window(shift, d) if (t and t["working"]) else None,
            "worked_minutes": t["worked_minutes"] if t else 0,
            "overtime_minutes": t["overtime"] if t else 0, "overtime_open_minutes": cell.get("otp", 0),
            "late_minutes": t["late_raw"] if t and t["late_tag"] else 0,
            "meals": t["meal"] if t else 0, "breakfast": bool(t and t["breakfast"]),
            "review": bool(cell.get("rv")), "hr_fixed": bool(t and t["hr_fixed"]),
            "decision": t["decision"] if t else "", "locked": bool(t and t.get("locked")),
            "note": (t.get("night_rule") or t["night_note"]) if t else "",
            "hr_note": notes.get((emp.id, d)) if t else None,
            "chips": chips, "money": money, "rupiah": _r(total), "why": why, "conflicts": conflicts,
        })
    return out


def attention(days):
    """What HR should look at this month, newest problems first by kind. Read-only in G21-1."""
    items = []
    for d in days:
        if d["kind"] == "absent":
            items.append({"date": d["date"], "kind": "absent", "tone": "red",
                          "text": "Tidak hadir tanpa keterangan: dipotong 1 hari. Ada cuti / izin atau gangguan absen?"})
        if d["review"]:
            items.append({"date": d["date"], "kind": "review", "tone": "amber", "text": "Belum ditinjau HR."})
        if d["overtime_open_minutes"]:
            items.append({"date": d["date"], "kind": "overtime_open", "tone": "amber",
                          "text": f"Lembur {_hm(d['overtime_open_minutes'])} di tap belum diputuskan: belum dibayar."})
        if d["status"] == "no_clock_out" and not d["overtime_minutes"]:
            items.append({"date": d["date"], "kind": "no_clock_out", "tone": "amber",
                          "text": "Tidak ada tap pulang."})
        if d["status"] == "no_clock_in":
            items.append({"date": d["date"], "kind": "no_clock_in", "tone": "amber", "text": "Tidak ada tap masuk."})
    return items                                    # G21-3a: conflicts are suggestions now (s4), not listed twice


def totals(nums, days, cfg, rates):
    ot = sum(o["minutes"] for o in nums.get("overtime", []))
    return {
        "working_days": nums["working_days"], "present_days": nums["present_days"],
        "absent_days": nums["absent_days"], "unpaid_days": float(nums["unpaid_days"]),
        "unpaid_leave_days": nums["unpaid_leave_days"], "paid_leave_days": nums["paid_leave_days"],
        "leave": nums["leave"], "sick_days": nums["sick_days"],
        "late_days": sum(1 for d in days if any(c["key"] == "late" for c in d["chips"])),
        "late_minutes": nums["late_minutes"],
        "half_days": nums["half_days"] + nums["permit_half_days"] + nums["long_halves"],
        "overtime_minutes": ot, "overtime_days": len(nums.get("overtime", [])),
        "overtime_open_days": sum(1 for d in days if d["overtime_open_minutes"]),
        "meals": nums["meal_days"], "breakfasts": nums["breakfast_days"],
        "review_days": sum(1 for d in days if d["review"]),
        "hr_fixed_days": sum(1 for d in days if d["hr_fixed"]),
    }


def _norm_ot(rows):
    return sorted((str(o["date"]), int(o["minutes"]), bool(o["rest_day"])) for o in rows or [])


def slip_check(nums, line):
    """Does the payroll line still say what the attendance says? -> {state, changed: [labels], fixed: [labels]}."""
    if line is None:
        return {"state": "none", "changed": [], "fixed": []}
    auto, fix = line.auto or {}, line.override or {}
    changed = [k for k in MONEY_KEYS if log._num(auto.get(k)) != log._num(nums.get(k))]
    if _norm_ot(auto.get("overtime")) != _norm_ot(nums.get("overtime")):
        changed.append("overtime")
    fixed = [k for k in fix]
    state = "stale" if changed else ("override" if fixed else "same")
    return {"state": state, "changed": [KEY_LABELS.get(k, k) for k in changed],
            "fixed": [KEY_LABELS.get(k, k) for k in fixed]}


def money_block(emp, nums, line, days, rates):
    if line is not None:
        res = line.result or {}
        pick = lambda xs: [{"code": x.get("code"), "label": x.get("label"), "amount": _r(log._num(x.get("amount"))),
                            "quantity": x.get("quantity"), "unit": x.get("unit") or ""} for x in xs or []]
        return {"source": "slip", "earnings": pick(res.get("earnings")), "deductions": pick(res.get("deductions")),
                "gross": _r(line.gross), "deductions_total": _r(line.deductions), "net": _r(line.net),
                "warnings": res.get("warnings", []), "line_id": str(line.id), "note": line.note,
                "check": slip_check(nums, line)}
    # no payroll yet: only what attendance moves, from the day rows (an estimate, the slip will say)
    parts = {}
    for d in days:
        for m in d["money"]:
            parts[m["group"]] = parts.get(m["group"], ZERO) + Decimal(m["amount"])
    return {"source": "attendance", "parts": [{"group": k, "label": GROUPS[k], "amount": _r(parts[k])}
                                              for k in GROUPS if k in parts],
            "check": {"state": "none", "changed": [], "fixed": []}}


def _missing(money, run):
    """G21-2: a payroll exists for the period but this person has no line yet (joined after it was made)."""
    if run is not None and money["source"] == "attendance":
        money["check"] = {"state": "missing", "changed": [], "fixed": []}
    return money


# ── the database part ──

def load(org, employee_id, month=None, now=None):
    from apps.employees.models import Employee
    from apps.payroll.models import PayrollSettings, PayRun, PayRunLine
    from apps.payroll.payrun import _days_by_employee, _leaves_by_employee, collect_numbers, employees_in_period
    from apps.payroll.services import price_overtime
    from apps.payroll.engine import round_overtime
    from .checklist import _conflict_dismissed
    from .day_notes_import import notes_for
    from .review import night_context
    from .review_bulk import _period

    try:
        uuid.UUID(str(employee_id))
    except (TypeError, ValueError):
        raise Http404
    emp = (Employee.objects.filter(organization=org, pk=employee_id).select_related("default_shift").first())
    if emp is None:
        raise Http404
    info, start, end = _period(org, month)
    now = now or timezone.now()
    cfg = PayrollSettings.for_org(org)
    days = _days_by_employee(org, start, end, [emp.id]).get(emp.id, {})
    leaves = _leaves_by_employee(org, start, end, [emp.id]).get(emp.id, {})
    ctx = night_context(org.id, [emp.id], start, end)
    trace, cells = [], []
    nums = collect_numbers(emp, start, end, cfg, days, leaves, now, cells=cells, ctx=ctx, trace=trace)
    rates = log.rates_for(emp, cfg)
    notes = notes_for(org, [emp.id], start, end)
    shift = emp.default_shift

    def price_for(t):
        minutes = round_overtime(t["overtime"], cfg.overtime_rounding)
        day = days.get(t["date"])
        day_shift = (day.shift if day is not None and day.shift_id else None) or shift
        return price_overtime(emp, day_shift, minutes, not t["working"], cfg)

    day_rows = build_days(emp, trace, cells, rates, cfg, notes, price_for, _conflict_dismissed(org))
    from . import suggestions as saran                                                          # G21-3a
    from .suggestion_actions import dismissed_for, moved_taps                                  # G21-3b
    saran_list = saran.find(
        emp, trace, saran.taps_by_day(org, [emp.id], start, end).get(emp.id, {}),
        {d: n for (_, d), n in notes.items()}, rates,
        dismissed=dismissed_for(org, [str(emp.id)]).get(str(emp.id), set()),
        conflicts=[(d["date"], c["kind"], c["kind_label"], c["text"]) for d in day_rows for c in d["conflicts"]])
    moved = moved_taps(org, emp, start, end)                                                    # G21-3b: Kembalikan
    for d in day_rows:
        d["moved"] = moved.get(d["date"], [])
    run = PayRun.objects.filter(organization=org, period_start=start).first()
    line = PayRunLine.objects.filter(run=run, employee=emp).first() if run else None
    people = [{"id": str(e.id), "employee_no": e.employee_no, "full_name": e.full_name}
              for e in employees_in_period(org, start, end)]
    meal_rule = trace[0]["meal_rule"] if trace else (emp.meal_rule or cfg.meal_rule)
    return {
        "success": True, **info,
        "employee": {
            "id": str(emp.id), "employee_no": emp.employee_no, "full_name": emp.full_name, "position": emp.position,
            "pay_type": emp.pay_type, "pay_type_label": PAY_TYPES.get(emp.pay_type, emp.pay_type),
            "base_rate": _r(emp.base_rate or 0), "join_date": emp.join_date.isoformat() if emp.join_date else None,
            "end_date": emp.end_date.isoformat() if emp.end_date else None,
            "overtime_eligible": emp.overtime_eligible,
            "meal_rule": meal_rule, "meal_rule_label": log.MEAL_RULES.get(meal_rule, meal_rule),
            "shift": ({"name": shift.name, "start": shift.start_time.strftime("%H:%M"),
                       "end": shift.end_time.strftime("%H:%M"), "grace_minutes": shift.grace_minutes,
                       "working_days": shift.working_days} if shift else None),
        },
        "rules": {"late_fine_per_minute": _r(rates.fine), "late_tolerance_minutes": rates.tolerance,
                  "meal_allowance": _r(rates.meal), "meal_late_after": (cfg.meal_late_after.strftime("%H:%M")
                                                                        if cfg.meal_late_after else None),
                  "per_day": _r(rates.per_day), "half_day": _r(rates.half_day)},
        "run": ({"id": str(run.id), "name": run.name, "locked": run.is_locked,
                 "calculated_at": timezone.localtime(run.calculated_at).isoformat() if run.calculated_at else None}
                if run else None),
        "money": _missing(money_block(emp, nums, line, day_rows, rates), run),
        "totals": totals(nums, day_rows, cfg, rates),
        "kinds": KINDS,
        "days": day_rows,
        "attention": attention(day_rows),
        "suggestions": saran_list,                                                              # G21-3a
        "people": people,
    }


class RingkasanView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        employee = request.query_params.get("employee")
        if not employee:
            return Response({"success": False, "detail": "Pilih karyawan."}, status=400)
        return Response(load(request.hr_org, employee, request.query_params.get("month")))
