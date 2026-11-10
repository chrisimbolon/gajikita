# =============================================================================
# === backend/apps/attendance/day_notes_import.py ===
# =============================================================================
"""
HR's notes per day into SeeGaji (G12f.3.1, 10 Nov 2026).

  plan(org, notefile, machine)       match each row's ID to an employee with the same machine rules and name
                                     check as the tap import, then compare with the notes already saved for
                                     those people over the report period: new, changed, unchanged, removed,
                                     and days left alone because they are locked. Reads only.
  apply(org, plan, actor, filename)  writes it in one transaction, with one audit entry.
  delete_plan / delete_apply         "Hapus catatan import" for a date range.
  notes_for(org, employee_ids, start, end)   {(employee id, date): payload} for the screens.

Rules
  - A note never changes status, lateness, overtime or pay. It is shown beside the day, nothing more.
  - The file is the truth for the people in it, over its own period: importing it again changes nothing,
    an edited note is updated, a note HR took out of the file is removed here. People not in the file and
    dates outside the period are not touched.
  - Locked (paid) days are left as they are.
  - One note per person per date: a date written twice in the file becomes one note (texts joined " · ").
"""
from collections import Counter, OrderedDict

from django.db import transaction

from apps.core.audit import record_audit

from .fingerprint_import import id_lookup, machine_names, suggest_machine
from .machines import AUTO, AUTO_NAME, MAIN, MAIN_NAME, assign, dept_owner_map, id_sort_key
from .models import AttendanceDay, DayNote, FingerprintMachine
from .name_match import names_match

JOIN = " · "
MAX_LISTED = 50


def note_payload(n):
    return {"code": n.code, "color": n.color, "text": n.text}


def notes_for(org, employee_ids, start, end):
    """{(employee id, date): {"code", "color", "text"}} of the saved notes. employee_ids None = everyone."""
    qs = DayNote.objects.filter(organization=org, date__gte=start, date__lte=end)
    if employee_ids is not None:
        qs = qs.filter(employee_id__in=list(employee_ids))
    return {(n.employee_id, n.date): note_payload(n) for n in qs.order_by("source")}


def _merge(rows):
    """Rows of one person on one date -> (code, color, text), or None when none of them has a note."""
    rows = [r for r in rows if r.has_note]
    if not rows:
        return None
    texts = list(OrderedDict.fromkeys(r.text for r in rows if r.text))
    code = next((r.code for r in rows if r.code), "")
    color = next((r.color for r in rows if r.color), "")
    return code, color, JOIN.join(texts)[:1000]


