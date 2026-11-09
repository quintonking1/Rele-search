"""Status log for the full agent: which complaints are outdated, by which release, since when.

One file per relevancy method, for example data/status/hybrid.json. The baseline store
(data/store.json) is never modified.

The log is append-only. Every complaint starts as current. A complaint is outdated as of a
date only if it has an event with `since` on or before that date, so the same log answers
"as of May" and "as of July" correctly.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

CURRENT = "current"
OUTDATED = "outdated"


class StatusLog:
    def __init__(self, path: Path):
        self.path = path
        self.meta: dict = {}
        self.events: list[dict] = []  # one per complaint marked outdated
        self.checks: list[dict] = []  # every (release, complaint) decision, for error analysis
        if path.exists():
            data = json.loads(path.read_text())
            self.meta = data.get("meta", {})
            self.events = data.get("events", [])
            self.checks = data.get("checks", [])

    def reset(self, meta: dict) -> None:
        """Start over, for example when re-running the relevancy check with new settings."""
        self.meta = {**meta, "created": datetime.now(timezone.utc).isoformat()}
        self.events = []
        self.checks = []

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

    def event_as_of(self, complaint_id: str, as_of: str | None) -> dict | None:
        """The earliest outdating event for this complaint dated on or before as_of, if any."""
        hits = [
            e
            for e in self.events
            if e["complaint_id"] == complaint_id and (as_of is None or e["since"] <= as_of)
        ]
        return min(hits, key=lambda e: e["since"]) if hits else None

    def status_as_of(self, complaint_id: str, as_of: str | None) -> dict:
        """{'status': 'current'} or {'status': 'outdated', 'outdated_by': ..., 'since': ...}."""
        event = self.event_as_of(complaint_id, as_of)
        if event is None:
            return {"status": CURRENT}
        return {"status": OUTDATED, "outdated_by": event["outdated_by"], "since": event["since"]}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"meta": self.meta, "events": self.events, "checks": self.checks}
        self.path.write_text(json.dumps(data, indent=1))
