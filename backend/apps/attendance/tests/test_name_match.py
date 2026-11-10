"""
G12f.2 (9 Nov 2026) — does the name in the machine look like the employee? (pure, no database)

The pairs are DKCB's real machine names against the full names in Anthony's leave file. The
"different" pairs are what a wrong machine choice produces (plant ID 2 = Feny read on the office
machine, where 2 = Apriyani "Dila").
"""
from django.test import SimpleTestCase

from apps.attendance.name_match import MATCH, best_candidate, name_score, names_match, suggest_pairs

SAME = [("GANDA", "Ganda Bintan Prasongko"), ("Arif", "Arief Chaniago"), ("Ridwan", "Riduan H.S"),
        ("YUDA", "Prayuda"), ("Tari", "Mentari Rezeki Anandha"), ("Dila", "Apriyani Fadhilah"),
        ("Vincent", "Vinsensius Umakela"), ("Syaifull", "Syaiful Bahri"), ("Supriyadi", "Supriadi"),
        ("EkoH", "Eko Haryanto"), ("IQBAL", "M Iqbal Hidayat"), ("AJI", "Nur Aji Affifudin"),
        ("Sinaga", "Parsaoran Sinaga"), ("Kamarol", "M. Kamarol"), ("HERIANTO", "Herianto")]
DIFFERENT = [("Feny", "Apriyani Fadhilah"), ("HERIANTO", "Mentari Rezeki Anandha"), ("AMSAR", "Anthony"),
             ("EkoH", "M. Kamarol"), ("Dila", "Feny Saputra"), ("JOKO", "Junaidi"), ("Taufik", "Togar"),
             ("Hadi", "Herianto"), ("Edi", "Eko Haryanto"),
             ("Hadi", "Prayuda Adi Susanto"), ("Edi", "Prayuda Adi Susanto"), ("Joan", "Joko Apriyanto")]  # G12f.2b


class NameMatchTests(SimpleTestCase):
    def test_machine_nicknames_match_the_full_name(self):
        for short, full in SAME:
            self.assertTrue(names_match(short, full), f"{short} / {full}: {name_score(short, full)}")

    def test_a_wrong_machine_pairs_names_that_do_not_match(self):
        for short, full in DIFFERENT:
            self.assertFalse(names_match(short, full), f"{short} / {full}: {name_score(short, full)}")

    def test_no_name_in_the_file_means_nothing_to_compare(self):
        for short in ("", None, "12", "M"):
            self.assertIsNone(names_match(short, "Ganda Bintan Prasongko"), repr(short))

    def test_best_candidate_proposes_the_most_similar_name(self):
        people = [("k14", "Amsar Sormin"), ("k22", "Herianto"), ("k05", "Arief Chaniago")]
        self.assertEqual(best_candidate("AMSAR", people), ("k14", 1.0))
        self.assertEqual(best_candidate("Arif", people)[0], "k05")
        self.assertIsNone(best_candidate("Risman", people))
        self.assertGreaterEqual(best_candidate("Arif", people)[1], MATCH)

    def test_suggestions_are_decided_for_the_whole_file_best_first(self):
        """G12f.2b (10 Nov): Hadi took Prayuda (via "adi") before YUDA got a look; iwan must not take Riduan."""
        wanted = [("id5", "kantor", "Hadi"), ("id6", "kantor", "YUDA"), ("id18", "kantor", "Ridwan"),
                  ("id19", "kantor", "iwan")]
        people = {"kantor": [("prayuda", "Prayuda Adi Susanto"), ("riduan", "Riduan H.S"), ("hadi", "Hadi Saputra")]}
        picks = suggest_pairs(wanted, people)
        self.assertEqual({k: v[0] for k, v in picks.items()}, {"id5": "hadi", "id6": "prayuda", "id18": "riduan"})
        self.assertEqual(suggest_pairs([("id5", "kantor", "Hadi")], {"kantor": [("prayuda", "Prayuda Adi Susanto")]}), {})
