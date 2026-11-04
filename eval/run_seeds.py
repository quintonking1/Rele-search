"""Run the five PRD seed questions against the baseline and show expected-record recall.

  python -m eval.run_seeds [--no-dates] [-k 8]

Eval code may import src/; src/ must never import eval/ (tests/test_isolation.py).
Only {question, as_of} is passed to the agent; expectations stay here.
"""

import argparse

from src.__main__ import print_run
from src.baseline import ask
from src.config import load_config

from .seeds import SEED_QUESTIONS


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.run_seeds")
    parser.add_argument("-k", type=int)
    parser.add_argument("--no-dates", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    include_dates = False if args.no_dates else None

    for seed in SEED_QUESTIONS:
        run = ask(cfg, seed["question"], seed["as_of"], args.k, include_dates, tag="seed")
        print_run(run)
        got = {r["id"] for r in run["retrieved"]}
        for label in ("outdated", "resolved_by", "still_true"):
            print(f"  {label:<12} " + ", ".join(f"{i}{'✓' if i in got else '✗'}" for i in seed[label]))


if __name__ == "__main__":
    main()
