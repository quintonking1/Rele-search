"""Test 2 scoring and questions (eval/scoring.py, eval/make_questions.py). No API calls.

  python -m unittest tests.test_test2
"""

import json
import unittest

from eval import make_questions, scoring
from eval.harness import QUESTIONS

LABELS = {
    "C1": {"complaint_id": "C1", "group": "g", "history": []},
    "C2": {"complaint_id": "C2", "group": "g", "history": [{"item": "R01-01", "date": "2026-02-01", "resolution": "full"}]},
    "C3": {"complaint_id": "C3", "group": "g", "history": [{"item": "R02-01", "date": "2026-03-01", "resolution": "partial"}]},
    "C4": {"complaint_id": "C4", "group": "other", "history": []},
    "C5": {"complaint_id": "C5", "group": "g", "history": []},
}
DATES = {"C1": "2026-01-01", "C2": "2026-01-10", "C3": "2026-01-20", "C4": "2026-01-01", "C5": "2026-05-01"}
PAIR = {"group": "g", "as_of": "2026-04-01"}


def outcomes(cited, retrieved=("C1", "C2", "C3")):
    res = scoring.score_pair(PAIR, cited, list(retrieved), LABELS, DATES)
    return {r["id"]: r["outcome"] for r in res["rows"]}, res


class TestStatus(unittest.TestCase):
    def test_expected_status_over_time(self):
        self.assertEqual(scoring.expected_status(LABELS["C2"], "2026-01-31"), scoring.CURRENT)
        self.assertEqual(scoring.expected_status(LABELS["C2"], "2026-02-01"), scoring.OUTDATED)
        self.assertEqual(scoring.expected_status(LABELS["C3"], "2026-04-01"), scoring.PARTIAL)

    def test_relevant_is_group_and_visible_only(self):
        rel = scoring.relevant_complaints(LABELS, DATES, "g", "2026-04-01")
        self.assertEqual(rel, {"C1": "current", "C2": "outdated", "C3": "partial"})  # not C4 (group) or C5 (future)


class TestScoringTable(unittest.TestCase):
    def test_perfect_answer(self):
        got, res = outcomes([{"id": "C1", "status": "current"}, {"id": "C2", "status": "outdated", "outdated_by": "R01-01"},
                             {"id": "C3", "status": "partial"}])
        self.assertEqual(set(got.values()), {scoring.CORRECT})
        self.assertTrue(next(r for r in res["rows"] if r["id"] == "C2")["right_release"])

    def test_baseline_style_answer_is_stale(self):
        got, _ = outcomes([{"id": "C1", "status": "current"}, {"id": "C2", "status": "current"},
                           {"id": "C3", "status": "current"}])
        self.assertEqual(got, {"C1": scoring.CORRECT, "C2": scoring.STALE, "C3": scoring.STALE})

    def test_omitting_an_outdated_complaint_is_fine_but_omitting_a_current_one_is_lost(self):
        got, res = outcomes([], retrieved=("C2",))
        self.assertEqual(got, {"C1": scoring.LOST, "C2": scoring.IGNORED, "C3": scoring.LOST})
        why = {r["id"]: r.get("why") for r in res["rows"]}
        self.assertEqual(why["C1"], "never retrieved")

    def test_partial_reported_as_outdated_is_lost(self):
        got, res = outcomes([{"id": "C3", "status": "outdated"}])
        self.assertEqual(got["C3"], scoring.LOST)
        self.assertEqual(next(r for r in res["rows"] if r["id"] == "C3")["why"], "cited as outdated")

    def test_off_topic_citation_is_graded_on_status_only(self):
        labels = {**LABELS, "C6": {"complaint_id": "C6", "group": "other",
                                    "history": [{"item": "R01-01", "date": "2026-02-01", "resolution": "full"}]}}
        dates = {**DATES, "C6": "2026-01-05"}
        res = scoring.score_pair(PAIR, [{"id": "C4", "status": "current"}, {"id": "C6", "status": "current"},
                                        {"id": "R01-01"}], [], labels, dates)
        off = {r["id"]: r["outcome"] for r in res["rows"] if not r["in_topic"]}
        self.assertEqual(off, {"C4": scoring.CORRECT, "C6": scoring.STALE})
        self.assertEqual(res["counts"]["relevant"], 3)  # lost findings still in-topic only
        self.assertEqual(res["counts"]["off_topic_stale"], 1)
        s = scoring.summarize([res])
        self.assertEqual(s["stale_answer_rate"], round(1 / 3, 3))  # C6 stale of C2 + C3 + C6
        self.assertEqual(s["lost_finding_rate"], 1.0)  # C1, C3 not cited

    def test_unknown_ids_are_reported(self):
        _, res = outcomes([{"id": "C999", "status": "current"}])
        self.assertEqual(res["unknown_ids"], ["C999"])

    def test_rates(self):
        _, res = outcomes([{"id": "C1", "status": "current"}, {"id": "C2", "status": "current"}])
        s = scoring.summarize([res])
        self.assertEqual(s["stale_answer_rate"], 0.5)  # C2 stale of C2 + C3
        self.assertEqual(s["lost_finding_rate"], 0.5)  # C3 lost of C1 + C3

    def test_validate_cited(self):
        self.assertIsNone(scoring.validate_cited([{"id": "C1", "status": "current"}, {"id": "R01-01"}]))
        self.assertIsNotNone(scoring.validate_cited([{"id": "C1"}]))
        self.assertIsNotNone(scoring.validate_cited("C1"))


class TestQuestions(unittest.TestCase):
    def test_committed_questions_pass_every_rule(self):
        w = make_questions.World()
        pairs = json.loads(QUESTIONS.read_text())["pairs"]
        self.assertEqual(make_questions.check(w, pairs), [])

    def test_regenerating_gives_the_committed_file(self):
        pairs, _ = make_questions.build(make_questions.World())
        self.assertEqual(pairs, json.loads(QUESTIONS.read_text())["pairs"])

    def test_every_testable_readme_item_is_covered(self):
        w = make_questions.World()
        pairs = json.loads(QUESTIONS.read_text())["pairs"]
        missing = {i for i, qs in make_questions.coverage(w, pairs).items() if not qs}
        self.assertEqual(missing, {"R01-01", "R10-04", "R19-01"})  # open decision 2: no complaints to test


if __name__ == "__main__":
    unittest.main()
