"""Agent CLI.

Baseline:
  python -m src ingest
  python -m src ask "What do we know about checkout?" --as-of 2026-07-15 [--no-dates] [-k 8]

Full agent:
  python -m src update --method hybrid          # run the relevancy check, write data/status/hybrid.json
  python -m src ask-full "What do we know about checkout?" --as-of 2026-07-15 --method hybrid

Agent code only. Seed questions and anything with expected answers live outside src/.
"""

import argparse

from . import agent
from .baseline import ask, ingest, make_client
from .config import load_config
from .relevancy import METHODS, run_relevancy
from .store import Store


def print_run(run: dict) -> None:
    print(f"\nQ: {run['question']}  (as_of={run['as_of']}, k={run['k']}, dates={run['include_dates']})")
    print("Retrieved: " + ", ".join(f"{r['id']}({r['score']:.3f})" for r in run["retrieved"]))
    print(f"\n{run['output']['answer']}\n")
    statuses = [f"{c['id']}={c['status']}" + (f"({c['outdated_by']})" if "outdated_by" in c else "")
                for c in run["output"]["cited"] if "status" in c]
    if statuses:
        print("Cited status: " + ", ".join(statuses))
    if run["cited_not_retrieved"]:
        print(f"WARNING cited but not retrieved: {run['cited_not_retrieved']}")
    print(f"Logged to {run['log_path']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="Embed both datasets into the JSON store")

    p_ask = sub.add_parser("ask", help="Ask one question")
    p_ask.add_argument("question")
    p_ask.add_argument("--as-of", help="YYYY-MM-DD; only records dated on or before this are used")
    p_ask.add_argument("-k", type=int, help="Top k (default TOP_K from .env)")
    p_ask.add_argument("--no-dates", action="store_true", help="Hide record dates from the LLM")

    p_up = sub.add_parser("update", help="Full agent: run the relevancy check over all releases")
    p_up.add_argument("--method", choices=METHODS, required=True)

    p_full = sub.add_parser("ask-full", help="Full agent: ask one question using a method's status log")
    p_full.add_argument("question")
    p_full.add_argument("--as-of", help="YYYY-MM-DD; only records dated on or before this are used")
    p_full.add_argument("--method", choices=METHODS, default="hybrid")
    p_full.add_argument("-k", type=int, help="Top k (default TOP_K from .env)")
    p_full.add_argument("--no-dates", action="store_true", help="Hide record dates from the LLM")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "ingest":
        ingest(cfg)
    elif args.cmd == "ask":
        include_dates = False if args.no_dates else None
        print_run(ask(cfg, args.question, args.as_of, args.k, include_dates))
    elif args.cmd == "update":
        store = Store(cfg.store_path)
        if not store.records:
            raise SystemExit(f"Store {cfg.store_path} is empty. Run ingest first.")
        client = make_client(cfg) if args.method in ("llm", "hybrid") else None
        run_relevancy(cfg, list(store.records.values()), args.method, client)
    elif args.cmd == "ask-full":
        include_dates = False if args.no_dates else None
        print_run(agent.ask(cfg, args.question, args.as_of, args.method, args.k, include_dates))


if __name__ == "__main__":
    main()
