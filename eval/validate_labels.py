"""Check eval/labels/complaint_labels.json against the rules in prompts/01_complaint_labels.md.

  python -m eval.validate_labels

Exits non-zero on any rule violation, then prints a coverage report for review.
status_at() is the status rule from docs/eval_plan.md; the harness should reuse it.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval/labels/complaint_labels.json"

# Confirmed by the team in docs/eval_plan.md ("Which items can resolve a complaint").
KNOWN_FIXES = {
    "R02-01": ["C008"],
    "R03-02": ["C007", "C013"],
    "R09-02": ["C046", "C049"],
    "R13-01": ["C062", "C067"],
    "R20-02": ["C097"],
    "R01-03": ["C002", "C005"],
}
KNOWN_NON_FIXES = {"R03-02": ["C021"], "R01-03": ["C016"]}

# Seed table in docs/baseline_rag_prd.md, as (as_of, complaint, expected status).
SEED_EXPECTATIONS = [
    ("2026-07-15", "C054", "outdated"), ("2026-07-15", "C070", "current"),
    ("2026-05-15", "C019", "outdated"), ("2026-05-15", "C034", "outdated"),
    ("2026-05-15", "C046", "outdated"), ("2026-05-15", "C052", "current"),
    ("2026-06-30", "C035", "outdated"), ("2026-06-30", "C048", "outdated"),
    ("2026-06-30", "C060", "current"),
    ("2026-09-01", "C008", "outdated"), ("2026-09-01", "C014", "partial"),
    ("2026-09-01", "C061", "partial"),
    ("2026-10-20", "C087", "outdated"), ("2026-10-20", "C097", "outdated"),
    ("2026-10-20", "C096", "current"), ("2026-10-20", "C098", "current"),
]


def status_at(label: dict, complaint_date: str, as_of: str) -> str | None:
    """None if the complaint is not visible yet, else current, outdated, or partial."""
    if complaint_date > as_of:
        return None
    applied = [h for h in label["history"] if h["date"] <= as_of]
    if not applied:
        return "current"
    return "outdated" if applied[-1]["resolution"] == "full" else "partial"


def main() -> int:
    complaints = {c["complaint_id"]: c for c in json.loads((ROOT / "data/tessera_complaints.json").read_text())["complaints"]}
    items = {
        i["item_id"]: (r["release_date"], i["title"])
        for r in json.loads((ROOT / "data/tessera_changelog.json").read_text())["releases"]
        for i in r["items"]
    }
    labels = json.loads(LABELS.read_text())
    by_id = {l["complaint_id"]: l for l in labels}
    errors = []

    if [l["complaint_id"] for l in labels] != sorted(complaints):
        errors.append("labels must cover every complaint, in id order")
    for l in labels:
        cid, c = l["complaint_id"], complaints.get(l["complaint_id"])
        if not c:
            continue
        if not l.get("group") or not l.get("notes"):
            errors.append(f"{cid}: missing group or notes")
        if "—" in l.get("notes", ""):
            errors.append(f"{cid}: em-dash in notes")
        prev = None
        for n, h in enumerate(l["history"]):
            if h["item"] not in items:
                errors.append(f"{cid}: unknown item {h['item']}")
                continue
            if h["date"] != items[h["item"]][0]:
                errors.append(f"{cid}: {h['item']} date {h['date']} != release date {items[h['item']][0]}")
            if h["date"] <= c["date"]:
                errors.append(f"{cid}: fix {h['item']} ({h['date']}) is not after complaint ({c['date']})")
            if h["resolution"] not in ("full", "partial"):
                errors.append(f"{cid}: bad resolution {h['resolution']}")
            if prev and h["date"] < prev["date"]:
                errors.append(f"{cid}: history out of date order")
            if prev and prev["resolution"] == "full":
                errors.append(f"{cid}: entry after a full fix")
            prev = h

    for item, cids in KNOWN_FIXES.items():
        for cid in cids:
            if item not in [h["item"] for h in by_id[cid]["history"]]:
                errors.append(f"known case: {item} should fix {cid}")
    for item, cids in KNOWN_NON_FIXES.items():
        for cid in cids:
            if item in [h["item"] for h in by_id[cid]["history"]]:
                errors.append(f"known case: {item} should not fix {cid}")
    for as_of, cid, want in SEED_EXPECTATIONS:
        got = status_at(by_id[cid], complaints[cid]["date"], as_of)
        if got != want:
            errors.append(f"seed: {cid} at {as_of} is {got}, PRD expects {want}")

    # Coverage report
    fixes = defaultdict(list)
    for l in labels:
        for h in l["history"]:
            fixes[h["item"]].append(f"{l['complaint_id']}{'' if h['resolution'] == 'full' else ' (partial)'}")
    finals = defaultdict(int)
    for l in labels:
        finals[l["history"][-1]["resolution"] if l["history"] else "empty"] += 1
    groups = defaultdict(list)
    for l in labels:
        groups[l["group"]].append(l["complaint_id"])

    print(f"Final status after last release: {dict(finals)}")
    print("\nFixes per changelog item:")
    for item in sorted(items):
        print(f"  {item} {items[item][1][:48]:<48} {', '.join(fixes[item]) or 'none'}")
    print("\nGroups:")
    for g, cids in sorted(groups.items()):
        print(f"  {g:<24} {len(cids):>2}  {' '.join(cids)}")
    review = [l["complaint_id"] for l in labels if l["notes"].startswith("REVIEW:")]
    print(f"\nREVIEW: {', '.join(review) or 'none'}")

    if errors:
        print(f"\n{len(errors)} ERRORS")
        for e in errors:
            print(f"  {e}")
        return 1
    print("\nAll checks passed (schema, dates, ordering, known cases, PRD seed statuses).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
