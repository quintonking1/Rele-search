"""Single-JSON-file memory store (PRD Store 1). No status field (PRD Store 2)."""

import json
from pathlib import Path

import numpy as np


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.meta: dict = {}
        self.records: dict[str, dict] = {}
        if path.exists():
            data = json.loads(path.read_text())
            self.meta = data.get("meta", {})
            self.records = {r["id"]: r for r in data["records"]}

    def upsert(self, records: list[dict]) -> None:
        for r in records:
            self.records[r["id"]] = r  # keyed by id: re-ingest overwrites, never duplicates

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"meta": self.meta, "records": sorted(self.records.values(), key=lambda r: r["id"])}
        self.path.write_text(json.dumps(data))

    def search(self, query_vector: list[float], as_of: str | None, k: int) -> list[tuple[dict, float]]:
        """Cosine similarity over records dated <= as_of. No boosting by source, recency, or area."""
        candidates = [r for r in self.records.values() if as_of is None or r["date"] <= as_of]
        if not candidates:
            return []
        matrix = np.array([r["vector"] for r in candidates], dtype=np.float32)
        q = np.array(query_vector, dtype=np.float32)
        scores = matrix @ q / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q))
        order = np.argsort(-scores)[:k]
        return [(candidates[i], float(scores[i])) for i in order]
