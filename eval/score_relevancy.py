"""Score each relevancy method's status log against the complaint labels.

  python -m eval.score_relevancy                     # every method with a status log
  python -m eval.score_relevancy --method hybrid --show-errors

This checks the relevancy check directly, before any question is asked: did each method mark
the right complaints outdated, by the right release? It complements the question-level eval
(stale answers, lost findings), which also depends on retrieval.

Counting, per complaint (labels' first fix vs the method's outdating event):
  correct          labeled fixed, method outdated it by the same release
  wrong release    labeled fixed, method outdated it by a different release
  missed           labeled fixed, method left it current      -> would cause stale answers
  false flag       labeled never fixed, method outdated it    -> would cause lost findings
  partial          labeled partial (reported separately; the agent has no partial status yet)

The split does not exist yet. Once eval/split.json is committed, tune thresholds and prompts on
dev groups only (--split dev).
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels" / "complaint_labels.json"
SPLIT = ROOT / "eval" / "split.json"
STATUS_DIR = ROOT / "data" / "status"


def load_labels() -> dict[str, dict]:
    return {c["complaint_id"]: c for c in json.loads(LABELS.read_text())}


def first_fix(label: dict) -> dict | None:
    return min(label["history"], key=lambda h: h["date"]) if label["history"] else None


def score(method: str, labels: dict[str, dict], groups: set[str] | None) -> dict:
    data = json.loads((STATUS_DIR / f"{method}.json").read_text())
    predicted = {}
    for e in sorted(data["events"], key=lambda e: e["since"]):
        predicted.setdefault(e["complaint_id"], e)

    rows = {"correct": [], "wrong release": [], "missed": [], "false flag": [], "partial": [], "correctly current": []}
    for cid, label in sorted(labels.items()):
        if groups is not None and label["group"] not in groups:
            continue
        fix = first_fix(label)
        pred = predicted.get(cid)
        if fix and fix["resolution"] == "partial":
            rows["partial"].append((cid, fix["item"], pred["outdated_by"] if pred else None))
        elif fix and pred:
            key = "correct" if pred["outdated_by"] == fix["item"] else "wrong release"
            rows[key].append((cid, fix["item"], pred["outdated_by"]))
        elif fix:
            rows["missed"].append((cid, fix["item"], None))
        elif pred:
            rows["false flag"].append((cid, None, pred["outdated_by"]))
        else:
            rows["correctly current"].append((cid, None, None))

    n_flagged = len(rows["correct"]) + len(rows["wrong release"]) + len(rows["false flag"])
    n_fixed = len(rows["correct"]) + len(rows["wrong release"]) + len(rows["missed"])
    precision = len(rows["correct"]) / n_flagged if n_flagged else 0.0
    recall = len(rows["correct"]) / n_fixed if n_fixed else 0.0
    return {"method": method, "meta": data["meta"], "rows": rows, "precision": precision, "recall": recall,
            "checks": data.get("checks", [])}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.score_relevancy")
    parser.add_argument("--method", action="append", help="Method(s) to score; default: all with a status log")
    parser.add_argument("--split", choices=("dev", "test"), help="Only score groups in this split (needs eval/split.json)")
    parser.add_argument("--show-errors", action="store_true", help="List every error with the method's reason")
    args = parser.parse_args()

    labels = load_labels()
    groups = None
    if args.split:
        if not SPLIT.exists():
            raise SystemExit("eval/split.json does not exist yet.")
        groups = set(json.loads(SPLIT.read_text())["groups"][args.split])

    methods = args.method or sorted(p.stem for p in STATUS_DIR.glob("*.json"))
    if not methods:
        raise SystemExit("No status logs in data/status/. Run: python -m src update --method <method>")

    results = [score(m, labels, groups) for m in methods]
    for r in results:
        checked = r["meta"].get("complaints_checked")
        if checked != len(labels):
            print(f"WARNING {r['method']}: status log covers {checked or 'an older set of'} complaints, labels cover "
                  f"{len(labels)}. Re-run `python -m src ingest` then `python -m src update --method {r['method']}`.")
    cols = ["correct", "wrong release", "missed", "false flag", "partial", "correctly current"]
    print(f"{'method':<11}" + "".join(f"{c:>18}" for c in cols) + f"{'precision':>11}{'recall':>8}")
    for r in results:
        print(f"{r['method']:<11}" + "".join(f"{len(r['rows'][c]):>18}" for c in cols)
              + f"{r['precision']:>11.2f}{r['recall']:>8.2f}")
    print("\nprecision = correct / all flagged; recall = correct / all labeled fixed (partials excluded)")

    if args.show_errors:
        for r in results:
            reasons = {(c["release"], c["complaint"]): c["reason"] for c in r["checks"]}
            print(f"\n== {r['method']} ==")
            for kind in ("wrong release", "missed", "false flag", "partial"):
                for cid, truth, pred in r["rows"][kind]:
                    why = reasons.get((pred, cid), "") if pred else ""
                    print(f"  {kind:<14} {cid}  label={truth}  method={pred}  {why}")


if __name__ == "__main__":
    main()
