"""Test 2 harness: ask an agent every (question, as_of) pair in a split and score the answers.

  python -m eval.harness --agent baseline --split dev
  python -m eval.harness --agent full --method hybrid --split dev
  python -m eval.harness --agent oracle --split dev        # no API calls; checks the harness itself
  python -m eval.harness --compare eval/runs/A.json eval/runs/B.json
  python -m eval.harness --agent full --method hybrid --split test --final   # once, after freezing

Approved 2026-11-26. Follows docs/eval_plan.md ("Harness flow"):
1. Load questions.json, split.json, and the labels.
2. Select the pairs whose group is in the requested split.
3. Send only {question, as_of} to the agent.
4. Validate the `cited` block; a malformed answer or an exception counts as a failed pair.
5. Score mechanically (eval/scoring.py).
6. Write a run file to eval/runs/ with settings, per-pair results, and summary metrics.

The full agent reads the latest run in data/status/<method>.jsonl; the run file records its tag.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import scoring

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions" / "questions.json"
SPLIT = ROOT / "eval" / "split.json"
CONFIG = ROOT / "eval" / "config.json"
RUNS = ROOT / "eval" / "runs"
TYPES = ("invalidator_before", "invalidator_after", "decoy", "partial", "still_true")


def load_pairs(split: str) -> list[dict]:
    groups = set(json.loads(SPLIT.read_text())["groups"][split])
    return [p for p in json.loads(QUESTIONS.read_text())["pairs"] if p["group"] in groups]


def make_agent(name: str, method: str | None, k: int | None, no_dates: bool, labels: dict, dates: dict):
    """Return (ask(question, as_of) -> (cited, retrieved_ids, run), settings dict)."""
    if name == "oracle":
        # Perfect agent built from the answer key. Only for checking the harness; never a result.
        def ask(question, as_of, group):
            rel = scoring.relevant_complaints(labels, dates, group, as_of)
            return [{"id": c, "status": s} for c, s in rel.items()], list(rel), None
        return ask, {"agent": "oracle"}

    from src import agent as full_agent
    from src.baseline import ask as baseline_ask
    from src.config import load_config

    cfg = load_config()
    include_dates = False if no_dates else None
    tag = f"test2-{name}" + (f"-{method}" if method else "")

    def ask(question, as_of, group):  # group is never passed to a real agent
        if name == "baseline":
            run = baseline_ask(cfg, question, as_of, k, include_dates, tag=tag)
        else:
            run = full_agent.ask(cfg, question, as_of, method, k, include_dates, tag=tag)
        return run["output"]["cited"], [r["id"] for r in run["retrieved"]], run

    settings = {"agent": name if name == "baseline" else f"full-{method}", "k": k or cfg.top_k,
                "include_dates": cfg.include_dates if include_dates is None else include_dates,
                "embedding_model": cfg.embedding_model, "generation_model": cfg.generation_model}
    return ask, settings


def run(args) -> Path:
    labels, dates = scoring.load_labels(), scoring.load_complaint_dates()
    pairs = load_pairs(args.split)
    if args.only:
        wanted = set(args.only.split(","))
        pairs = [p for p in pairs if p["question_id"] in wanted]
    if args.limit:
        pairs = pairs[: args.limit]
    ask, settings = make_agent(args.agent, args.method, args.k, args.no_dates, labels, dates)

    results, failed, status_log = [], [], None
    for p in pairs:
        try:
            cited, retrieved, agent_run = ask(p["question"], p["as_of"], p["group"])
        except Exception as e:  # noqa: BLE001 - one bad pair should not stop the run
            failed.append({"question_id": p["question_id"], "error": f"{type(e).__name__}: {e}"[:500]})
            print(f"  {p['question_id']} FAILED: {failed[-1]['error']}")
            continue
        problem = scoring.validate_cited(cited)
        if problem:
            failed.append({"question_id": p["question_id"], "error": f"malformed output: {problem}"})
            print(f"  {p['question_id']} FAILED: {problem}")
            continue
        if agent_run and "relevancy" in agent_run:
            status_log = {k: agent_run["relevancy"].get(k) for k in ("method", "tag", "created", "relevancy_model")}
        scored = scoring.score_pair(p, cited, retrieved, labels, dates)
        results.append({"question_id": p["question_id"], "group": p["group"], "type": p["type"],
                        "as_of": p["as_of"], "cited": cited, "retrieved": retrieved, **scored})
        c = scored["counts"]
        print(f"  {p['question_id']} {p['as_of']} {p['group']:<24} correct {c['correct']:>2}  "
              f"stale {c['stale answer']:>2}  lost {c['lost finding']:>2}  of {c['relevant']}")

    summary = {"all": scoring.summarize(results)}
    for t in TYPES:
        subset = [r for r in results if r["type"] == t]
        if subset:
            summary[t] = scoring.summarize(subset)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "timestamp": stamp,
        "split": args.split,
        "split_seed": json.loads(CONFIG.read_text()).get("split_seed"),
        "settings": settings,
        "status_log": status_log,
        "pairs_requested": len(pairs),
        "failed": failed,
        "summary": summary,
        "results": results,
    }
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{stamp}_{settings['agent']}_{args.split}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print_summary(out)
    print(f"\nWrote {path.relative_to(ROOT)}")
    return path


def fmt(x) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def print_summary(run_file: dict) -> None:
    s = run_file["settings"]
    print(f"\n{s['agent']} on {run_file['split']}: {run_file['summary']['all']['pairs']} pairs scored, "
          f"{len(run_file['failed'])} failed")
    print(f"{'':<20}{'pairs':>6}{'stale rate':>12}{'lost rate':>11}{'recall@k':>10}")
    for name, m in run_file["summary"].items():
        print(f"{name:<20}{m['pairs']:>6}{fmt(m['stale_answer_rate']):>12}{fmt(m['lost_finding_rate']):>11}"
              f"{fmt(m['retrieval_recall']):>10}")
    reasons = run_file["summary"]["all"]["lost_finding_reasons"]
    if reasons:
        print("lost findings by cause: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    off = run_file["summary"]["all"]["off_topic"]
    if off["cited"]:
        print(f"off-topic citations: {off['cited']} ({off['stale']} stale, {off['wrongly_outdated']} wrongly outdated)")


def compare(a_path: str, b_path: str) -> None:
    a, b = (json.loads(Path(p).read_text()) for p in (a_path, b_path))
    if a["split"] != b["split"]:
        print(f"WARNING: different splits ({a['split']} vs {b['split']})")
    na, nb = a["settings"]["agent"], b["settings"]["agent"]
    print(f"{'':<20}{'stale ' + na:>22}{'stale ' + nb:>22}{'lost ' + na:>22}{'lost ' + nb:>22}")
    for name in a["summary"]:
        if name not in b["summary"]:
            continue
        ma, mb = a["summary"][name], b["summary"][name]
        print(f"{name:<20}{fmt(ma['stale_answer_rate']):>22}{fmt(mb['stale_answer_rate']):>22}"
              f"{fmt(ma['lost_finding_rate']):>22}{fmt(mb['lost_finding_rate']):>22}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.harness")
    parser.add_argument("--agent", choices=("baseline", "full", "oracle"))
    parser.add_argument("--method", choices=("area", "similarity", "llm", "hybrid"), default="hybrid",
                        help="Relevancy method for --agent full (default: hybrid)")
    parser.add_argument("--split", choices=("train", "dev", "test"), default="dev")
    parser.add_argument("--final", action="store_true", help="Required for --split test (run once, after freezing)")
    parser.add_argument("-k", type=int)
    parser.add_argument("--no-dates", action="store_true")
    parser.add_argument("--limit", type=int, help="Only the first N pairs (for a quick try)")
    parser.add_argument("--only", help="Comma-separated question ids")
    parser.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"), help="Compare two run files")
    args = parser.parse_args()

    if args.compare:
        compare(*args.compare)
        return
    if not args.agent:
        parser.error("--agent is required unless --compare is given")
    if args.split == "test" and not args.final:
        parser.error("The test split runs once per agent, after freezing. Add --final if that is now.")
    if args.agent == "baseline":
        args.method = None
    run(args)


if __name__ == "__main__":
    main()
