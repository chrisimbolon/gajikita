# =============================================================================
# === backend/apps/attendance/fingerprint_import.py ===
# =============================================================================
"""
Fingerprint taps into GajiKita (G9, 1 Nov 2026).

  plan(org, punches)    match machine IDs to employees (Karyawan -> "ID Mesin Fingerprint"),
                        build each person's sessions, and count what is new, what was already
                        imported, and what falls on a locked (paid) day. Reads only.
  apply(org, plan, actor)   writes the new taps as ClockEvents (source "fingerprint") on the
                        right AttendanceDay. Safe to repeat: every tap has a fixed id made from
                        the employee and the time, so importing the same file twice adds nothing.

After import the taps behave like phone taps: Absensi, Perlu Tinjau, Lembur and Payroll see them.

G12f.1a: plan(org, punches, machine) matches IDs on one machine only: MAIN (the IDs on the employee),
a FingerprintMachine, or AUTO (each block of a combined report by its Dept.). One person's taps from
two machines are paired together, and every saved tap remembers its machine.
They carry no GPS, so no location flags.

G12f.2: every name in the file is checked against the matched employee (name_match), the file is tried
on every machine choice and a clearly better one is suggested, and each unknown ID gets a proposed employee.
"""
import uuid
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.employees.models import Employee

from .fingerprint import clean_id, make_sessions
from .machines import (AUTO, AUTO_NAME, MAIN, MAIN_NAME, assign, dept_owner_map, depts_in_file, id_sort_key,
                       merge_by_employee)
from .models import AttendanceDay, ClockEvent, EmployeeMachineId, FingerprintMachine
from .name_match import names_match, suggest_pairs

NAMESPACE = uuid.UUID("4f0d6c3e-7a1b-4c55-9d3e-2b6f8a9e1c07")      # fixed forever: re-imports find the same ids


def tap_id(employee, at, kind):
    return uuid.uuid5(NAMESPACE, f"fp|{employee.id}|{at.isoformat()}|{kind}")


def machine_names(machines):
    """{key: name} for MAIN and every machine of the company."""
    names = {MAIN: MAIN_NAME}
    names.update({m.pk: m.name for m in machines})
    return names


def machine_fit(punches, mode, dept_map, lookup):
    """
    How well a file fits one machine choice (G12f.2): IDs recognised, names that agree with the
    employee, names that don't. Read with the wrong machine, IDs still match (numbers are reused)
    but the names stop agreeing, so a wrong name weighs three times a right one.
    """
    fit = {"known": 0, "unknown": 0, "name_ok": 0, "name_bad": 0}
    for (key, machine_id), items in assign(punches, mode, dept_map).items():
        emp = lookup(key, machine_id)
        if emp is None:
            fit["unknown"] += 1
            continue
        fit["known"] += 1
        same = names_match(next((p.name for p in items if p.name), ""), emp.full_name)
        if same is True:
            fit["name_ok"] += 1
        elif same is False:
            fit["name_bad"] += 1
    fit["score"] = fit["known"] + fit["name_ok"] - 3 * fit["name_bad"]
    return fit


SUGGEST_MARGIN = 3                 # another machine must fit clearly better before SeeGaji says so


