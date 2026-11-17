# =============================================================================
# === backend/apps/attendance/overtime_import.py ===
# =============================================================================
"""
Overtime decided from HR's recap file (G17-8, 17 Nov 2026).

  plan(org, overtime_file, machine)   match each block's ID to an employee (same machine rules and name check as
                                      the tap and note imports), then compare, day by day, what HR paid in the file
                                      with what the taps propose and what is decided in SeeGaji now. Reads only.
  apply(org, plan, actor, filename)   decides those days in one transaction; every day is one audit line with the
                                      batch id, so "Urungkan" (POST review/undo/) puts them all back.

Rules (the file is the truth for the people in it, over its own period)
  - hours > 0 in the file          -> "Lembur dibayar" that many minutes (a day with no taps at all, e.g. a power
                                      cut, gets a day record so the hours can be paid)
  - empty / 0, taps propose overtime -> "Hadir, tanpa lembur" (no SPL)
  - empty / 0, SeeGaji pays overtime -> changed to "Hadir, tanpa lembur"
  - the same as SeeGaji already      -> left alone (importing the same file twice changes nothing)
  - never touched: locked (paid) days, rejected days (Kembalikan ke belum first), people not entitled to overtime
    pay (listed), days outside the person's employment, people without an overtime row (a plain machine export)
  - HR's late / one-tap / ½-day decisions on those days stay as they were; only the overtime is decided.
"""
from collections import OrderedDict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.models import AuditEntry

from .fingerprint_import import id_lookup, machine_names, suggest_machine
from .machines import AUTO, AUTO_NAME, MAIN, MAIN_NAME, assign, dept_owner_map, depts_in_file, id_sort_key
from .models import AttendanceDay, FingerprintMachine
from .name_match import check_names, distinct_names
from .review import evaluate, leaves_between, night_context
from .review_overtime import as_pending, new_batch, snapshot

PAY, UNPAY, NONE, SAME = "pay", "unpay", "none", "same"
LOCKED, REJECTED, NOT_ELIGIBLE, OUTSIDE = "locked", "rejected", "not_eligible", "outside"
TODO = (PAY, UNPAY, NONE)
AUDIT_ACTION = "attendance.overtime_import"


