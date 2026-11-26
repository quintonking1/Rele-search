"""Test 2 scoring: compare the statuses an agent cites with the label file (docs/eval_plan.md, "Scoring").

Everything here is mechanical. No model grades anything, so the same run always gets the same score.

For each (question, as_of) pair:
- Relevant complaints are every complaint in the pair's group dated on or before as_of. Their
  expected statuses come from eval/labels/complaint_labels.json at that date.
- Each relevant complaint gets one outcome from the table below, using the status the agent
  reported in its `cited` block (the baseline reports everything it cites as current).
- A cited complaint outside the group is still graded on its status (rows with in_topic false):
  calling an outdated complaint current is a stale answer whatever the topic. Leaving out an
  off-topic complaint is never a mistake, so lost findings and recall count in-topic rows only.

    Expected \\ Agent says | current | partial | outdated | not cited
    current               | correct | lost    | lost     | lost
    partial               | stale   | correct | lost     | lost
    outdated              | stale   | stale   | correct  | ignored

Each lost finding also records why, so retrieval misses are separated from relevancy-check
misses: never retrieved, retrieved but not cited, or cited with the wrong status.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels" / "complaint_labels.json"
COMPLAINTS = ROOT / "data" / "tessera_complaints.json"

CURRENT, PARTIAL, OUTDATED = "current", "partial", "outdated"
STATUSES = (CURRENT, PARTIAL, OUTDATED)
NOT_CITED = "not cited"

CORRECT, STALE, LOST, IGNORED = "correct", "stale answer", "lost finding", "ignored"
OUTCOME = {
    CURRENT: {CURRENT: CORRECT, PARTIAL: LOST, OUTDATED: LOST, NOT_CITED: LOST},
    PARTIAL: {CURRENT: STALE, PARTIAL: CORRECT, OUTDATED: LOST, NOT_CITED: LOST},
    OUTDATED: {CURRENT: STALE, PARTIAL: STALE, OUTDATED: CORRECT, NOT_CITED: IGNORED},
}


# ---------- answer key ----------


def load_labels() -> dict[str, dict]:
    return {c["complaint_id"]: c for c in json.loads(LABELS.read_text())}


def load_complaint_dates() -> dict[str, str]:
    return {c["complaint_id"]: c["date"] for c in json.loads(COMPLAINTS.read_text())["complaints"]}


def expected_status(label: dict, as_of: str) -> str:
    """Latest history entry dated on or before as_of decides: full -> outdated, partial -> partial."""
    entries = [h for h in label["history"] if h["date"] <= as_of]
    if not entries:
        return CURRENT
    latest = max(entries, key=lambda h: h["date"])
    return OUTDATED if latest["resolution"] == "full" else PARTIAL


def relevant_complaints(labels: dict[str, dict], dates: dict[str, str], group: str, as_of: str) -> dict[str, str]:
    """{complaint_id: expected status} for every complaint in the group visible at as_of."""
    return {
        cid: expected_status(label, as_of)
        for cid, label in sorted(labels.items())
        if label["group"] == group and dates[cid] <= as_of
    }


# ---------- one pair ----------


def validate_cited(cited) -> str | None:
    """Return a problem description, or None if the block follows the output contract."""
    if not isinstance(cited, list):
        return "cited is not a list"
    for entry in cited:
        if not isinstance(entry, dict) or "id" not in entry:
            return f"bad cited entry: {entry!r}"
        if str(entry["id"]).startswith("C") and entry.get("status") not in STATUSES:
            return f"complaint {entry['id']} has status {entry.get('status')!r}"
    return None


def score_pair(pair: dict, cited: list[dict], retrieved_ids: list[str], labels: dict, dates: dict) -> dict:
    """Score one agent answer. `cited` is the agent's output block; `retrieved_ids` its top k records."""
    expected = relevant_complaints(labels, dates, pair["group"], pair["as_of"])
    said = {e["id"]: e for e in cited if str(e["id"]).startswith("C")}
    retrieved = set(retrieved_ids)

    rows = []
    for cid, exp in expected.items():
        entry = said.get(cid)
        got = entry["status"] if entry else NOT_CITED
        outcome = OUTCOME[exp][got]
        row = {"id": cid, "expected": exp, "agent": got, "outcome": outcome, "retrieved": cid in retrieved}
        if outcome == LOST:
            row["why"] = ("never retrieved" if cid not in retrieved
                          else "retrieved, not cited" if got == NOT_CITED else f"cited as {got}")
        if entry and got == OUTDATED and exp == OUTDATED:
            fixes = {h["item"] for h in labels[cid]["history"] if h["date"] <= pair["as_of"]}
            row["right_release"] = entry.get("outdated_by") in fixes
        rows.append(row)

    for row in rows:
        row["in_topic"] = True

    unknown = []
    for cid in sorted(set(said) - set(expected)):
        if cid not in labels:
            unknown.append(cid)
            continue
        exp, got = expected_status(labels[cid], pair["as_of"]), said[cid]["status"]
        rows.append({"id": cid, "group": labels[cid]["group"], "expected": exp, "agent": got,
                     "outcome": OUTCOME[exp][got], "retrieved": cid in retrieved, "in_topic": False})
    return {"rows": rows, "unknown_ids": unknown, "counts": count(rows)}


