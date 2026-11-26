"""Write eval/questions/questions.json: the (question, as_of) pairs for Test 2.

  python -m eval.make_questions            # writes questions.json (refuses to overwrite)
  python -m eval.make_questions --force    # regenerate
  python -m eval.make_questions --check    # only validate the existing questions.json

Approved 2026-11-26. This follows the coverage table and rules in eval/prompts/02_questions.md,
but code picks the dates and targets instead of a model, so every pair can be checked and
regenerated. Question wording is written by hand, one per group, in
eval/questions/group_questions.json, so pairs in a group share wording by construction.

Coverage, from the roles in eval/tessera_changelog_README.md and the fix histories in the labels:
- Invalidator: 2 pairs (before, after) in each group where it fixes complaints. An invalidator
  that fixes no complaint is skipped (README open decision 2: R01-01, R19-01).
- Partial: 1 pair after the release. R10-04 has no partial complaint and is skipped (decision 2).
- Decoy: 1 pair after the decoy. It checks both halves: complaints of the target finding keep
  their status, and complaints the decoy itself fixes flip. When the two halves sit in different
  groups, each half gets its own pair in its own group (decision 1, option a). When a decoy ships
  the same day as the invalidator it is a decoy for, the target half cannot be separated in time,
  so only the decoy's own complaints are tested and the invalidator's after pair covers the rest.
- Neutral that fixes complaints: like a decoy with no target half.
- still_true: 1 pair per group that has never-fixed complaints, as_of 2026-10-31.
Pairs that land on the same group and date are merged (rule 6). Each pair's `tests` lists every
item it covers with that item's own targets; `target_complaints` is their union.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .scoring import CURRENT, OUTDATED, PARTIAL, expected_status, load_complaint_dates, load_labels

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "eval" / "tessera_changelog_README.md"
CHANGELOG = ROOT / "data" / "tessera_changelog.json"
GROUP_QUESTIONS = ROOT / "eval" / "questions" / "group_questions.json"
SPLIT = ROOT / "eval" / "split.json"
OUT = ROOT / "eval" / "questions" / "questions.json"

STILL_TRUE_AS_OF = date(2026, 10, 31)
MIN_GAP = 3  # days between any as_of and any release in its group (rule 4)
MAX_AFTER = 28  # after-pairs sit within four weeks of the release they test
BANNED = re.compile(r"\b(still|anymore|any more|now that|recently|after the update)\b", re.IGNORECASE)
PRIORITY = ["invalidator_after", "invalidator_before", "partial", "decoy", "still_true"]


# ---------- inputs ----------


def d(s: str) -> date:
    return date.fromisoformat(s)


def load_roles() -> dict[str, dict]:
    """{item_id: {"role": invalidator|decoy|partial|neutral, "decoy_for": item or None}} from the README table."""
    roles = {}
    for line in README.read_text().splitlines():
        m = re.match(r"\|\s*(R\d{2}-\d{2})\b[^|]*\|\s*[\d-]+\s*\|\s*([^|]+?)\s*\|", line)
        if not m:
            continue
        role = m.group(2)
        target = re.search(r"Decoy for (R\d{2}-\d{2})", role)
        roles[m.group(1)] = {"role": role.split()[0].lower(), "decoy_for": target.group(1) if target else None}
    return roles


def load_release_dates() -> dict[str, date]:
    data = json.loads(CHANGELOG.read_text())
    return {it["item_id"]: d(rel["release_date"]) for rel in data["releases"] for it in rel["items"]}


class World:
    def __init__(self):
        self.labels = load_labels()
        self.dates = load_complaint_dates()
        self.roles = load_roles()
        self.released = load_release_dates()
        self.questions = json.loads(GROUP_QUESTIONS.read_text())["questions"]
        self.split = {g: s for s, gs in json.loads(SPLIT.read_text())["groups"].items() for g in gs}
        self.fixed_by = defaultdict(list)  # item -> complaints whose history includes it
        for cid, label in self.labels.items():
            for h in label["history"]:
                self.fixed_by[h["item"]].append(cid)

    def group(self, cid: str) -> str:
        return self.labels[cid]["group"]

    def cdate(self, cid: str) -> date:
        return d(self.dates[cid])

    def status(self, cid: str, when: date) -> str:
        return expected_status(self.labels[cid], when.isoformat())

    def group_releases(self, group: str) -> set[date]:
        """Release dates of every item in the history of a complaint in this group."""
        return {d(h["date"]) for l in self.labels.values() if l["group"] == group for h in l["history"]}

    def next_change(self, cids: list[str], after: date) -> date | None:
        """First date after `after` on which any of these complaints changes status."""
        later = [d(h["date"]) for c in cids for h in self.labels[c]["history"] if d(h["date"]) > after]
        return min(later) if later else None


# ---------- choosing dates ----------


def pick_date(lo: date, hi: date, avoid: set[date], prefer_late: bool) -> date | None:
    """A day in [lo, hi] at least MIN_GAP days from every date in `avoid`.

    Valid days form runs between releases. Before-pairs take the last run and after-pairs the
    first, so each pair sits next to the release it tests, as long as that run has 3 or more days;
    otherwise the longest run. The middle day of the run is returned.
    """
    days, day = [], lo
    while day <= hi:
        if all(abs((day - a).days) >= MIN_GAP for a in avoid):
            days.append(day)
        day += timedelta(days=1)
    if not days:
        return None
    runs, run = [], [days[0]]
    for x in days[1:]:
        if (x - run[-1]).days == 1:
            run.append(x)
        else:
            runs.append(run)
            run = [x]
    runs.append(run)
    nearest = runs[-1] if prefer_late else runs[0]
    best = nearest if len(nearest) >= 3 else max(runs, key=len)
    return best[len(best) // 2]


def after_window(w: World, item: str, cids: list[str], lo: date | None = None) -> tuple[date, date]:
    start = w.released[item] + timedelta(days=MIN_GAP)
    lo = max(start, lo) if lo else start
    nxt = w.next_change(cids, w.released[item])
    hi = lo + timedelta(days=MAX_AFTER)
    if nxt:
        hi = min(hi, nxt - timedelta(days=MIN_GAP))
    return lo, hi


# ---------- building pairs ----------


def specs(w: World) -> tuple[list[dict], list[str]]:
    """Pair specifications before dates are chosen, plus notes on anything skipped."""
    out, skipped = [], []

    def by_group(cids):
        groups = defaultdict(list)
        for c in cids:
            groups[w.group(c)].append(c)
        return groups

    for item, info in sorted(w.roles.items()):
        role, fixed = info["role"], sorted(w.fixed_by.get(item, []))
        rel = w.released[item]

        if role == "invalidator":
            if not fixed:
                skipped.append(f"{item} invalidator: fixes no complaint (open decision 2)")
            for g, cids in by_group(fixed).items():
                lo = max(w.cdate(c) for c in cids)
                out.append({"group": g, "type": "invalidator_before", "item": item, "targets": cids,
                            "lo": lo, "hi": rel - timedelta(days=MIN_GAP), "late": True, "notes": ""})
                lo, hi = after_window(w, item, cids)
                out.append({"group": g, "type": "invalidator_after", "item": item, "targets": cids,
                            "lo": lo, "hi": hi, "late": False, "notes": ""})

        elif role == "partial":
            partial = [c for c in fixed if any(h["item"] == item and h["resolution"] == "partial"
                                               for h in w.labels[c]["history"])]
            if not partial:
                skipped.append(f"{item} partial: no complaint has a partial entry for it (open decision 2)")
            for g, cids in by_group(partial).items():
                lo, hi = after_window(w, item, cids)
                out.append({"group": g, "type": "partial", "item": item, "targets": cids,
                            "lo": lo, "hi": hi, "late": False, "notes": ""})

        elif role in ("decoy", "neutral"):
            target = info["decoy_for"]
            finding = sorted(w.fixed_by.get(target, [])) if target else []
            same_day = bool(target) and w.released[target] == rel
            if same_day and finding:
                skipped.append(f"{item} decoy: ships the same day as {target}, so its target-finding half is "
                               f"covered by {target}'s after pair")
                finding = []
            if role == "neutral" and not fixed:
                continue
            groups = by_group(fixed)
            for g, cids in by_group(finding).items():
                groups.setdefault(g, [])
            cross = len(groups) > 1
            for g in sorted(groups):
                narrow = groups[g]
                half = [c for c in finding if w.group(c) == g]
                if not narrow and not half:
                    continue
                lo = min(w.cdate(c) for c in half) if half else None
                lo, hi = after_window(w, item, narrow + half, lo)
                out.append({"group": g, "type": "decoy", "item": item, "targets": narrow + half,
                            "narrow": narrow, "half": half, "decoy_for": target, "neutral": role == "neutral",
                            "cross": cross, "lo": lo, "hi": hi, "late": False, "notes": ""})

    for g in sorted({l["group"] for l in w.labels.values()}):
        never = sorted(c for c, l in w.labels.items() if l["group"] == g and not l["history"])
        if never:
            out.append({"group": g, "type": "still_true", "item": None, "targets": never,
                        "lo": STILL_TRUE_AS_OF, "hi": STILL_TRUE_AS_OF, "late": False, "notes": ""})
    return out, skipped


def decoy_notes(s: dict, half: list[str]) -> str:
    parts = []
    if half:
        parts.append(f"target finding of {s['decoy_for']} ({', '.join(half)}) must keep its status")
    if s["narrow"]:
        parts.append(f"complaints {s['item']} fixes ({', '.join(s['narrow'])}) must flip")
    if s["neutral"]:
        parts.append("README role is neutral, but the labels show it fixes complaints")
    if s["cross"]:
        parts.append("cross-group decoy: this half only (open decision 1, option a)")
    return "; ".join(parts)


def build(w: World) -> tuple[list[dict], list[str]]:
    raw, skipped = specs(w)
    placed = []
    for s in raw:
        avoid = w.group_releases(s["group"]) | ({w.released[s["item"]]} if s["item"] else set())
        when = pick_date(s["lo"], s["hi"], avoid, s["late"]) if s["lo"] <= s["hi"] else None
        if when is None:
            skipped.append(f"{s['item']} {s['type']} in {s['group']}: no date satisfies the spacing and "
                           f"visibility rules between {s['lo']} and {s['hi']}")
            continue
        visible = [c for c in s["targets"] if w.cdate(c) <= when]
        if s["type"] == "decoy":
            s["notes"] = decoy_notes(s, [c for c in s["half"] if c in visible])
        placed.append({**s, "as_of": when, "targets": visible})

    merged: dict[tuple[str, date], dict] = {}
    for p in sorted(placed, key=lambda p: PRIORITY.index(p["type"])):
        key = (p["group"], p["as_of"])
        tests = {"item": p["item"], "type": p["type"], "targets": p["targets"], "notes": p["notes"]}
        if key not in merged:
            merged[key] = {**p, "tests": [tests]}
        else:
            m = merged[key]
            m["targets"] = sorted(set(m["targets"]) | set(p["targets"]))
            m["tests"].append(tests)

    pairs = []
    for i, ((g, when), m) in enumerate(sorted(merged.items()), start=1):
        primary, others = m["tests"][0], m["tests"][1:]
        notes = [primary["notes"]] if primary["notes"] else []
        notes += [f"merged with {o['type']} {o['item'] or ''}".strip() + (f" ({o['notes']})" if o["notes"] else "")
                  for o in others]
        pairs.append({
            "question_id": f"Q{i:03d}",
            "question": w.questions[g],
            "as_of": when.isoformat(),
            "group": g,
            "type": primary["type"],
            "target_item": primary["item"],
            "target_complaints": sorted(m["targets"]),
            "tests": [{"type": t["type"], "item": t["item"], "target_complaints": sorted(t["targets"])}
                      for t in m["tests"]],
            "notes": "; ".join(notes),
        })
    return pairs, skipped


# ---------- checks ----------


def check(w: World, pairs: list[dict]) -> list[str]:
    """Rules from eval/prompts/02_questions.md. Returns a list of problems (empty means pass)."""
    problems = []
    wording = defaultdict(set)
    for p in pairs:
        qid, g, when = p["question_id"], p["group"], d(p["as_of"])
        wording[g].add(p["question"])
        if BANNED.search(p["question"]):
            problems.append(f"{qid}: question hints at the answer: {p['question']!r}")
        items = [t["item"] for t in p["tests"]]
        avoid = w.group_releases(g) | {w.released[i] for i in items if i}
        close = [a for a in avoid if abs((when - a).days) < MIN_GAP]
        if close:
            problems.append(f"{qid}: as_of {when} is within {MIN_GAP} days of a release on {close[0]}")
        for c in p["target_complaints"]:
            if w.cdate(c) > when:
                problems.append(f"{qid}: target {c} is dated after as_of")
            if w.group(c) != g:
                problems.append(f"{qid}: target {c} is in group {w.group(c)}, not {g}")
        for t in p["tests"]:
            problems += check_type(w, qid, {**t, "targets": t["target_complaints"]}, when)
    for g, qs in wording.items():
        if len(qs) > 1:
            problems.append(f"group {g}: pairs use {len(qs)} different wordings")
    return problems


def check_type(w: World, qid: str, t: dict, when: date) -> list[str]:
    want = {"invalidator_before": {CURRENT}, "invalidator_after": {OUTDATED}, "partial": {PARTIAL},
            "still_true": {CURRENT}}.get(t["type"])
    problems = []
    for c in t["targets"]:
        now = w.status(c, when)
        if want is not None and now not in want:
            problems.append(f"{qid}: {t['type']} {t['item']} expects {c} {'/'.join(want)}, label gives {now}")
        if t["type"] == "decoy":
            item = t["item"]
            fixed_here = item in {h["item"] for h in w.labels[c]["history"]}
            if fixed_here and now not in (OUTDATED, PARTIAL):
                problems.append(f"{qid}: decoy {item} should have flipped {c}, label gives {now}")
            if not fixed_here:
                before = w.status(c, w.released[item] - timedelta(days=1))
                if now != before:
                    problems.append(f"{qid}: decoy {item}: {c} changed from {before} to {now}")
    return problems


def coverage(w: World, pairs: list[dict]) -> dict[str, list[str]]:
    tested = defaultdict(list)
    for p in pairs:
        for item in [t["item"] for t in p["tests"]]:
            if item:
                tested[item].append(p["question_id"])
    return {item: tested.get(item, []) for item, info in sorted(w.roles.items()) if info["role"] != "neutral"}


def report(w: World, pairs: list[dict], skipped: list[str]) -> None:
    print(f"{len(pairs)} pairs")
    print("by type: " + ", ".join(f"{k} {v}" for k, v in Counter(p["type"] for p in pairs).most_common()))
    by_split = Counter(w.split.get(p["group"], "?") for p in pairs)
    print("by split: " + ", ".join(f"{k} {v}" for k, v in sorted(by_split.items())))
    print("by group: " + ", ".join(f"{g} {n}" for g, n in sorted(Counter(p["group"] for p in pairs).items())))
    missing = [item for item, qs in coverage(w, pairs).items() if not qs]
    print(f"README items not tested: {', '.join(missing) or 'none'}")
    for s in skipped:
        print(f"  note: {s}")
    merges = [p for p in pairs if len(p["tests"]) > 1]
    print(f"{len(merges)} merged pairs: " + ", ".join(p["question_id"] for p in merges))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.make_questions")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing questions.json")
    parser.add_argument("--check", action="store_true", help="Validate the existing questions.json and exit")
    args = parser.parse_args()
    w = World()

    if args.check:
        pairs = json.loads(OUT.read_text())["pairs"]
        problems = check(w, pairs)
        print("\n".join(problems) or f"OK: {len(pairs)} pairs pass every check")
        raise SystemExit(1 if problems else 0)

    if OUT.exists() and not args.force:
        raise SystemExit(f"{OUT.relative_to(ROOT)} exists. Use --force to regenerate.")
    pairs, skipped = build(w)
    problems = check(w, pairs)
    if problems:
        raise SystemExit("Not written; checks failed:\n" + "\n".join(problems))
    OUT.write_text(json.dumps({
        "_about": "Test 2 pairs. Only question and as_of are sent to an agent. Generated by "
                  "python -m eval.make_questions. Approved 2026-11-26; frozen.",
        "skipped": skipped,
        "pairs": pairs,
    }, indent=2) + "\n")
    report(w, pairs, skipped)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