def plan(org, nf, machine=MAIN):
    machines = list(FingerprintMachine.objects.filter(organization=org))
    names = machine_names(machines)
    mode = machine.pk if isinstance(machine, FingerprintMachine) else machine
    dept_map = dept_owner_map((m.pk, m.dept_labels) for m in machines if m.is_active)
    _, _, lookup = id_lookup(org)
    start, end = nf.period
    suggest = suggest_machine(nf.rows, mode, machines, dept_map, lookup, names)

    found, unknown = OrderedDict(), []
    for (key, machine_id), items in assign(nf.rows, mode, dept_map).items():
        file_name = next((r.name for r in items if r.name), "")
        emp = lookup(key, machine_id)
        if emp is None:
            unknown.append({"machine_id": machine_id, "name": file_name, "rows": len(items),
                            "notes": sum(1 for r in items if r.has_note),
                            "machine": names.get(key, MAIN_NAME), "machine_key": str(key),
                            "link_machine": MAIN if key == MAIN else str(key), "_sort": id_sort_key(machine_id)})
            continue
        person = found.setdefault(emp, {"ids": [], "checks": [], "rows": []})
        person["ids"].append((key, machine_id))
        person["checks"].append((file_name, names_match(file_name, emp.full_name)))
        person["rows"].extend(items)

    emps = list(found)
    existing = {(n.employee_id, n.date): n for n in DayNote.objects.filter(
        organization=org, source=DayNote.Source.IMPORT, employee__in=emps, date__gte=start, date__lte=end)}
    locked = set(AttendanceDay.objects.filter(employee__in=emps, date__gte=start, date__lte=end, is_locked=True)
                 .values_list("employee_id", "date"))

    people = []
    for emp, person in found.items():
        by_date = OrderedDict()
        for r in sorted(person["rows"], key=lambda r: r.date):
            by_date.setdefault(r.date, []).append(r)
        wanted = OrderedDict((d, m) for d, m in ((d, _merge(rs)) for d, rs in by_date.items()) if m is not None)
        add, change, same, remove, lines, locked_n = [], [], [], [], [], 0
        for d, (code, color, text) in wanted.items():
            old = existing.get((emp.id, d))
            if (emp.id, d) in locked:
                state = "locked"
                locked_n += 1
            elif old is None:
                state = "new"
                add.append((d, code, color, text))
            elif (old.code, old.color, old.text) != (code, color, text):
                state = "changed"
                change.append((old, code, color, text))
            else:
                state = "same"
                same.append(d)
            lines.append({"date": d.isoformat(), "code": code, "color": color, "text": text, "state": state,
                          "before": old.text if state == "changed" else ""})
        for (eid, d), old in existing.items():
            if eid == emp.id and d not in wanted:
                if (eid, d) in locked:
                    locked_n += 1
                else:
                    remove.append(old)
        bad = [n for n, same_name in person["checks"] if same_name is False]
        people.append({
            "employee": emp, "machine_id": ", ".join(i for _, i in person["ids"]),
            "machines": [{"machine": names.get(k, MAIN_NAME), "machine_id": i} for k, i in person["ids"]],
            "sort": min(id_sort_key(i) for _, i in person["ids"]),
            "name_in_file": next((n for n, _ in person["checks"] if n), ""),
            "name_check": "bad" if bad else ("ok" if any(s for _, s in person["checks"]) else "none"),
            "mismatch_name": bad[0] if bad else "",
            "codes": Counter(code for code, _, _ in wanted.values() if code),
            "lines": lines, "add": add, "change": change, "same": same, "remove": remove, "locked": locked_n,
        })
    people.sort(key=lambda x: (x["name_check"] != "bad", x["sort"], x["employee"].full_name))
    unknown.sort(key=lambda u: (u["machine_key"] != MAIN, u["machine"], u["_sort"]))

    return {
        "file": nf, "people": people, "unknown": unknown, "suggest": suggest, "start": start, "end": end,
        "mode": MAIN if mode == MAIN else (AUTO if mode == AUTO else "one"),
        "machine": machine if isinstance(machine, FingerprintMachine) else None,
        "machine_name": names.get(mode, AUTO_NAME if mode == AUTO else MAIN_NAME),
    }


def public(p):
    nf = p["file"]
    people = p["people"]
    legend_order = list(OrderedDict.fromkeys(nf.legend.values()))
    return {
        "sheet": nf.sheet, "period": {"start": p["start"].isoformat(), "end": p["end"].isoformat()},
        "period_in_file": nf.period_in_file, "colors_read": nf.colors_read,
        "legend": [{"color": c, "label": l} for c, l in nf.legend.items()],
        "unreadable": nf.unreadable, "outside": nf.outside,
        "repeated": [{"machine_id": i, "name": n, "date": d.isoformat()} for i, n, d in nf.repeated][:MAX_LISTED],
        "machine": {"mode": p["mode"], "id": str(p["machine"].pk) if p["machine"] else None, "name": p["machine_name"]},
        "suggest_machine": p["suggest"],
        "unknown": [{k: v for k, v in u.items() if k != "_sort"} for u in p["unknown"]],
        "people": [{"employee": {"id": str(x["employee"].id), "employee_no": x["employee"].employee_no,
                                 "full_name": x["employee"].full_name},
                    "machine_id": x["machine_id"], "machines": x["machines"], "name_in_file": x["name_in_file"],
                    "name_check": x["name_check"], "mismatch_name": x["mismatch_name"],
                    "codes": [{"code": c, "count": x["codes"][c]}
                              for c in sorted(x["codes"], key=lambda c: (c not in legend_order,
                                                                       legend_order.index(c) if c in legend_order else 0, c))],
                    "notes": len(x["lines"]), "new": len(x["add"]), "changed": len(x["change"]),
                    "same": len(x["same"]), "removed": len(x["remove"]), "locked": x["locked"],
                    "lines": x["lines"]} for x in people],
        "totals": {"people": len(people), "unknown": len(p["unknown"]),
                   "unknown_notes": sum(u["notes"] for u in p["unknown"]),
                   "notes": sum(len(x["lines"]) for x in people),
                   "new": sum(len(x["add"]) for x in people), "changed": sum(len(x["change"]) for x in people),
                   "same": sum(len(x["same"]) for x in people), "removed": sum(len(x["remove"]) for x in people),
                   "locked": sum(x["locked"] for x in people),
                   "name_mismatch": sum(1 for x in people if x["name_check"] == "bad")},
    }