def count(rows: list[dict]) -> dict:
    """In-topic counts, plus how off-topic citations were graded."""
    inside = [r for r in rows if r["in_topic"]]
    outside = [r for r in rows if not r["in_topic"]]
    c = {
        "relevant": len(inside),
        "expected_current": sum(r["expected"] == CURRENT for r in inside),
        "expected_partial": sum(r["expected"] == PARTIAL for r in inside),
        "expected_outdated": sum(r["expected"] == OUTDATED for r in inside),
        "retrieved": sum(r["retrieved"] for r in inside),
    }
    for outcome in (CORRECT, STALE, LOST, IGNORED):
        c[outcome] = sum(r["outcome"] == outcome for r in inside)
    c["off_topic_cited"] = len(outside)
    c["off_topic_not_current"] = sum(r["expected"] != CURRENT for r in outside)
    c["off_topic_stale"] = sum(r["outcome"] == STALE for r in outside)
    c["off_topic_wrongly_outdated"] = sum(r["outcome"] == LOST for r in outside)
    return c


# ---------- many pairs ----------


def ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def summarize(results: list[dict]) -> dict:
    """Headline metrics over scored pairs (failed pairs are reported separately by the harness)."""
    rows = [r for res in results for r in res["rows"]]
    c = count(rows)
    confusion = {exp: {got: 0 for got in (*STATUSES, NOT_CITED)} for exp in STATUSES}
    for r in rows:
        if r["in_topic"]:
            confusion[r["expected"]][r["agent"]] += 1
    lost_why: dict[str, int] = {}
    for r in rows:
        if "why" in r:
            lost_why[r["why"]] = lost_why.get(r["why"], 0) + 1
    return {
        "pairs": len(results),
        "counts": c,
        # stale: every complaint the grader expected not to be current, in topic or cited off topic
        "stale_answer_rate": ratio(c[STALE] + c["off_topic_stale"],
                                   c["expected_outdated"] + c["expected_partial"] + c["off_topic_not_current"]),
        "lost_finding_rate": ratio(c[LOST], c["expected_current"] + c["expected_partial"]),
        "retrieval_recall": ratio(c["retrieved"], c["relevant"]),
        "lost_finding_reasons": dict(sorted(lost_why.items())),
        "confusion": confusion,
        "off_topic": {"cited": c["off_topic_cited"], "stale": c["off_topic_stale"],
                      "wrongly_outdated": c["off_topic_wrongly_outdated"]},
        "unknown_ids": sum(len(res["unknown_ids"]) for res in results),
    }