def _dates(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _hm(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def _line(emp, d, book, day, r, decided):
    """-> the line for one date, or None when there is nothing to say about it."""
    proposed = (r.overtime_proposed_minutes or 0) if r is not None else 0
    current = (day.overtime_approved_minutes or 0) if decided else 0
    if d < emp.join_date or (emp.end_date and d > emp.end_date):
        state = OUTSIDE if book else None
    elif day is not None and day.is_locked:
        changes = book != current or (not book and proposed and not decided)
        state = LOCKED if changes else None
    elif book:
        if not emp.overtime_eligible:
            state = NOT_ELIGIBLE
        elif day is not None and day.decision == "rejected":
            state = REJECTED
        elif decided and current == book:
            state = SAME
        else:
            state = PAY
    elif decided and current:
        state = UNPAY
    elif proposed and day is not None and not day.decision:
        state = NONE
    else:
        state = None
    if state is None:
        return None
    return {"date": d, "state": state, "book": book, "proposed": proposed,
            "current": current if decided else None, "in": _hm(r.first_in) if r else None,
            "out": _hm(r.last_out) if r else None}


def plan(org, of, machine=MAIN):
    machines = list(FingerprintMachine.objects.filter(organization=org))
    names = machine_names(machines)
    mode = machine.pk if isinstance(machine, FingerprintMachine) else machine
    dept_map = dept_owner_map((m.pk, m.dept_labels) for m in machines if m.is_active)
    _, _, lookup = id_lookup(org)
    start, end = of.period
    blocks = of.people
    suggest = suggest_machine(blocks, mode, machines, dept_map, lookup, names)

    found, unknown = OrderedDict(), []
    for (key, machine_id), items in assign(blocks, mode, dept_map).items():
        emp = lookup(key, machine_id)
        hours = sum(b.total for b in items)
        if emp is None:
            unknown.append({"machine_id": machine_id, "name": next((b.name for b in items if b.name), ""),
                            "minutes": hours, "machine": names.get(key, MAIN_NAME), "machine_key": str(key),
                            "link_machine": MAIN if key == MAIN else str(key), "_sort": id_sort_key(machine_id)})
            continue
        person = found.setdefault(emp, {"ids": [], "names": [], "blocks": []})
        person["ids"].append((key, machine_id))
        person["names"].extend(b.name for b in items)
        person["blocks"].extend(items)

    emps = list(found)
    days = {(d.employee_id, d.date): d for d in AttendanceDay.objects.filter(
        organization=org, employee__in=emps, date__gte=start, date__lte=end)
        .select_related("employee", "shift").prefetch_related("events__site")}
    leaves = leaves_between(org.id, start, end)
    ctx = night_context(org.id, [e.id for e in emps], start, end)
    now = timezone.now()

    people = []
    for emp, person in found.items():
        book, twice, unreadable, total_file = {}, [], [], 0
        for b in person["blocks"]:
            for d, m in b.minutes.items():
                if d in book:
                    twice.append(d)
                book[d] = max(book.get(d, 0), m)       # two blocks for one person: the larger, and say so
            unreadable.extend(b.unreadable)
            total_file = None if total_file is None or b.total_file is None else total_file + b.total_file
        lines = []
        for d in _dates(start, end):
            day = days.get((emp.id, d))
            r = evaluate(as_pending(day), now, leave=leaves.get((emp.id, d), ""), ctx=ctx) if day else None
            decided = day is not None and day.decision == "approved"
            line = _line(emp, d, book.get(d, 0), day, r, decided)
            if line:
                line["day_id"] = str(day.pk) if day else None
                lines.append(line)
        names_here = distinct_names(person["names"])
        name_check, bad = check_names(names_here, emp.full_name)
        count = lambda *states: sum(1 for l in lines if l["state"] in states)
        file_total = sum(book.values())
        people.append({
            "employee": emp, "machine_id": ", ".join(i for _, i in person["ids"]),
            "machines": [{"machine": names.get(k, MAIN_NAME), "machine_id": i} for k, i in person["ids"]],
            "sort": min(id_sort_key(i) for _, i in person["ids"]),
            "name_in_file": names_here[0] if names_here else "", "names_in_file": names_here,
            "name_check": name_check, "mismatch_name": bad[0] if bad else "",
            "file_minutes": file_total, "file_total": total_file,
            "total_mismatch": total_file is not None and total_file != file_total,
            "twice": sorted(set(twice)), "unreadable": unreadable,
            "proposed_minutes": sum(l["proposed"] for l in lines),
            "lines": lines, "todo": count(*TODO), "pay": count(PAY), "unpay": count(UNPAY), "none": count(NONE),
            "same": count(SAME), "locked": count(LOCKED), "rejected": count(REJECTED),
            "not_eligible": count(NOT_ELIGIBLE), "outside": count(OUTSIDE),
        })
    people.sort(key=lambda x: (x["name_check"] != "bad", -x["todo"], x["sort"], x["employee"].full_name))
    unknown.sort(key=lambda u: (-u["minutes"], u["machine_key"] != MAIN, u["_sort"]))
    return {
        "file": of, "people": people, "unknown": unknown, "suggest": suggest, "start": start, "end": end,
        "no_row": sum(1 for b in of.blocks if not b.has_row),
        "depts": [{**d, "machine": names.get(d["machine_key"], MAIN_NAME), "machine_key": str(d["machine_key"])}
                  for d in depts_in_file(blocks, mode, dept_map) if d["dept"]],
        "mode": MAIN if mode == MAIN else (AUTO if mode == AUTO else "one"),
        "machine": machine if isinstance(machine, FingerprintMachine) else None,
        "machine_name": names.get(mode, AUTO_NAME if mode == AUTO else MAIN_NAME),
    }


def public(p):
    people = p["people"]
    total = lambda key: sum(x[key] for x in people)
    return {
        "sheet": p["file"].sheet, "period": {"start": p["start"].isoformat(), "end": p["end"].isoformat()},
        "machine": {"mode": p["mode"], "id": str(p["machine"].pk) if p["machine"] else None, "name": p["machine_name"]},
        "suggest_machine": p["suggest"], "depts": p["depts"], "no_row": p["no_row"],
        "unknown": [{k: v for k, v in u.items() if k != "_sort"} for u in p["unknown"]],
        "people": [{"employee": {"id": str(x["employee"].id), "employee_no": x["employee"].employee_no,
                                 "full_name": x["employee"].full_name},
                    "machine_id": x["machine_id"], "machines": x["machines"], "name_in_file": x["name_in_file"],
                    "names_in_file": x["names_in_file"], "name_check": x["name_check"], "mismatch_name": x["mismatch_name"],
                    "file_minutes": x["file_minutes"], "file_total": x["file_total"], "total_mismatch": x["total_mismatch"],
                    "twice": [d.isoformat() for d in x["twice"]],
                    "unreadable": [{"date": d.isoformat(), "text": t} for d, t in x["unreadable"]],
                    "proposed_minutes": x["proposed_minutes"],
                    **{k: x[k] for k in ("todo", "pay", "unpay", "none", "same", "locked", "rejected", "not_eligible", "outside")},
                    "lines": [{**l, "date": l["date"].isoformat()} for l in x["lines"]]} for x in people],
        "totals": {"people": len(people), "unknown": len(p["unknown"]),
                   "unknown_with_overtime": sum(1 for u in p["unknown"] if u["minutes"]),
                   "file_minutes": total("file_minutes"),
                   **{k: total(k) for k in ("todo", "pay", "unpay", "none", "same", "locked", "rejected", "not_eligible", "outside")},
                   "people_todo": sum(1 for x in people if x["todo"]),
                   "name_mismatch": sum(1 for x in people if x["name_check"] == "bad"),
                   "total_mismatch": sum(1 for x in people if x["total_mismatch"])},
    }


def apply(org, p, actor, filename=""):
    """Decide every PAY / UNPAY / NONE line. -> {"decided", "skipped", "minutes", "batch"}."""
    batch, now, audits = new_batch(), timezone.now(), []
    decided = skipped = minutes = 0
    who = actor if getattr(actor, "is_authenticated", False) else None
    with transaction.atomic():
        for x in p["people"]:
            emp = x["employee"]
            for l in x["lines"]:
                if l["state"] not in TODO:
                    continue
                day = (AttendanceDay.objects.select_for_update().select_related("employee")
                       .filter(organization=org, employee=emp, date=l["date"]).first())
                if day is None:
                    if l["state"] != PAY:
                        continue
                    day = AttendanceDay.objects.create(organization=org, employee=emp, date=l["date"],
                                                       shift=emp.default_shift)
                if day.is_locked or day.decision == "rejected":    # changed since the preview
                    skipped += 1
                    continue
                before = snapshot(day)
                day.decision = "approved"
                day.overtime_approved_minutes = l["book"] or None
                day.decided_by, day.decided_at = who, now
                day.save(update_fields=["decision", "overtime_approved_minutes", "decided_by", "decided_at", "updated_at"])
                minutes += l["book"]
                decided += 1
                summary = (f"Lembur dibayar {l['book']} menit dari file rekap" if l["book"]
                           else "Hadir, tanpa lembur (tidak ada lembur di file rekap)")
                audits.append(AuditEntry(
                    organization=org, actor=who, action=AUDIT_ACTION,
                    target_type=day._meta.label_lower, target_id=str(day.pk),
                    summary=f"{emp.full_name} {day.date:%d-%m-%Y}: {summary}"[:255],
                    data={"before": before, "after": snapshot(day), "batch": batch, "file": filename[:200],
                          "book": l["book"], "proposed": l["proposed"]}))
        AuditEntry.objects.bulk_create(audits, batch_size=500)
        if decided:
            record_audit(organization=org, actor=actor, action="attendance.overtime_import_file", target=org,
                         summary=f"Lembur dari file rekap{(' ' + filename) if filename else ''} "
                                 f"{p['start']:%d-%m-%Y} s/d {p['end']:%d-%m-%Y}: {decided} hari diputuskan",
                         after={"decided": decided, "minutes": minutes, "file": filename, "batch_of_days": batch,
                                "start": p["start"].isoformat(), "end": p["end"].isoformat()})
    return {"decided": decided, "skipped": skipped, "minutes": minutes, "batch": batch if decided else None}