def apply(org, p, actor, filename=""):
    added = changed = removed = 0
    with transaction.atomic():
        emps = [x["employee"] for x in p["people"]]
        locked = set(AttendanceDay.objects.select_for_update()
                     .filter(employee__in=emps, date__gte=p["start"], date__lte=p["end"], is_locked=True)
                     .values_list("employee_id", "date"))                       # locked in the meantime: left alone
        for x in p["people"]:
            emp = x["employee"]
            for d, code, color, text in x["add"]:
                if (emp.id, d) in locked:
                    continue
                _, created = DayNote.objects.update_or_create(
                    employee=emp, date=d, source=DayNote.Source.IMPORT,
                    defaults={"organization": org, "code": code, "color": color, "text": text,
                              "source_file": filename[:255], "created_by": actor if actor.is_authenticated else None})
                added += 1 if created else 0
                changed += 0 if created else 1
            for old, code, color, text in x["change"]:
                if (emp.id, old.date) in locked:
                    continue
                n = DayNote.objects.filter(pk=old.pk).update(code=code, color=color, text=text,
                                                             source_file=filename[:255])
                changed += n
            ids = [old.pk for old in x["remove"] if (emp.id, old.date) not in locked]
            if ids:
                removed += DayNote.objects.filter(pk__in=ids).delete()[0]
        if added or changed or removed:
            record_audit(organization=org, actor=actor, action="attendance.day_notes_import", target=org,
                         summary=f"Import catatan HR{(' ' + filename) if filename else ''} ({p['machine_name']}) "
                                 f"{p['start']:%d-%m-%Y} s/d {p['end']:%d-%m-%Y}: "
                                 f"{added} baru, {changed} diubah, {removed} dihapus",
                         after={"added": added, "changed": changed, "removed": removed, "file": filename,
                                "machine": p["machine_name"], "start": p["start"].isoformat(),
                                "end": p["end"].isoformat()})
    return {"added": added, "changed": changed, "removed": removed}


# ── "Hapus catatan import" ──
def delete_plan(org, start, end):
    notes = list(DayNote.objects.filter(organization=org, source=DayNote.Source.IMPORT, date__gte=start, date__lte=end)
                 .select_related("employee"))
    locked = set(AttendanceDay.objects.filter(organization=org, date__gte=start, date__lte=end, is_locked=True)
                 .values_list("employee_id", "date"))
    remove = [n for n in notes if (n.employee_id, n.date) not in locked]
    return {"start": start, "end": end, "remove": remove, "locked": len(notes) - len(remove)}


def delete_public(p):
    people = Counter(n.employee for n in p["remove"])
    return {"start": p["start"].isoformat(), "end": p["end"].isoformat(),
            "totals": {"notes": len(p["remove"]), "people": len(people), "locked": p["locked"]},
            "people": [{"employee": {"id": str(e.id), "employee_no": e.employee_no, "full_name": e.full_name},
                        "notes": n} for e, n in sorted(people.items(), key=lambda kv: kv[0].full_name)]}


def delete_apply(org, p, actor, reason):
    with transaction.atomic():
        locked = set(AttendanceDay.objects.select_for_update()
                     .filter(organization=org, date__gte=p["start"], date__lte=p["end"], is_locked=True)
                     .values_list("employee_id", "date"))
        ids = [n.pk for n in p["remove"] if (n.employee_id, n.date) not in locked]
        removed = DayNote.objects.filter(pk__in=ids).delete()[0] if ids else 0
        if removed:
            record_audit(organization=org, actor=actor, action="attendance.day_notes_delete", target=org,
                         summary=f"Hapus catatan HR {p['start']:%d-%m-%Y} s/d {p['end']:%d-%m-%Y}: {removed} catatan",
                         after={"removed": removed, "start": p["start"].isoformat(), "end": p["end"].isoformat()},
                         note=reason)
    return {"removed": removed}
