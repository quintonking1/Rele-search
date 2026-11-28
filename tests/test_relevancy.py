"""Offline tests for the full agent's status log, gates, relevancy loop, and cited block.

The llm and hybrid methods are exercised with a fake OpenAI client, so no API key is needed.

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
from src.relevancy import passes_gates, run_relevancy, verdict_from_checklist
from src.status import StatusLog
from src.store import Store


class FakeClient:
    """Stands in for openai.OpenAI. Says a release fixes a complaint only for pairs in `fixes`.

    Answers in the v1 format (yes/no) or the v2 format (checklist) depending on the schema asked
    for. In v2, pairs in `partial` get a checklist whose core need is met and second need is not.
    """

    def __init__(self, fixes: set[tuple[str, str]], drop: set[str] = frozenset(),
                 partial: set[tuple[str, str]] = frozenset()):
        self.fixes = fixes
        self.partial = partial
        self.drop = drop  # complaint ids to leave out of the response, to test missing verdicts
        self.calls: list[str] = []  # complaint ids sent to the model, per call
        self.schemas: list[str] = []  # schema name per call
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, **kwargs):
        self.schemas.append(kwargs.get("response_format", {}).get("json_schema", {}).get("name"))
        text = self._generate(messages[-1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=text))])

    def _checklist(self, release, cid):
        if (release, cid) in self.fixes:
            return [{"need": "core", "met": "met", "evidence": "q"}]
        if (release, cid) in self.partial:
            return [{"need": "core", "met": "met", "evidence": "q"}, {"need": "default", "met": "not met", "evidence": ""}]
        return [{"need": "core", "met": "not met", "evidence": ""}]

    def _generate(self, contents):
        release = contents.split("id: ", 1)[1].split("\n", 1)[0]
        ids = [line[4:] for line in contents.split("COMPLAINTS", 1)[1].splitlines() if line.startswith("id: ")]
        self.calls.append((release, ids))
        if self.schemas and self.schemas[-1] == "judge_checklist":
            out = [{"id": i, "requirements": self._checklist(release, i), "reason": "fake"}
                   for i in ids if i not in self.drop]
        else:
            out = [{"id": i, "fixes": (release, i) in self.fixes, "evidence": "", "reason": "fake"}
                   for i in ids if i not in self.drop]
        return json.dumps({"results": out})


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

    def test_failed_call_is_logged_not_raised(self):
        class Boom(FakeClient):
            def _generate(self, contents):
                if contents.split("id: ", 1)[1].startswith("R12-01"):
                    raise RuntimeError("quota exhausted")
                return super()._generate(contents)

        fake = Boom({("R18-01", "C054")})
        log = run_relevancy(self.cfg, self.records, "llm", fake, tag="fail-test")
        self.assertEqual(log.meta["counts"]["failed_calls"], 1)
        self.assertEqual(log.meta["failures"][0]["release"], "R12-01")
        self.assertTrue(all(c["stage"] == "error" for c in log.checks if c["release"] == "R12-01"))
        self.assertTrue((self.cfg.status_dir / "failed_calls.jsonl").exists())
        self.assertEqual({e["complaint_id"]: e["outdated_by"] for e in log.events}.get("C054"), "R18-01")

    def test_runs_are_appended_and_tagged(self):
        path = Path(self.tmp.name) / "append.json"
        path.write_text(json.dumps({"meta": {"method": "old"}, "events": [], "checks": []}))  # legacy format
        before = path.read_text()
        for tag in ("first", "second"):
            log = StatusLog(path)
            log.start_run({"method": "unit"}, tag)
            log.mark_outdated("C054", "R12-01", "2026-06-16")
            log.save()
        self.assertEqual(path.read_text(), before)  # legacy file untouched
        self.assertEqual(StatusLog(path).tags(), ["legacy", "first", "second"])
        self.assertEqual(StatusLog(path).meta["tag"], "second")  # latest by default
        self.assertEqual(StatusLog(path, "legacy").events, [])
        with self.assertRaises(ValueError):
            StatusLog(path).start_run({"method": "unit"}, "first")  # tags are unique

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

    def test_v1_judge_still_available(self):
        fake = FakeClient({("R12-01", "C054")})
        log = run_relevancy(self.cfg, self.records, "llm", fake, tag="v1-check", judge_version="v1")
        self.assertEqual(set(fake.schemas), {"judge_verdicts"})
        self.assertEqual(log.meta["judge"], "v1")
        self.assertEqual({e["complaint_id"] for e in log.events}, {"C054"})

    def test_checklist_verdict_rule(self):
        met = {"need": "x", "met": "met", "evidence": "q"}
        partly = {"need": "x", "met": "partly", "evidence": "q"}
        no = {"need": "x", "met": "not met", "evidence": ""}
        for v in ("v2", "v2.1"):
            self.assertEqual(verdict_from_checklist([met, met], v), "fixed")
            self.assertEqual(verdict_from_checklist([met, no], v), "partial")
            self.assertEqual(verdict_from_checklist([met, partly], v), "partial")
            self.assertEqual(verdict_from_checklist([no, met], v), "not fixed")  # core need not met
            self.assertEqual(verdict_from_checklist([], v), "not fixed")
        # The one rule that differs: a core need that is only partly met.
        self.assertEqual(verdict_from_checklist([partly, met], "v2"), "partial")
        self.assertEqual(verdict_from_checklist([partly, met], "v2.1"), "not fixed")

    def test_v21_prompt_drops_default_rules_only(self):
        from src.relevancy import JUDGE_V2_SYSTEM_PROMPT, JUDGE_V21_SYSTEM_PROMPT
        self.assertIn("default experience", JUDGE_V2_SYSTEM_PROMPT)
        self.assertNotIn("default experience", JUDGE_V21_SYSTEM_PROMPT)
        self.assertNotIn("default", JUDGE_V21_SYSTEM_PROMPT.lower())
        self.assertIn("anything it does not list is not covered", JUDGE_V21_SYSTEM_PROMPT)

    def test_v2_partial_then_full_fix(self):
        # R16-01 partly fixes C014; R18-01 (later) fixes it fully. C054 is fixed outright by R12-01.
        fake = FakeClient({("R12-01", "C054"), ("R18-01", "C014")}, partial={("R16-01", "C014")})
        cfg = replace(self.cfg, relevancy_candidates=500)  # judge every open complaint, so R18-01 sees C014
        log = run_relevancy(cfg, self.records, "llm", fake, tag="v2-check")
        self.assertEqual(set(fake.schemas), {"judge_checklist"})
        self.assertEqual(log.meta["judge"], "v2.1")
        self.assertEqual(log.status_as_of("C014", "2026-08-01")["status"], "current")
        self.assertEqual(log.status_as_of("C014", "2026-08-20"), {"status": "partial", "partial_by": "R16-01", "since": "2026-08-18"})
        self.assertEqual(log.status_as_of("C014", "2026-10-01")["outdated_by"], "R18-01")
        self.assertEqual(log.status_as_of("C054", "2026-07-01")["status"], "outdated")
        checks = [c for c in log.checks if c["complaint"] == "C014" and c["release"] == "R16-01"]
        self.assertEqual(checks[0]["verdict"], "partial")
        self.assertEqual(len(checks[0]["requirements"]), 2)

    def test_cited_block_and_prompt_show_partial(self):
        log = StatusLog(Path(self.tmp.name) / "unit3.json")
        log.start_run({"method": "unit", "judge": "v2"}, "p")
        log.mark_partial("C014", "R16-01", "2026-08-18")
        self.assertEqual(agent.cited_block(["C014"], log, "2026-09-01"),
                         [{"id": "C014", "status": "partial", "partial_by": "R16-01"}])
        line = agent.status_line(log.status_as_of("C014", "2026-09-01"), True)
        self.assertEqual(line, "status: PARTIAL as of 2026-08-18, partly fixed by R16-01")
        self.assertIn("PARTIAL complaint", agent.system_prompt(log))
        v1 = StatusLog(Path(self.tmp.name) / "unit4.json")
        v1.start_run({"method": "unit"}, "old")
        self.assertEqual(agent.system_prompt(v1), agent.SYSTEM_PROMPT)  # v1 logs keep the v1 prompt exactly

    def test_prompt_shows_status(self):
        rec = self.by_id["C054"]
        text = agent.format_chunk(rec, {"status": "outdated", "outdated_by": "R12-01", "since": "2026-06-16"}, True)
        self.assertIn("status: OUTDATED as of 2026-06-16, fixed by R12-01", text)
        hidden = agent.format_chunk(rec, {"status": "outdated", "outdated_by": "R12-01", "since": "2026-06-16"}, False)
        self.assertNotIn("2026-06-16", hidden)


if __name__ == "__main__":
    unittest.main()