def plan(org, punches, machine=MAIN):
    """
    machine: MAIN (the IDs on the employee), AUTO (each block by its Dept.; G12f.1a) or a
    FingerprintMachine of this company. IDs are matched only on that machine.
    G12f.2: also checks every name in the file against the matched employee, tries the file on the
    other machines and suggests a better one, and proposes an employee for each unknown ID.
    """
    machines = list(FingerprintMachine.objects.filter(organization=org))
    by_key = {m.pk: m for m in machines}
    names = machine_names(machines)
    mode = machine.pk if isinstance(machine, FingerprintMachine) else machine
    dept_map = dept_owner_map((m.pk, m.dept_labels) for m in machines if m.is_active)

    main_ids = {clean_id(e.fingerprint_id): e
                for e in Employee.objects.filter(organization=org).exclude(fingerprint_id="")
                .select_related("default_shift", "default_site")}
    other_ids = {(r.machine_id, clean_id(r.fingerprint_id)): r.employee
                 for r in EmployeeMachineId.objects.filter(organization=org)
                 .select_related("employee__default_shift", "employee__default_site")}

    def lookup(key, machine_id):
        return main_ids.get(machine_id) if key == MAIN else other_ids.get((key, machine_id))

    groups = assign(punches, mode, dept_map)
    file_names = {k: next((p.name for p in items if p.name), "") for k, items in groups.items()}
    found, missing = merge_by_employee(groups, lookup)

    # G12f.2: would another machine choice fit this file clearly better?
    candidates = [MAIN] + [m.pk for m in machines if m.is_active]
    if dept_map and any(p.dept for p in punches):
        candidates.append(AUTO)
    fits = {c: machine_fit(punches, c, dept_map, lookup) for c in candidates}
    chosen = fits.get(mode) or machine_fit(punches, mode, dept_map, lookup)
    best, best_score = mode, chosen["score"]
    for c in candidates:                                   # a tie keeps HR's own choice
        if fits[c]["score"] > best_score:
            best, best_score = c, fits[c]["score"]
    suggest = None
    if best != mode and best_score >= chosen["score"] + SUGGEST_MARGIN and fits[best]["known"] > 0:
        suggest = {"mode": MAIN if best == MAIN else (AUTO if best == AUTO else "one"),
                   "id": None if best in (MAIN, AUTO) else str(best),
                   "value": best if best in (MAIN, AUTO) else str(best),
                   "name": names.get(best, AUTO_NAME if best == AUTO else MAIN_NAME),
                   "known": fits[best]["known"], "name_ok": fits[best]["name_ok"],
                   "chosen_known": chosen["known"], "chosen_name_bad": chosen["name_bad"]}

    people = []
    for emp, person in found.items():
        shift = emp.default_shift
        sessions = make_sessions(person["times"], shift.start_time if shift else None)    # G12c
        events = []
        for s in sessions:
            events.append((s, "in", s.clock_in))
            if s.clock_out is not None:
                events.append((s, "out", s.clock_out))
        ids = [tap_id(emp, at, kind) for _, kind, at in events]
        already = set(ClockEvent.objects.filter(employee=emp, client_id__in=ids).values_list("client_id", flat=True))
        dates = {s.work_date for s in sessions}
        locked = set(AttendanceDay.objects.filter(employee=emp, date__in=dates, is_locked=True)
                     .values_list("date", flat=True))
        new_sessions = [s for s in sessions if s.work_date not in locked
                        and any(tap_id(emp, at, kind) not in already for ss, kind, at in events if ss is s)]
        checks = [(file_names.get(k, ""), names_match(file_names.get(k, ""), emp.full_name)) for k in person["ids"]]
        bad = [n for n, same in checks if same is False]
        people.append({
            "employee": emp, "machine_id": ", ".join(i for _, i in person["ids"]),
            "machines": [{"machine": names.get(k, MAIN_NAME), "machine_id": i} for k, i in person["ids"]],
            "sort": min((id_sort_key(i) for _, i in person["ids"])),
            "tap_machine": person["tap_machine"], "name_in_file": person["name"],
            "name_check": "bad" if bad else ("ok" if any(same for _, same in checks) else "none"),   # G12f.2
            "mismatch_name": bad[0] if bad else "",
            "sessions": sessions, "events": events, "already": already, "locked": locked,
            # G12f.2c: counted per date, like "days" and like apply(); a date can hold two sessions
            # (a lone 02:00 tap, then 12:43 -> 21:00), which must not count as two days
            "days": len(dates), "new_days": len({s.work_date for s in new_sessions}),
            "already_days": len(dates - locked - {s.work_date for s in new_sessions}),
            "locked_days": len(locked),
            "no_clock_out": sum(1 for s in sessions if s.clock_out is None),
        })
    people.sort(key=lambda x: (x["name_check"] != "bad", x["sort"], x["employee"].full_name))

    # G12f.2 / G12f.2b: for each unknown ID, the active employee whose name looks most like the name in the
    # file, among those with no ID yet on that machine. Decided for the whole file at once, best pairs
    # first (suggest_pairs). No suggestions while the file seems to come from another machine: linking
    # then would store this machine's numbers on the wrong machine.
    order = {MAIN: 0, **{m.pk: 1 for m in machines}}
    missing = sorted(missing, key=lambda x: (order.get(x[0], 1), names.get(x[0], ""), id_sort_key(x[1])))
    file_name = lambda items: next((p.name for p in items if p.name), "")
    picks = {}
    if suggest is None:
        active = list(Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE).order_by("full_name"))
        linked = {MAIN: {e.pk for e in main_ids.values()}}
        for (key, _), e in other_ids.items():
            linked.setdefault(key, set()).add(e.pk)
        groups_wanted = {key for key, _, _ in missing}
        picks = suggest_pairs(
            [(n, key, file_name(items)) for n, (key, _, items) in enumerate(missing) if file_name(items)],
            {key: [(e, e.full_name) for e in active if e.pk not in linked.get(key, set())] for key in groups_wanted})

    unknown = []
    for n, (key, machine_id, items) in enumerate(missing):
        t = sorted(p.at for p in items)
        pick = picks.get(n)
        unknown.append({"machine_id": machine_id, "name": file_name(items), "taps": len(t),
                        "first": t[0].isoformat(sep=" ", timespec="minutes"),
                        "last": t[-1].isoformat(sep=" ", timespec="minutes"),
                        "machine": names.get(key, MAIN_NAME), "machine_key": str(key),
                        "link_machine": MAIN if key == MAIN else str(key),
                        "suggest": {"id": str(pick[0].pk), "full_name": pick[0].full_name,
                                    "employee_no": pick[0].employee_no} if pick else None})

    all_dates = [s.work_date for p in people for s in p["sessions"]]
    tap_dates = [p.at.date() for p in punches]
    return {
        "people": people, "unknown": unknown, "by_key": by_key,
        "mode": MAIN if mode == MAIN else (AUTO if mode == AUTO else "one"),
        "machine": by_key.get(mode), "machine_name": names.get(mode, AUTO_NAME if mode == AUTO else MAIN_NAME),
        "depts": [{**d, "machine": names.get(d["machine_key"], MAIN_NAME), "machine_key": str(d["machine_key"])}
                  for d in depts_in_file(punches, mode, dept_map) if d["dept"]],
        "machines": [m for m in machines if m.is_active],
        "suggest": suggest,
        "period": {"start": min(all_dates).isoformat(), "end": max(all_dates).isoformat()} if all_dates else None,
        "file_period": {"start": min(tap_dates).isoformat(), "end": max(tap_dates).isoformat(),
                        "days": (max(tap_dates) - min(tap_dates)).days + 1} if tap_dates else None,
        "not_linked": [{"employee_no": e.employee_no, "full_name": e.full_name}
                       for e in Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE, fingerprint_id="",
                                                        machine_ids__isnull=True)
                       .order_by("full_name")[:50]],
    }


