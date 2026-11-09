"""
G12f.1a (9 Nov 2026) — several fingerprint machines: which machine a tap belongs to (pure, no database).

DKCB: plant machine = the main machine (IDs on the employee), office machine = "Mesin Kantor" with
Dept. labels "Staf, Manager". 12 is Herianto on the plant and Tari in the office; Dila is on both
(plant 14, office 2). Names below are anonymised.
"""
from datetime import datetime

from django.test import SimpleTestCase

from apps.attendance.fingerprint import Punch
from apps.attendance.machines import (AUTO, MAIN, assign, dept_conflicts, dept_owner_map, depts_in_file,
                                      id_sort_key, merge_by_employee, normalize_dept, parse_dept_labels)

KANTOR = "kantor-uuid"


def at(day, hhmm):
    h, m = hhmm.split(":")
    return datetime(2026, 10, day, int(h), int(m))


PUNCHES = [
    Punch("12", at(1, "07:55"), "K12", "DKCB"), Punch("12", at(1, "17:01"), "K12", "DKCB"),
    Punch("12", at(1, "07:56"), "K12b", "Staf"), Punch("12", at(1, "12:02"), "K12b", "Staf"),
    Punch("7", at(1, "08:20"), "K07b", "Manager"),
    Punch("14", at(2, "07:48"), "K16", "DKCB"),                     # Dila taps in on the plant ...
    Punch("2", at(2, "17:04"), "K16", "Staf"),                      # ... and out in the office
    Punch("99", at(2, "08:00"), "", "Gudang"),                      # a Dept. no machine claims
]


class Emp:
    def __init__(self, name):
        self.full_name = name

    def __repr__(self):
        return self.full_name


class DeptLabelTests(SimpleTestCase):
    def test_labels_are_split_trimmed_and_deduplicated(self):
        self.assertEqual(parse_dept_labels(" Staf, Manager;staf / Kantor\n"), ["Staf", "Manager", "Kantor"])
        self.assertEqual(parse_dept_labels(""), [])
        self.assertEqual(normalize_dept("  STAF  "), "staf")

    def test_a_dept_claimed_by_another_machine_is_a_conflict(self):
        self.assertEqual(dept_conflicts("Staf, Gudang", [("Mesin Kantor", "Staf, Manager")]),
                         [("Staf", "Mesin Kantor")])
        self.assertEqual(dept_conflicts("Gudang", [("Mesin Kantor", "Staf, Manager")]), [])


class AssignTests(SimpleTestCase):
    def setUp(self):
        self.dept_map = dept_owner_map([(KANTOR, "Staf, Manager")])

    def test_one_machine_file_keeps_every_tap_on_that_machine(self):
        groups = assign(PUNCHES, KANTOR, self.dept_map)
        self.assertEqual({k for k, _ in groups}, {KANTOR})
        groups = assign(PUNCHES, MAIN)
        self.assertEqual({k for k, _ in groups}, {MAIN})

    def test_auto_follows_the_dept_of_each_block(self):
        groups = assign(PUNCHES, AUTO, self.dept_map)
        self.assertEqual(list(groups), [(MAIN, "12"), (KANTOR, "12"), (KANTOR, "7"), (MAIN, "14"), (KANTOR, "2"),
                                        (MAIN, "99")])

    def test_depts_in_file_say_where_each_dept_goes(self):
        rows = depts_in_file(PUNCHES, AUTO, self.dept_map)
        self.assertEqual([(r["dept"], r["people"], r["taps"], r["machine_key"]) for r in rows],
                         [("DKCB", 2, 3, MAIN), ("Staf", 2, 3, KANTOR), ("Manager", 1, 1, KANTOR),
                          ("Gudang", 1, 1, MAIN)])


class MergeTests(SimpleTestCase):
    def setUp(self):
        self.herianto, self.tari, self.dila, self.anthony = Emp("Herianto"), Emp("Tari"), Emp("Dila"), Emp("Anthony")
        ids = {(MAIN, "12"): self.herianto, (KANTOR, "12"): self.tari, (MAIN, "14"): self.dila,
               (KANTOR, "2"): self.dila, (KANTOR, "7"): self.anthony}
        groups = assign(PUNCHES, AUTO, dept_owner_map([(KANTOR, "Staf, Manager")]))
        self.people, self.unknown = merge_by_employee(groups, lambda k, i: ids.get((k, i)))

    def test_same_id_on_two_machines_is_two_people(self):
        self.assertEqual(self.people[self.herianto]["times"], [at(1, "07:55"), at(1, "17:01")])
        self.assertEqual(self.people[self.tari]["times"], [at(1, "07:56"), at(1, "12:02")])

    def test_one_person_on_two_machines_gets_all_taps_with_their_machine(self):
        dila = self.people[self.dila]
        self.assertEqual(dila["ids"], [(MAIN, "14"), (KANTOR, "2")])
        self.assertEqual(dila["tap_machine"], {at(2, "07:48"): MAIN, at(2, "17:04"): KANTOR})

    def test_unknown_ids_keep_their_machine(self):
        self.assertEqual([(k, i, len(p)) for k, i, p in self.unknown], [(MAIN, "99", 1)])

    def test_the_same_minute_on_two_machines_is_one_tap(self):
        twice = [Punch("14", at(3, "07:50"), "", "DKCB"), Punch("2", at(3, "07:50"), "", "Staf")]
        groups = assign(twice, AUTO, dept_owner_map([(KANTOR, "Staf")]))
        people, _ = merge_by_employee(groups, lambda k, i: self.dila)
        self.assertEqual((people[self.dila]["times"], people[self.dila]["tap_machine"]),
                         ([at(3, "07:50")], {at(3, "07:50"): MAIN}))

    def test_ids_sort_as_numbers(self):
        self.assertEqual(sorted(["10", "2", "A3", "1"], key=id_sort_key), ["1", "2", "10", "A3"])
