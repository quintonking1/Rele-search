"""Relevancy check: does a release make an earlier complaint outdated?

Four methods, one per answer to the research question, behind one flag:

  area        same product_area and dated before the release -> outdated
  similarity  cosine similarity between release and complaint >= SIMILARITY_THRESHOLD -> outdated
  llm         the RELEVANCY_CANDIDATES most similar earlier complaints go to an LLM, which
              judges whether the release fixes each one
  hybrid      metadata gates first (platform and plan must overlap), then the llm step on
              the complaints that pass

Releases are processed in date order. Only complaints dated strictly before a release can be
outdated by it, and once a complaint is outdated it stays outdated (no later release reopens it).

A judge call that still fails after retries does not stop the run: its candidates are logged as
checks with stage "error" (treated as not fixed), the failure is listed in the run's meta, and a
line is appended to data/status/failed_calls.jsonl.
"""

import json
from datetime import datetime, timezone

import numpy as np

from .config import Config
from .llm import generate
from .status import StatusLog

METHODS = ("area", "similarity", "llm", "hybrid")

JUDGE_SYSTEM_PROMPT = """You check whether a product release fixes specific customer complaints for Tessera, an all-in-one workspace app.

For each complaint, decide whether this release FULLY fixes the specific problem that customer describes.
Be strict:
- A release in the same product area that leaves the customer's specific problem unsolved is NOT a fix.
- Check scope: platforms, plans, views, file types, limits, and anything the release says it does not cover or leaves for a future release.
- A feature request counts as fixed only if the release delivers what the customer asked for.
- If the release only partly addresses the complaint, answer false.
Quote the sentence from the release that supports a true answer. Use an empty string for evidence when the answer is false."""

# OpenAI strict structured output needs an object at the top level, so the verdicts sit under "results".
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "fixes": {"type": "boolean"},
                    "evidence": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "fixes", "evidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


# ---------- helpers ----------


def cosine_matrix(a: list[list[float]], b: list[list[float]]) -> np.ndarray:
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return a @ b.T


def passes_gates(release: dict, complaint: dict) -> tuple[bool, str]:
    """Metadata gates for the hybrid method. Returns (passes, reason if it fails)."""
    if not set(complaint["platforms"]) & set(release["platforms"]):
        return False, f"platform gate: complaint on {complaint['platforms']}, release ships on {release['platforms']}"
    if not set(complaint["plan"]) & set(release["plan"]):
        return False, f"plan gate: complaint plan {complaint['plan']}, release available on {release['plan']}"
    return True, ""


def format_release(release: dict) -> str:
    return (
        f"id: {release['id']}\ndate: {release['date']}\nproduct_area: {release['product_area']}\n"
        f"platforms: {', '.join(release['platforms'])}\nplans: {', '.join(release['plan'])}\n"
        f"title: {release['title']}\ntext: {release['text']}"
    )


def format_complaint(complaint: dict) -> str:
    return (
        f"id: {complaint['id']}\ndate: {complaint['date']}\nproduct_area: {complaint['product_area']}\n"
        f"platforms: {', '.join(complaint['platforms'])}\nplan: {', '.join(complaint['plan'])}\n"
        f"title: {complaint['title']}\ntext: {complaint['text']}"
    )


def build_judge_prompt(release: dict, candidates: list[dict]) -> str:
    complaints = "\n\n---\n\n".join(format_complaint(c) for c in candidates)
    return (
        f"RELEASE\n\n{format_release(release)}\n\n=====\n\nCOMPLAINTS\n\n{complaints}\n\n=====\n\n"
        f"Return one result per complaint, using its id."
    )


def judge(cfg: Config, client, release: dict, candidates: list[dict]) -> dict[str, dict]:
    """One LLM call per release. Returns {complaint_id: {fixes, evidence, reason}}."""
    if not candidates:
        return {}
    text = generate(
        client, cfg.relevancy_model, JUDGE_SYSTEM_PROMPT, build_judge_prompt(release, candidates),
        temperature=0.0, json_schema=JUDGE_SCHEMA, schema_name="judge_verdicts",
    )
    results = json.loads(text or "{}").get("results", [])
    wanted = {c["id"] for c in candidates}
    verdicts = {r["id"]: r for r in results if r.get("id") in wanted}
    # A candidate the model skipped is treated as "not fixed" and flagged in the log.
    for cid in wanted - verdicts.keys():
        verdicts[cid] = {"id": cid, "fixes": False, "evidence": "", "reason": "MISSING: model returned no verdict"}
    return verdicts


# ---------- the update loop ----------


