# =============================================================================
# === backend/apps/attendance/machines.py ===
# =============================================================================
"""
Several fingerprint machines in one company (G12f.1a, 9 Nov 2026). Pure Python, no Django.

DKCB has a plant machine and an office machine whose IDs overlap: 12 is Herianto on the plant and
Tari in the office. So an ID only means something together with its machine.

  - The "main machine" (MAIN) is the one whose IDs sit on the employee ("ID Mesin Fingerprint").
    A company with one machine never sees anything else.
  - Every other machine is a FingerprintMachine; an employee's ID on it is an EmployeeMachineId.
  - An import is from the main machine, from one named machine, or AUTO: Anthony's monthly
    workbook puts both machines in one sheet, each block labelled "Dept.: DKCB" or "Dept.: Staf".
    A machine lists the Dept. labels that belong to it ("Staf, Manager"); a block whose Dept. no
    machine claims belongs to the main machine.
  - One person can be on two machines (Dila: plant 14, office 2). Their taps are put together
    before pairing, so an in on one machine and an out on the other make one day.
"""
import re
from collections import OrderedDict

MAIN = "main"                 # the machine whose IDs are on the employee
AUTO = "auto"                 # choose per block by its Dept. label
ALL = "all"                   # only for "Hapus data import": every machine
MAIN_NAME = "Mesin utama"
AUTO_NAME = "Otomatis menurut Dept. di file"
LABEL_SPLIT = re.compile(r"[,;/\n]+")


def normalize_dept(text):
    """' Staf ' / 'STAF' / 'staf' -> 'staf'. Dept. labels are compared this way."""
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def parse_dept_labels(text):
    """'Staf, Manager;  staf' -> ['Staf', 'Manager'] (order kept, repeats dropped, case of the first kept)."""
    out, seen = [], set()
    for part in LABEL_SPLIT.split(str(text or "")):
        label = re.sub(r"\s+", " ", part).strip()
        key = normalize_dept(label)
        if key and key not in seen:
            seen.add(key)
            out.append(label)
    return out


def dept_owner_map(machines):
    """machines: [(key, dept_labels text)] of ACTIVE machines -> {normalized dept: key}. First claim wins."""
    owners = {}
    for key, labels in machines:
        for label in parse_dept_labels(labels):
            owners.setdefault(normalize_dept(label), key)
    return owners


def dept_conflicts(labels, others):
    """
    labels: the Dept. labels text being saved; others: [(machine name, dept_labels text)] of the other
    active machines. -> [(label, other machine name)] for every label another machine already claims.
    """
    claimed = {}
    for name, text in others:
        for label in parse_dept_labels(text):
            claimed.setdefault(normalize_dept(label), name)
    return [(label, claimed[normalize_dept(label)]) for label in parse_dept_labels(labels)
            if normalize_dept(label) in claimed]


def machine_for(punch, mode, dept_map):
    """The machine key a punch belongs to: MAIN, a machine key, or (AUTO) the owner of its Dept."""
    if mode == AUTO:
        return dept_map.get(normalize_dept(punch.dept), MAIN)
    return mode


def assign(punches, mode, dept_map=None):
    """punches -> OrderedDict {(machine key, machine id): [punches]} in file order."""
    groups = OrderedDict()
    for p in punches:
        groups.setdefault((machine_for(p, mode, dept_map or {}), p.machine_id), []).append(p)
    return groups


def depts_in_file(punches, mode, dept_map):
    """
    [{dept, people, taps, machine_key, claimed}] for each Dept. label in the file ("" = none), in file order.
    G12f.3.4: claimed = a machine lists this Dept.; unclaimed labels are read as the main machine.
    """
    seen = OrderedDict()
    for p in punches:
        d = seen.setdefault(normalize_dept(p.dept), {"dept": p.dept.strip(), "ids": set(), "taps": 0,
                                                     "machine_key": machine_for(p, mode, dept_map),
                                                     "claimed": normalize_dept(p.dept) in (dept_map or {})})
        d["ids"].add(p.machine_id)
        d["taps"] += 1
    return [{"dept": d["dept"], "people": len(d["ids"]), "taps": d["taps"], "machine_key": d["machine_key"],
             "claimed": d["claimed"]} for d in seen.values()]


def merge_by_employee(groups, lookup):
    """
    groups: from assign(); lookup(machine key, machine id) -> employee or None.

    -> (people, unknown)
       people:  OrderedDict {employee: {"times": [datetime], "tap_machine": {datetime: key},
                                        "ids": [(key, machine id)], "name": name in the file}}
       unknown: [(key, machine id, [punches])] for IDs no employee has on that machine.
    A tap at the same minute on two machines is one tap; the first machine it was seen on keeps it.
    """
    people, unknown = OrderedDict(), []
    for (key, machine_id), punches in groups.items():
        emp = lookup(key, machine_id)
        if emp is None:
            unknown.append((key, machine_id, punches))
            continue
        person = people.setdefault(emp, {"times": [], "tap_machine": {}, "ids": [], "name": ""})
        if (key, machine_id) not in person["ids"]:
            person["ids"].append((key, machine_id))
        for p in punches:
            if p.at not in person["tap_machine"]:
                person["tap_machine"][p.at] = key
                person["times"].append(p.at)
            if p.name and not person["name"]:
                person["name"] = p.name
    return people, unknown


def id_sort_key(machine_id):
    """'2' < '10' < 'A3': numbers first in number order, then text."""
    return (0, int(machine_id), "") if machine_id.isdigit() else (1, 0, machine_id)
