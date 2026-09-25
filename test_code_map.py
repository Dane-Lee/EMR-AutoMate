"""The ref -> name cheat sheet, and the refusals that keep it off the wrong record.

Fake names throughout (`Smith, Jane` / `Doe, John`), per CLAUDE.md. The point of every
test here is a REFUSAL: the cheat sheet exists to save Dane forty picks, and the moment
it is less than certain it has to hand the pick back rather than fill a medical record
with a guess.
"""

import csv
import os
import tempfile
import unittest

import encounter_builder as eb


def _csv(rows):
    fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     newline="", encoding="utf-8")
    csv.writer(fh).writerows(rows)
    fh.close()
    return fh.name


ROSTER = [{"name": "Smith, Jane"}, {"name": "Doe, John"},
          {"name": "Roe, Richard"}, {"name": "Smith, Janet"}]


class LoadCodeMap(unittest.TestCase):

    def test_reads_pairs_and_skips_the_header(self):
        p = _csv([["Code", "Name"], ["A2", "Smith, Jane"], ["B10", "Doe, John"]])
        mapping, problem = eb.load_code_map(p)
        self.assertEqual(len(mapping), 2)
        self.assertEqual(mapping["A2"], "Smith, Jane")
        self.assertFalse(problem)

    def test_a_code_with_two_different_names_is_dropped_not_guessed(self):
        # The whole point. Picking either one puts an encounter on a 50/50 person.
        p = _csv([["A2", "Smith, Jane"], ["A2", "Doe, John"], ["B1", "Roe, Richard"]])
        mapping, problem = eb.load_code_map(p)
        self.assertNotIn("A2", mapping)
        self.assertIn("B1", mapping)
        self.assertIn("A2", problem)

    def test_the_same_code_twice_with_the_same_name_is_fine(self):
        p = _csv([["A2", "Smith, Jane"], ["A2", "Smith, Jane"]])
        mapping, problem = eb.load_code_map(p)
        self.assertEqual(mapping["A2"], "Smith, Jane")
        self.assertFalse(problem)

    def test_blank_rows_and_half_rows_are_ignored(self):
        p = _csv([["A2", "Smith, Jane"], ["", ""], ["B3", ""], ["", "Doe, John"]])
        mapping, _ = eb.load_code_map(p)
        self.assertEqual(list(mapping), ["A2"])

    def test_missing_file_reports_instead_of_raising(self):
        mapping, problem = eb.load_code_map(
            os.path.join(tempfile.gettempdir(), "no_such_code_map.csv"))
        self.assertEqual(mapping, {})
        self.assertTrue(problem)

    def test_no_cheat_sheet_at_all_explains_where_to_put_one(self):
        # Default path, with the directory pointed somewhere empty.
        old = eb.CODE_MAP_DIR
        try:
            eb.CODE_MAP_DIR = tempfile.mkdtemp()
            mapping, problem = eb.load_code_map()
            self.assertEqual(mapping, {})
            self.assertIn("code_map.csv", problem)
        finally:
            eb.CODE_MAP_DIR = old


class ResolveRefs(unittest.TestCase):

    def test_an_unambiguous_code_resolves(self):
        res, un = eb.resolve_refs(["A2"], {"A2": "Smith, Jane"}, ROSTER)
        self.assertEqual(res["A2"], "Smith, Jane")
        self.assertFalse(un)

    def test_a_code_not_in_the_sheet_falls_back(self):
        res, un = eb.resolve_refs(["Z9"], {"A2": "Smith, Jane"}, ROSTER)
        self.assertFalse(res)
        self.assertEqual(un[0][0], "Z9")

    def test_a_name_not_on_the_roster_falls_back(self):
        res, un = eb.resolve_refs(["A2"], {"A2": "Nobody, Real"}, ROSTER)
        self.assertFalse(res)
        self.assertIn("roster", un[0][1])

    def test_two_roster_people_with_one_name_refuse_rather_than_picking(self):
        # The case that matters: the site really does have two Jane Smiths. An exact
        # match on both is not a match, and picking the first is how an encounter lands
        # on the wrong person.
        res, un = eb.resolve_refs(["A2"], {"A2": "Smith, Jane"},
                                  [{"name": "Smith, Jane"}, {"name": "Smith, Jane"}])
        self.assertFalse(res)
        self.assertIn("ambiguous", un[0][1])

    def test_a_bare_surname_matches_nobody(self):
        # "Smith" alone is not enough to name a person, and it is not treated as one.
        res, un = eb.resolve_refs(["A2"], {"A2": "Smith"},
                                  [{"name": "Smith, Jane"}, {"name": "Smith, Janet"}])
        self.assertFalse(res)
        self.assertIn("roster", un[0][1])

    def test_exact_match_beats_a_near_neighbour(self):
        # "Smith, Jane" must not be diluted into ambiguity by "Smith, Janet".
        res, _ = eb.resolve_refs(["A2"], {"A2": "Smith, Jane"}, ROSTER)
        self.assertEqual(res["A2"], "Smith, Jane")

    def test_refs_are_matched_as_written_including_whitespace(self):
        res, _ = eb.resolve_refs([" A2 "], {"A2": "Smith, Jane"}, ROSTER)
        self.assertEqual(res[" A2 "], "Smith, Jane")


if __name__ == "__main__":
    unittest.main(verbosity=2)
