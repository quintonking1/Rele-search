"""Score each relevancy method's status log against the complaint labels.

  python -m eval.score_relevancy                     # every method with a status log
  python -m eval.score_relevancy --method hybrid --show-errors
  python -m eval.score_relevancy --tag nearmiss-2026-11-15   # score the run with this tag in each method's log

Status logs are append-only and hold several tagged runs; the latest run is scored unless --tag
is given. Scores are reported for all complaints, the original set (C001 to C100), and the near
misses (C101 to C115) separately. Every near miss is labeled never fixed, so on that subset
recall has no positives to find and precision is 0 whenever anything is flagged; the number to
read there is false flags out of 15.

This checks the relevancy check directly, before any question is asked: did each method mark
the right complaints outdated, by the right release? It complements the question-level eval
(stale answers, lost findings), which also depends on retrieval.

Counting, per complaint (labels' first fix vs the method's first outdated and first partial event):
  correct          labeled fixed, method outdated it by the same release
  wrong release    labeled fixed, method outdated it by a different release
  missed           labeled fixed, method never outdated it (left it current or only called it partial)
                                                              -> would cause stale answers
  false flag       labeled never fixed, method outdated it    -> would cause lost findings
  false partial    labeled never fixed, method called it partial -> would cause lost findings
  partial right    labeled partial, method called it partial by the same release
  partial wrong    labeled partial, anything else (v1 methods have no partial status)
  correctly current  labeled never fixed, method left it current

Precision and recall cover full fixes only, as in the v1 reports: precision = correct / all
outdated flags on complaints not labeled partial; recall = correct / all labeled fixed. False
partials and partial rows are reported in their own columns.

eval/split.json (python -m eval.make_split) assigns groups to train (40%), dev (20%), and test
(40%). Tune thresholds and prompts on dev only (--split dev); score test once per agent after freezing.
"""

import argparse
import json
from pathlib import Path

from src.status import StatusLog

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels" / "complaint_labels.json"
SPLIT = ROOT / "eval" / "split.json"
STATUS_DIR = ROOT / "data" / "status"

# Subsets reported separately. C101 to C115 are near misses added 2026-11-09.
SUBSETS = {
    "original": lambda cid: int(cid[1:]) <= 100,
    "near-miss": lambda cid: 101 <= int(cid[1:]) <= 115,
}


def load_labels() -> dict[str, dict]:
    return {c["complaint_id"]: c for c in json.loads(LABELS.read_text())}


def first_fix(label: dict) -> dict | None:
    return min(label["history"], key=lambda h: h["date"]) if label["history"] else None


def ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 2 * p * r / (p + r) if p + r else 0.0


def load_run(method: str, tag: str | None) -> dict:
    log = StatusLog(STATUS_DIR / f"{method}.json", tag)
    if not log.runs:
        raise SystemExit(f"No status log for {method}. Run: python -m src update --method {method}")
    return {"meta": log.meta, "events": log.events, "checks": log.checks}


def score(method: str, labels: dict[str, dict], groups: set[str] | None, data: dict,
          keep=lambda cid: True) -> dict:
    predicted, partials = {}, {}  # first outdated event and first partial event per complaint
    for e in sorted(data["events"], key=lambda e: e["since"]):
        if e.get("status", "outdated") == "partial":
            partials.setdefault(e["complaint_id"], e)
        else:
            predicted.setdefault(e["complaint_id"], e)

    rows = {k: [] for k in COLUMNS}
    for cid, label in sorted(labels.items()):
        if (groups is not None and label["group"] not in groups) or not keep(cid):
            continue
        fix = first_fix(label)
        pred = predicted.get(cid)
        part = partials.get(cid)
        if fix and fix["resolution"] == "partial":
            ok = part is not None and part["partial_by"] == fix["item"] and (pred is None or pred["since"] > fix["date"])
            got = pred["outdated_by"] if pred else (part["partial_by"] if part else None)
            rows["partial right" if ok else "partial wrong"].append((cid, fix["item"], got))
        elif fix and pred:
            key = "correct" if pred["outdated_by"] == fix["item"] else "wrong release"
            rows[key].append((cid, fix["item"], pred["outdated_by"]))
        elif fix:
            rows["missed"].append((cid, fix["item"], part["partial_by"] if part else None))
        elif pred:
            rows["false flag"].append((cid, None, pred["outdated_by"]))
        elif part:
            rows["false partial"].append((cid, None, part["partial_by"]))
        else:
            rows["correctly current"].append((cid, None, None))

    n_flagged = len(rows["correct"]) + len(rows["wrong release"]) + len(rows["false flag"])
    n_fixed = len(rows["correct"]) + len(rows["wrong release"]) + len(rows["missed"])
    precision = ratio(len(rows["correct"]), n_flagged)
    recall = ratio(len(rows["correct"]), n_fixed)
    return {"method": method, "meta": data["meta"], "rows": rows, "precision": precision, "recall": recall,
            "f1": f1(precision, recall), "checks": data.get("checks", [])}


