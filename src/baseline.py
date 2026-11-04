"""Baseline RAG agent: ingest, then retrieve -> rank -> answer -> log."""

import json
import re
from datetime import date, datetime, timezone

from google import genai
from google.genai import types

from .config import Config
from .embed import Embedder, document_text
from .retry import with_retry
from .schema import load_all
from .store import Store

# Deliberately no instruction about staleness or comparing complaints with releases (PRD Answer 3).
SYSTEM_PROMPT = """You are a research assistant for the product team at Tessera, an all-in-one workspace app.
Answer the researcher's question using ONLY the retrieved records provided. Records are customer complaints and changelog items.
Cite the record IDs that support every claim in square brackets, for example [C054] or [R12-01].
If the records do not contain enough information to answer, say so."""


def make_client(cfg: Config) -> genai.Client:
    if not cfg.api_key:
        raise SystemExit("GOOGLE_API_KEY is not set. Add it to .env.")
    return genai.Client(api_key=cfg.api_key)


def ingest(cfg: Config) -> int:
    client = make_client(cfg)
    records = load_all(cfg.complaints_path, cfg.changelog_path)
    print(f"Loaded {len(records)} records; embedding with {cfg.embedding_model} ({cfg.embedding_dim}d)")
    vectors = Embedder(cfg, client).embed([document_text(r) for r in records])
    for r, v in zip(records, vectors):
        r["vector"] = v
    store = Store(cfg.store_path)
    if store.meta and (store.meta.get("embedding_model"), store.meta.get("embedding_dim")) != (
        cfg.embedding_model,
        cfg.embedding_dim,
    ):
        store.records = {}  # vectors from a different model/dimension are not comparable
    store.meta = {"embedding_model": cfg.embedding_model, "embedding_dim": cfg.embedding_dim}
    store.upsert(records)
    store.save()
    print(f"Wrote {len(store.records)} records to {cfg.store_path}")
    return len(store.records)


def format_chunk(record: dict, include_dates: bool) -> str:
    header = [f"id: {record['id']}", f"source_type: {record['source_type']}"]
    if include_dates:
        header.append(f"date: {record['date']}")
    header.append(f"product_area: {record['product_area']}")
    return "\n".join(header) + f"\ntitle: {record['title']}\ntext: {record['text']}"


def build_prompt(question: str, ranked: list[tuple[dict, float]], include_dates: bool) -> str:
    chunks = "\n\n---\n\n".join(format_chunk(r, include_dates) for r, _ in ranked)
    return f"Retrieved records:\n\n{chunks}\n\n---\n\nQuestion: {question}"


def ask(
    cfg: Config,
    question: str,
    as_of: str | None = None,
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
    if store.meta.get("embedding_model") != cfg.embedding_model or store.meta.get("embedding_dim") != cfg.embedding_dim:
        raise SystemExit("Store was built with a different embedding model/dimension. Re-run ingest.")

    client = make_client(cfg)
    q_vec = Embedder(cfg, client).embed_query(question)
    ranked = store.search(q_vec, as_of, k)
    prompt = build_prompt(question, ranked, include_dates)

    response = with_retry(
        lambda: client.models.generate_content(
            model=cfg.generation_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=cfg.temperature,
            ),
        )
    )
    answer = response.text or ""
    retrieved_ids = {r["id"] for r, _ in ranked}
    cited = sorted(set(re.findall(r"\b(C\d{3}|R\d{2}-\d{2})\b", answer)))
    output = {"answer": answer, "cited": cited_block(cited)}

    run = {
        "agent": "baseline",
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
        "retrieved": [
            {"rank": i + 1, "id": r["id"], "source_type": r["source_type"], "date": r["date"], "score": round(s, 6)}
            for i, (r, s) in enumerate(ranked)
        ],
        "prompt": {"system": SYSTEM_PROMPT, "user": prompt},
        "output": output,
        "cited_not_retrieved": [c for c in cited if c not in retrieved_ids],
    }
    _log(cfg, run)
    return run


def cited_block(cited_ids: list[str]) -> list[dict]:
    """Shared output contract (docs/eval_plan.md, "Agent output contract").

    The baseline has no status concept, so every complaint it cites is reported
    as "current" by construction; the model is never asked for a status.
    Changelog IDs are evidence only and carry no status.
    """
    return [
        {"id": i, "status": "current"} if i.startswith("C") else {"id": i}
        for i in cited_ids
    ]


def _log(cfg: Config, run: dict) -> None:
    cfg.runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = run["timestamp"].replace(":", "").replace("-", "").split(".")[0]
    slug = re.sub(r"[^a-z0-9]+", "-", run["question"].lower()).strip("-")[:40]
    path = cfg.runs_dir / f"{stamp}_{run['agent']}_{slug}.json"
    path.write_text(json.dumps(run, indent=2))
    run["log_path"] = str(path)
