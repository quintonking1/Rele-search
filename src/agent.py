"""Full agent: the baseline pipeline plus status from the relevancy check.

Retrieval, ranking, model, temperature, and log format are the same as the baseline, so any
difference in the eval comes from the status. The changes:

1. Each retrieved complaint's status as of `as_of` is read from data/status/<method>.json
   and shown to the model next to the record.
2. The system prompt adds instructions for outdated complaints.
3. The `cited` block's statuses are filled in by code from the status log; the model never
   writes them. The eval then measures the relevancy check rather than how well the model
   copies a label.
"""

import re
from datetime import date, datetime, timezone

from google.genai import types

from .baseline import SYSTEM_PROMPT as BASELINE_SYSTEM_PROMPT
from .baseline import _log, make_client
from .config import Config
from .embed import Embedder
from .retry import with_retry
from .status import OUTDATED, StatusLog
from .store import Store

SYSTEM_PROMPT = (
    BASELINE_SYSTEM_PROMPT
    + """

Each complaint has a status. A CURRENT complaint describes a problem that still exists; present it as ongoing.
An OUTDATED complaint describes a problem a later release has already fixed. Do not present it as a current problem.
Mention it as resolved and cite the release that fixed it, for example: "Users found checkout confusing [C054], but the redesign fixed this [R12-01]." """
)


def status_line(status: dict, include_dates: bool) -> str:
    if status["status"] != OUTDATED:
        return "status: CURRENT"
    when = f" as of {status['since']}" if include_dates else ""
    return f"status: OUTDATED{when}, fixed by {status['outdated_by']}"


def format_chunk(record: dict, status: dict | None, include_dates: bool) -> str:
    header = [f"id: {record['id']}", f"source_type: {record['source_type']}"]
    if include_dates:
        header.append(f"date: {record['date']}")
    header.append(f"product_area: {record['product_area']}")
    if status is not None:  # complaints only; changelog items carry no status
        header.append(status_line(status, include_dates))
    return "\n".join(header) + f"\ntitle: {record['title']}\ntext: {record['text']}"


def cited_block(cited_ids: list[str], log: StatusLog, as_of: str | None) -> list[dict]:
    """Output contract (docs/eval_plan.md). Complaint statuses come from the status log, not the model."""
    block = []
    for i in cited_ids:
        if not i.startswith("C"):
            block.append({"id": i})  # changelog IDs are evidence only
            continue
        s = log.status_as_of(i, as_of)
        entry = {"id": i, "status": s["status"]}
        if s["status"] == OUTDATED:
            entry["outdated_by"] = s["outdated_by"]
        block.append(entry)
    return block


def ask(
    cfg: Config,
    question: str,
    as_of: str | None = None,
    method: str = "hybrid",
    k: int | None = None,
    include_dates: bool | None = None,
    tag: str | None = None,
) -> dict:
    k = k or cfg.top_k
    include_dates = cfg.include_dates if include_dates is None else include_dates
    if as_of:
        date.fromisoformat(as_of)  # validate

    store = Store(cfg.store_path)
    if not store.records:
        raise SystemExit(f"Store {cfg.store_path} is empty. Run ingest first.")
    log = StatusLog(cfg.status_dir / f"{method}.json")
    if not log.meta:
        raise SystemExit(f"No status log for method '{method}'. Run: python -m src update --method {method}")

    client = make_client(cfg)
    q_vec = Embedder(cfg, client).embed_query(question)
    ranked = store.search(q_vec, as_of, k)  # identical retrieval to the baseline

    statuses = {r["id"]: log.status_as_of(r["id"], as_of) for r, _ in ranked if r["source_type"] == "complaint"}
    chunks = "\n\n---\n\n".join(format_chunk(r, statuses.get(r["id"]), include_dates) for r, _ in ranked)
    prompt = f"Retrieved records:\n\n{chunks}\n\n---\n\nQuestion: {question}"

    response = with_retry(
        lambda: client.models.generate_content(
            model=cfg.generation_model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=cfg.temperature),
        )
    )
    answer = response.text or ""
    retrieved_ids = {r["id"] for r, _ in ranked}
    cited = sorted(set(re.findall(r"\b(C\d{3}|R\d{2}-\d{2})\b", answer)))

    run = {
        "agent": f"full-{method}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "question": question,
        "as_of": as_of,
        "k": k,
        "include_dates": include_dates,
        "models": {
            "embedding": cfg.embedding_model,
            "embedding_dim": cfg.embedding_dim,
            "generation": cfg.generation_model,
            "temperature": cfg.temperature,
        },
        "relevancy": {"method": method, "status_log": str(log.path.name), **log.meta},
        "retrieved": [
            {"rank": i + 1, "id": r["id"], "source_type": r["source_type"], "date": r["date"],
             "score": round(s, 6), **({"status": statuses[r["id"]]["status"]} if r["id"] in statuses else {})}
            for i, (r, s) in enumerate(ranked)
        ],
        "prompt": {"system": SYSTEM_PROMPT, "user": prompt},
        "output": {"answer": answer, "cited": cited_block(cited, log, as_of)},
        "cited_not_retrieved": [c for c in cited if c not in retrieved_ids],
    }
    _log(cfg, run)
    return run
