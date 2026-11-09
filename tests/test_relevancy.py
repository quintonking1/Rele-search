"""Offline tests for the full agent's status log, gates, relevancy loop, and cited block.

The llm and hybrid methods are exercised with a fake Gemini client, so no API key is needed.

  python -m unittest discover tests
"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from src import agent
from src.config import load_config
from src.relevancy import passes_gates, run_relevancy
from src.status import StatusLog
from src.store import Store


class FakeClient:
    """Stands in for genai.Client. Says a release fixes a complaint only for pairs in `fixes`."""

    def __init__(self, fixes: set[tuple[str, str]], drop: set[str] = frozenset()):
        self.fixes = fixes
        self.drop = drop  # complaint ids to leave out of the response, to test missing verdicts
        self.calls: list[str] = []  # complaint ids sent to the model, per call
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        release = contents.split("id: ", 1)[1].split("\n", 1)[0]
        ids = [line[4:] for line in contents.split("COMPLAINTS", 1)[1].splitlines() if line.startswith("id: ")]
        self.calls.append((release, ids))
        out = [
            {"id": i, "fixes": (release, i) in self.fixes, "evidence": "", "reason": "fake"}
            for i in ids
            if i not in self.drop
        ]
        return SimpleNamespace(text=json.dumps(out))


class TestRelevancy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = load_config()
        cls.records = list(Store(base.store_path).records.values())
        cls.by_id = {r["id"]: r for r in cls.records}
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = replace(base, status_dir=Path(cls.tmp.name), relevancy_candidates=10)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_status_as_of(self):
        log = StatusLog(Path(self.tmp.name) / "unit.json")
        log.reset({"method": "unit"})
        log.mark_outdated("C054", "R12-01", "2026-06-16")
        self.assertEqual(log.status_as_of("C054", "2026-05-20")["status"], "current")
        self.assertEqual(log.status_as_of("C054", "2026-06-16")["status"], "outdated")  # on the release day
        self.assertEqual(log.status_as_of("C054", "2026-07-15")["outdated_by"], "R12-01")
        self.assertEqual(log.status_as_of("C070", "2026-07-15")["status"], "current")

    def test_gates(self):
        b = self.by_id
        self.assertFalse(passes_gates(b["R16-02"], b["C085"])[0])  # Android complaint, no Android release
        self.assertFalse(passes_gates(b["R11-01"], b["C068"])[0])  # Free user, Plus+ feature
        self.assertFalse(passes_gates(b["R18-01"], b["C073"])[0])  # Enterprise, not in Plus/Business checkout
        self.assertTrue(passes_gates(b["R12-01"], b["C054"])[0])
        self.assertTrue(passes_gates(b["R12-01"], b["C059"])[0])  # Free iOS user, checkout covers both

    def test_llm_only_earlier_complaints_and_outdated_once(self):
        fake = FakeClient({("R12-01", "C054"), ("R12-01", "C059"), ("R18-01", "C054")})
        log = run_relevancy(self.cfg, self.records, "llm", fake)
        for release, ids in fake.calls:
            rdate = self.by_id[release]["date"]
            self.assertTrue(all(self.by_id[i]["date"] < rdate for i in ids), release)
            self.assertLessEqual(len(ids), 10)
        events = {e["complaint_id"]: e for e in log.events}
        self.assertEqual(events["C054"]["outdated_by"], "R12-01")  # first fix wins; R18-01 never re-flags it
        self.assertEqual(sum(e["complaint_id"] == "C054" for e in log.events), 1)
        self.assertNotIn("C070", events)

    def test_hybrid_gates_before_model(self):
        fake = FakeClient(set())
        log = run_relevancy(self.cfg, self.records, "hybrid", fake)
        sent = {(r, i) for r, ids in fake.calls for i in ids}
        self.assertNotIn(("R18-01", "C073"), sent)  # gated out, never sent to the model
        gated = [c for c in log.checks if c.get("stage") == "gate"]
        self.assertTrue(any(c["release"] == "R18-01" and c["complaint"] == "C073" for c in gated))

    def test_missing_verdict_counts_as_not_fixed(self):
        fake = FakeClient({("R12-01", "C054")}, drop={"C054"})
        log = run_relevancy(self.cfg, self.records, "llm", fake)
        self.assertNotIn("C054", {e["complaint_id"] for e in log.events})
        self.assertTrue(any(c["complaint"] == "C054" and c["reason"].startswith("MISSING") for c in log.checks))

    def test_cited_block_uses_status_log(self):
        log = StatusLog(Path(self.tmp.name) / "unit2.json")
        log.reset({"method": "unit"})
        log.mark_outdated("C054", "R12-01", "2026-06-16")
        block = agent.cited_block(["C054", "C070", "R12-01"], log, "2026-07-15")
        self.assertEqual(block, [
            {"id": "C054", "status": "outdated", "outdated_by": "R12-01"},
            {"id": "C070", "status": "current"},
            {"id": "R12-01"},
        ])
        self.assertEqual(agent.cited_block(["C054"], log, "2026-05-20"), [{"id": "C054", "status": "current"}])

    def test_prompt_shows_status(self):
        rec = self.by_id["C054"]
        text = agent.format_chunk(rec, {"status": "outdated", "outdated_by": "R12-01", "since": "2026-06-16"}, True)
        self.assertIn("status: OUTDATED as of 2026-06-16, fixed by R12-01", text)
        hidden = agent.format_chunk(rec, {"status": "outdated", "outdated_by": "R12-01", "since": "2026-06-16"}, False)
        self.assertNotIn("2026-06-16", hidden)


if __name__ == "__main__":
    unittest.main()