def public(p):
    return {
        "period": p["period"], "file_period": p["file_period"], "unknown": p["unknown"], "not_linked": p["not_linked"],
        "machine": {"mode": p["mode"], "id": str(p["machine"].pk) if p["machine"] else None, "name": p["machine_name"]},
        "machines": [{"id": str(m.pk), "name": m.name, "dept_labels": m.dept_labels} for m in p["machines"]],
        "depts": p["depts"], "suggest_machine": p["suggest"],
        "people": [{"employee": {"id": str(x["employee"].id), "employee_no": x["employee"].employee_no,
                                 "full_name": x["employee"].full_name},
                    "machine_id": x["machine_id"], "machines": x["machines"], "name_in_file": x["name_in_file"],
                    "name_check": x["name_check"], "mismatch_name": x["mismatch_name"],
                    "days": x["days"], "new_days": x["new_days"], "already_days": x["already_days"],
                    "locked_days": x["locked_days"], "no_clock_out": x["no_clock_out"]} for x in p["people"]],
        "totals": {"people": len(p["people"]), "unknown": len(p["unknown"]),
                   "new_days": sum(x["new_days"] for x in p["people"]),
                   "already_days": sum(x["already_days"] for x in p["people"]),
                   "locked_days": sum(x["locked_days"] for x in p["people"]),
                   "name_mismatch": sum(1 for x in p["people"] if x["name_check"] == "bad")},
    }


def apply(org, p, actor, filename=""):
    tz = timezone.get_current_timezone()
    now = timezone.now()
    days_touched, events_added = set(), 0
    with transaction.atomic():
        for x in p["people"]:
            emp = x["employee"]
            for s, kind, at in x["events"]:
                if s.work_date in x["locked"]:
                    continue
                cid = tap_id(emp, at, kind)
                if cid in x["already"]:
                    continue
                day, _ = AttendanceDay.objects.get_or_create(
                    employee=emp, date=s.work_date,
                    defaults={"organization": org, "shift": emp.default_shift})
                if day.is_locked:
                    continue
                ClockEvent.objects.create(
                    organization=org, day=day, employee=emp, kind=kind, source=ClockEvent.Source.FINGERPRINT,
                    site=emp.default_site, occurred_at=timezone.make_aware(at, tz), received_at=now,
                    flags=[], client_id=cid, machine=p["by_key"].get(x["tap_machine"].get(at, MAIN)))   # G12f.1a
                days_touched.add((emp.id, s.work_date))
                events_added += 1
        if events_added:
            record_audit(organization=org, actor=actor, action="attendance.fingerprint_import", target=org,
                         summary=f"Import fingerprint{(' ' + filename) if filename else ''} ({p['machine_name']}): "
                                 f"{events_added} tap, {len(days_touched)} hari kerja",
                         after={"events": events_added, "days": len(days_touched), "file": filename,
                                "machine": p["machine_name"]})
    return {"events": events_added, "days": len(days_touched)}