COLUMNS = ["correct", "wrong release", "missed", "false flag", "false partial", "partial right", "partial wrong",
           "correctly current"]


def fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def print_table(title: str, results: list[dict]) -> None:
    cols = COLUMNS
    print(f"\n{title}")
    print(f"{'method':<11}" + "".join(f"{c:>18}" for c in cols) + f"{'precision':>11}{'recall':>8}{'F1':>6}")
    for r in results:
        print(f"{r['method']:<11}" + "".join(f"{len(r['rows'][c]):>18}" for c in cols)
              + f"{fmt(r['precision']):>11}{fmt(r['recall']):>8}{fmt(r['f1']):>6}")


def gate_breakdown(data: dict) -> None:
    """Hybrid only: (release, complaint) pairs decided by the metadata gates vs judged by the model."""
    checks = data["checks"]
    counts = data["meta"].get("counts", {})
    print("\nhybrid: who decided each (release, complaint) pair")
    if counts:
        print(f"  all gated pairs (any rank): {counts['gated_all']}   gated among the top "
              f"{data['meta'].get('candidates_per_release')} by similarity: {counts['gated_in_top']}   "
              f"sent to the LLM: {counts['sent_to_llm']} in {counts['llm_calls']} calls   "
              f"failed calls: {counts['failed_calls']}")
    for name, keep in SUBSETS.items():
        sub = [c for c in checks if keep(c["complaint"])]
        n = {s: sum(c.get("stage") == s for c in sub) for s in ("gate", "llm", "error")}
        flagged = sum(c["fixes"] for c in sub)
        part = sum(c.get("verdict") == "partial" for c in sub)
        print(f"  {name:<9} logged pairs: gate {n['gate']}, llm {n['llm']}, error {n['error']}  "
              f"(llm said fixes: {flagged}, partial: {part})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.score_relevancy")
    parser.add_argument("--method", action="append", help="Method(s) to score; default: all with a status log")
    parser.add_argument("--split", choices=("train", "dev", "test"), help="Only score groups in this split (needs eval/split.json)")
    parser.add_argument("--show-errors", action="store_true", help="List every error with the method's reason")
    parser.add_argument("--tag", help="Score the run with this tag (default: latest run per method)")
    args = parser.parse_args()

    labels = load_labels()
    groups = None
    if args.split:
        if not SPLIT.exists():
            raise SystemExit("eval/split.json does not exist yet.")
        groups = set(json.loads(SPLIT.read_text())["groups"][args.split])

    methods = args.method or sorted({p.stem for p in STATUS_DIR.glob("*.json*")} - {"failed_calls"})
    if not methods:
        raise SystemExit("No status logs in data/status/. Run: python -m src update --method <method>")

    runs = {m: load_run(m, args.tag) for m in methods}
    results = [score(m, labels, groups, runs[m]) for m in methods]
    for r in results:
        checked = r["meta"].get("complaints_checked")
        if checked != len(labels):
            print(f"WARNING {r['method']}: status log covers {checked or 'an older set of'} complaints, labels cover "
                  f"{len(labels)}. Re-run `python -m src ingest` then `python -m src update --method {r['method']}`.")
    for r in results:
        print(f"{r['method']:<11} run tag: {r['meta'].get('tag')}  created: {r['meta'].get('created')}")

    print_table("ALL COMPLAINTS", results)
    for name, keep in SUBSETS.items():
        print_table(f"{name.upper()} ONLY", [score(m, labels, groups, runs[m], keep) for m in methods])
    print("\nprecision = correct / all outdated flags; recall = correct / all labeled fixed (partials excluded); "
          "n/a = no denominator. Judge: " + ", ".join(f"{r['method']} {r['meta'].get('judge') or 'v1' if r['method'] in ('llm', 'hybrid') else '-'}" for r in results))
    if "hybrid" in runs:
        gate_breakdown(runs["hybrid"])

    if args.show_errors:
        for r in results:
            checks = {(c["release"], c["complaint"]): c for c in r["checks"]}
            print(f"\n== {r['method']} ==")
            for kind in ("wrong release", "missed", "false flag", "false partial", "partial right", "partial wrong"):
                for cid, truth, pred in r["rows"][kind]:
                    c = checks.get((pred, cid), {}) if pred else {}
                    verdict = f"[{c['verdict']}] " if c.get("verdict") else ""
                    print(f"  {kind:<14} {cid}  label={truth}  method={pred}  {verdict}{c.get('reason', '')}")
                    for q in c.get("requirements", []):  # v2 checklist, so the verdict can be audited
                        print(f"      - {q['met']:<8} {q['need']}")


if __name__ == "__main__":
    main()
