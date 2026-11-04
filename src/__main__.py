"""Baseline agent CLI.

  python -m src ingest
  python -m src ask "What do we know about checkout?" --as-of 2026-07-15 [--no-dates] [-k 8]

Agent code only. Seed questions and anything with expected answers live outside src/.
"""

import argparse

from .baseline import ask, ingest
from .config import load_config


def print_run(run: dict) -> None:
    print(f"\nQ: {run['question']}  (as_of={run['as_of']}, k={run['k']}, dates={run['include_dates']})")
    print("Retrieved: " + ", ".join(f"{r['id']}({r['score']:.3f})" for r in run["retrieved"]))
    print(f"\n{run['output']['answer']}\n")
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

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "ingest":
        ingest(cfg)
    elif args.cmd == "ask":
        include_dates = False if args.no_dates else None
        print_run(ask(cfg, args.question, args.as_of, args.k, include_dates))


if __name__ == "__main__":
    main()
