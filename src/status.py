"""Status log for the full agent: which complaints are outdated, by which release, since when.

One log per relevancy method. The baseline store (data/store.json) is never modified.

The log is append-only at two levels:
- Within a run, every complaint starts as current and only gains outdating events. A complaint is
  outdated as of a date only if it has an event with `since` on or before that date, so the same
  run answers "as of May" and "as of July" correctly.
- Across runs, each run of the relevancy check is appended as one tagged JSON line to
  data/status/<method>.jsonl. Earlier runs are never rewritten. A legacy data/status/<method>.json
  (the format before run tags) is read as the first run, tagged "legacy", and never modified.

Readers use the latest run unless they ask for a tag.

Statuses: current, partial, outdated. A partial event (judge v2) means a release partly fixed the
complaint; a later release can still fix it fully. On any date, the latest event on or before that
date decides the status. Events written before partial existed have no "status" key and are
outdated events.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

CURRENT = "current"
PARTIAL = "partial"
OUTDATED = "outdated"
LEGACY_TAG = "legacy"


class StatusLog:
    def __init__(self, path: Path, tag: str | None = None):
        """`path` is data/status/<method>.json; runs are appended to the sibling .jsonl file."""
        self.legacy_path = path.with_suffix(".json")
        self.path = path.with_suffix(".jsonl")
        self.runs: list[dict] = []  # every saved run, oldest first: {meta, events, checks}
        if self.legacy_path.exists():
            data = json.loads(self.legacy_path.read_text())
            self.runs.append({**data, "meta": {**data.get("meta", {}), "tag": LEGACY_TAG}})
        if self.path.exists():
            self.runs += [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

        self._new = False  # True once start_run is called; only a new run can be saved
        self.meta: dict = {}
        self.events: list[dict] = []  # one per status change: a complaint marked partial or outdated
        self.checks: list[dict] = []  # every (release, complaint) decision, for error analysis
        if self.runs:
            run = self.run(tag) if tag else self.runs[-1]
            self.meta, self.events, self.checks = run["meta"], run.get("events", []), run.get("checks", [])
        elif tag:
            raise KeyError(f"No run tagged {tag!r} in {self.path}")

    def tags(self) -> list[str]:
        return [r["meta"].get("tag") for r in self.runs]

    def run(self, tag: str) -> dict:
        hits = [r for r in self.runs if r["meta"].get("tag") == tag]
        if not hits:
            raise KeyError(f"No run tagged {tag!r} in {self.path}. Tags: {self.tags()}")
        return hits[-1]

    def start_run(self, meta: dict, tag: str | None = None) -> None:
        """Begin a new run in memory. Earlier runs stay on disk untouched."""
        created = datetime.now(timezone.utc)
        tag = tag or f"{meta.get('method', 'run')}-{created.strftime('%Y%m%dT%H%M%S%f')}"
        if tag in self.tags():
            raise ValueError(f"Tag {tag!r} already exists in {self.path}; pick a new one")
        self.meta = {**meta, "tag": tag, "created": created.isoformat()}
        self.events = []
        self.checks = []
        self._new = True

    def reset(self, meta: dict) -> None:
        """Kept for callers that predate run tags: starts a new run with an automatic tag."""
        self.start_run(meta)

    def add_check(self, check: dict) -> None:
        self.checks.append(check)

    def mark_outdated(self, complaint_id: str, item_id: str, since: str, reason: str = "", evidence: str = "") -> None:
        self.events.append(
            {
                "complaint_id": complaint_id,
                "status": OUTDATED,
                "outdated_by": item_id,
                "since": since,
                "reason": reason,
                "evidence": evidence,
            }
        )

    def mark_partial(self, complaint_id: str, item_id: str, since: str, reason: str = "", evidence: str = "") -> None:
        self.events.append(
            {
                "complaint_id": complaint_id,
                "status": PARTIAL,
                "partial_by": item_id,
                "since": since,
                "reason": reason,
                "evidence": evidence,
            }
        )

    def event_as_of(self, complaint_id: str, as_of: str | None) -> dict | None:
        """The latest status event for this complaint dated on or before as_of, if any.

        An outdated event wins over a partial one on the same day.
        """
        hits = [
            e
            for e in self.events
            if e["complaint_id"] == complaint_id and (as_of is None or e["since"] <= as_of)
        ]
        rank = {PARTIAL: 0, OUTDATED: 1}
        return max(hits, key=lambda e: (e["since"], rank[e.get("status", OUTDATED)])) if hits else None

    def status_as_of(self, complaint_id: str, as_of: str | None) -> dict:
        """{'status': 'current'}, {'status': 'partial', 'partial_by', 'since'}, or {'status': 'outdated', 'outdated_by', 'since'}."""
        event = self.event_as_of(complaint_id, as_of)
        if event is None:
            return {"status": CURRENT}
        if event.get("status", OUTDATED) == PARTIAL:
            return {"status": PARTIAL, "partial_by": event["partial_by"], "since": event["since"]}
        return {"status": OUTDATED, "outdated_by": event["outdated_by"], "since": event["since"]}

    def save(self) -> None:
        """Append the new run as one line. Never rewrites what is already on disk."""
        if not self._new:
            raise RuntimeError("Nothing to save: call start_run first (saved runs are never rewritten)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        run = {"meta": self.meta, "events": self.events, "checks": self.checks}
        with self.path.open("a") as f:
            f.write(json.dumps(run) + "\n")
        self.runs.append(run)
        self._new = False