def log_failure(cfg: Config, entry: dict) -> None:
    path = cfg.status_dir / "failed_calls.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def run_relevancy(cfg: Config, records: list[dict], method: str, client=None, tag: str | None = None) -> StatusLog:
    """Process every release in date order and append a tagged run to data/status/<method>.jsonl.

    `records` are store records (with vectors). `client` is only needed for llm and hybrid.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if method in ("llm", "hybrid") and client is None:
        raise ValueError(f"method {method} needs an OpenAI client")

    complaints = [r for r in records if r["source_type"] == "complaint"]
    releases = sorted(
        (r for r in records if r["source_type"] == "changelog"), key=lambda r: (r["date"], r["id"])
    )
    sims = cosine_matrix([r["vector"] for r in releases], [c["vector"] for c in complaints])

    log = StatusLog(cfg.status_dir / f"{method}.json")
    log.start_run(
        {
            "method": method,
            "similarity_threshold": cfg.similarity_threshold if method == "similarity" else None,
            "candidates_per_release": cfg.relevancy_candidates if method in ("llm", "hybrid") else None,
            "relevancy_model": cfg.relevancy_model if method in ("llm", "hybrid") else None,
            "embedding_model": cfg.embedding_model,
            "complaints_checked": len(complaints),
        },
        tag,
    )
    outdated: set[str] = set()
    # Counts of (release, complaint) pairs, for the hybrid gate-vs-model breakdown.
    counts = {"gated_all": 0, "gated_in_top": 0, "sent_to_llm": 0, "llm_calls": 0, "failed_calls": 0}
    failures: list[dict] = []

    for i, release in enumerate(releases):
        # Earlier complaints that are still current when this release ships.
        open_idx = [
            j for j, c in enumerate(complaints) if c["date"] < release["date"] and c["id"] not in outdated
        ]
        decisions: list[dict] = []  # {id, fixes, score, reason, evidence}

        if method == "area":
            for j in open_idx:
                c = complaints[j]
                if c["product_area"] == release["product_area"]:
                    decisions.append(
                        {"id": c["id"], "fixes": True, "score": float(sims[i, j]), "reason": "same product area", "evidence": ""}
                    )

        elif method == "similarity":
            for j in open_idx:
                score = float(sims[i, j])
                if score >= cfg.similarity_threshold:
                    decisions.append(
                        {"id": complaints[j]["id"], "fixes": True, "score": score,
                         "reason": f"similarity {score:.3f} >= {cfg.similarity_threshold}", "evidence": ""}
                    )

        else:  # llm or hybrid
            pool = open_idx
            if method == "hybrid":
                # Complaints the llm method would have judged; gate rejections among them are logged
                # so you can see which near misses the gates caught before any model call.
                would_judge = set(sorted(open_idx, key=lambda j: -sims[i, j])[: cfg.relevancy_candidates])
                pool = []
                for j in open_idx:
                    ok, why = passes_gates(release, complaints[j])
                    if ok:
                        pool.append(j)
                        continue
                    counts["gated_all"] += 1
                    if j in would_judge:
                        counts["gated_in_top"] += 1
                        decisions.append(
                            {"id": complaints[j]["id"], "fixes": False, "score": float(sims[i, j]),
                             "reason": why, "evidence": "", "stage": "gate"}
                        )
            top = sorted(pool, key=lambda j: -sims[i, j])[: cfg.relevancy_candidates]
            candidates = [complaints[j] for j in top]
            try:
                verdicts = judge(cfg, client, release, candidates)
                stage, error = "llm", ""
            except Exception as e:  # noqa: BLE001 - any failure is logged and the run continues
                error = f"{type(e).__name__}: {e}"[:500]
                verdicts = {c["id"]: {"fixes": False, "reason": f"ERROR: {error}"} for c in candidates}
                stage = "error"
                entry = {"time": datetime.now(timezone.utc).isoformat(), "tag": log.meta["tag"], "method": method,
                         "release": release["id"], "complaints": [c["id"] for c in candidates], "error": error}
                failures.append(entry)
                log_failure(cfg, entry)
                counts["failed_calls"] += 1
                print(f"  FAILED {release['id']}: {error}")
            if candidates:
                counts["llm_calls"] += 1
                counts["sent_to_llm"] += len(candidates)
            for j in top:
                v = verdicts[complaints[j]["id"]]
                decisions.append(
                    {"id": complaints[j]["id"], "fixes": bool(v["fixes"]), "score": float(sims[i, j]),
                     "reason": v.get("reason", ""), "evidence": v.get("evidence", ""), "stage": stage}
                )

        for d in decisions:
            log.add_check({"release": release["id"], "release_date": release["date"], "complaint": d["id"], **d})
            if d["fixes"]:
                log.mark_outdated(d["id"], release["id"], release["date"], d["reason"], d["evidence"])
                outdated.add(d["id"])

        n_fixed = sum(d["fixes"] for d in decisions)
        print(f"  {release['date']} {release['id']}: {n_fixed} outdated", flush=True)  # flush: progress shows even when output goes to a file

    if method in ("llm", "hybrid"):
        log.meta["counts"] = counts
        log.meta["failures"] = failures
    log.save()
    print(f"{method} [{log.meta['tag']}]: {len(log.events)} complaints marked outdated -> {log.path}")
    if failures:
        print(f"  {len(failures)} judge call(s) failed after retries; see {cfg.status_dir / 'failed_calls.jsonl'}")
    return log
