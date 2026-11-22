"""Split complaint groups into train, dev, and test with a fixed seed.

  python -m eval.make_split            # writes eval/split.json (refuses to overwrite)
  python -m eval.make_split --force    # regenerate; record why in eval/config.json's "split_note"

Groups are split whole, so complaints that share a storyline stay on the same side. Targets are
40% test (held out; run once per agent after freezing), 20% dev (tune thresholds and prompts),
and 40% train. questions.json does not exist yet, so groups are weighted by complaint count;
re-check the balance once questions are written.

Assignment: shuffle groups with the seed, order them largest first (the shuffle breaks ties
between equal sizes), then give each group to the split furthest below its target share. This
lands close to the targets even though group sizes vary (1 to 16).
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels" / "complaint_labels.json"
CONFIG = ROOT / "eval" / "config.json"
SPLIT = ROOT / "eval" / "split.json"
TARGETS = {"test": 0.40, "dev": 0.20, "train": 0.40}


def label_kind(label: dict) -> str:
    """fixed / partial / never, from the label's fix history."""
    resolutions = {h["resolution"] for h in label["history"]}
    if "full" in resolutions:
        return "fixed"
    return "partial" if resolutions else "never"


def make_split(labels: list[dict], seed: int) -> dict:
    sizes = Counter(l["group"] for l in labels)
    groups = sorted(sizes)  # sort first so the shuffle depends only on the seed
    random.Random(seed).shuffle(groups)
    # Largest groups first (the seed's shuffle breaks ties), so small groups fill the gaps at the end.
    groups.sort(key=lambda g: -sizes[g])

    assigned = {s: [] for s in TARGETS}
    counts = {s: 0 for s in TARGETS}
    for g in groups:
        total = sum(counts.values()) + sizes[g]
        # Deficit = how far each split would be below its target after adding this group elsewhere.
        split = max(TARGETS, key=lambda s: TARGETS[s] * total - counts[s])
        assigned[split].append(g)
        counts[split] += sizes[g]

    n = len(labels)
    summary = {}
    for s, gs in assigned.items():
        members = [l for l in labels if l["group"] in gs]
        summary[s] = {
            "groups": len(gs),
            "complaints": len(members),
            "share": round(len(members) / n, 3),
            "by_label": dict(Counter(label_kind(l) for l in members)),
            "near_misses": sum(int(l["complaint_id"][1:]) >= 101 for l in members),
        }
    return {"seed": seed, "targets": TARGETS, "weighted_by": "complaint count",
            "groups": {s: sorted(gs) for s, gs in assigned.items()}, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.make_split")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing eval/split.json")
    args = parser.parse_args()
    if SPLIT.exists() and not args.force:
        raise SystemExit("eval/split.json already exists. The split is frozen; use --force with a note in eval/config.json.")

    seed = json.loads(CONFIG.read_text())["split_seed"]
    split = make_split(json.loads(LABELS.read_text()), seed)
    SPLIT.write_text(json.dumps(split, indent=2) + "\n")
    for s, info in split["summary"].items():
        print(f"{s:<5} {info['complaints']:>3} complaints ({info['share']:.0%}), {info['groups']} groups, "
              f"labels {info['by_label']}, near misses {info['near_misses']}")
        print(f"      {', '.join(split['groups'][s])}")
    print(f"Wrote {SPLIT}")


if __name__ == "__main__":
    main()
