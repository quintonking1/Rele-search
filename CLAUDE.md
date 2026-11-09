# CLAUDE.md

Context for Claude when working in this repo. Read this before making changes.

## Project

**A Continual Learning Research Agent for Product Organizations.** Final project by Quinton King and Sanjali Roy (UC Berkeley I School).

Product teams pile up research (complaints, interviews, findings), but the product keeps shipping. A finding like "checkout is confusing" can be outdated once checkout is redesigned. Standard RAG returns stale findings with no warning. This agent tracks release notes and flags research that a later release has made outdated.

**Research question:** how should the agent decide that a release affects a finding: by product area, by text similarity, or by a model's judgment? Topic matching alone is not enough, because a finding can share a product area with a release and still be true.

## Current phase: full agent (first version)

The baseline is built. The full agent's first version lives in `src/relevancy.py`, `src/status.py`, and `src/agent.py` (see the README). Baseline files (`src/baseline.py`, `data/store.json`) must stay unchanged so the comparison stays clean; the full agent imports from them but never modifies them.

## Baseline

We built the **baseline** first: a plain shared RAG system with no staleness awareness. It is the control condition the full agent is compared against. The spec is `docs/baseline_rag_prd.md`; the eval spec is `docs/eval_plan.md`.

**In scope (baseline)**
- One shared store holding both complaints and changelog items
- Ingest, embed, retrieve, rank by similarity, answer with cited IDs, log every run
- An `as_of` date filter so questions can be asked as of a past date

**Out of scope until the full agent** (the orange boxes in the deck)
- Change note ingestion as a trigger
- Relevancy check between releases and stored items
- A current or outdated status field
- Staleness warnings or prompt instructions about whether a finding still holds

Do not add any of the out-of-scope features to the baseline, even partially. The comparison depends on the baseline staying naive.

## Data

Both datasets are synthetic and describe **Tessera**, a fictional Notion-like workspace (notes, docs, databases, calendar, mail).

| File | Contents |
| --- | --- |
| `data/tessera_complaints.json` | 100 customer complaints, 2025-12-04 to 2026-10-21 |
| `data/tessera_changelog.json` | 20 releases, 49 items, 2026-01-13 to 2026-10-13 |
| `eval/tessera_changelog_README.md` | Schema, plus the role of each changelog item (invalidator, partial, decoy, neutral) and its target finding |

- One complaint = one chunk. One changelog item = one chunk (release title + item title + description). 149 chunks total.
- Both datasets share the same `product_area` and `platforms` enums.
- The README's role table is input for building the answer key. The agent must never read it.

**Unified record schema:** `id`, `source_type` (`complaint` or `changelog`), `date`, `product_area`, `title`, `text`, `platforms`, `plan`, `audience`, `extra`, `vector`. Mapping details are in the PRD.

## Stack and decisions

- **Embeddings:** Gemini free-tier embedding model. Use the same model for records and questions.
- **Storage:** a single JSON file for now; migrate to SQLite later.
- **Retrieval:** cosine similarity, top k (default 8), filtered to records dated on or before `as_of`.
- **Answering:** LLM answers from retrieved chunks only, cites IDs (for example C054, R12-01), temperature 0.
- **Logging:** one JSON record per run (question, `as_of`, retrieved IDs with scores and ranks, prompt, answer, model names, timestamp). The full agent must use the same log format.
- **Secrets:** API keys come from environment variables. Never hard-code or commit them.

Open decisions (ask before choosing): answer LLM, exact embedding model, whether to add an LLM reranker, whether dates appear in the answer prompt, and whether status gets a third "partial" value later. The full agent currently uses two statuses (current, outdated).

## Evaluation

Full spec: `docs/eval_plan.md`. The essentials:

- **Isolation:** agent code lives in `src/` and never reads anything under `eval/`. The harness passes the agent only `{question, as_of}`.
- **Answer key:** `eval/labels/complaint_labels.json` (a fix `history` per complaint) and `eval/questions/questions.json`. Drafted once, reviewed, committed, then frozen.
- **Any changelog item can resolve a complaint**, including README decoys and neutrals. README roles describe effects on target findings only.
- **Grading is deterministic:** code compares the agent's `cited` block to statuses computed from the label file at `as_of`. No model grades the headline metrics.
- **Split:** groups shuffled with a fixed seed into dev (about 40%) and test. Tune on dev only. Run test once per agent, after freezing.
- **Errors counted:** stale answer (outdated complaint cited as current) and lost finding (still-true complaint missed or marked outdated).

Agent output format (both agents):

```json
{"answer": "prose", "cited": [{"id": "C054", "status": "outdated", "outdated_by": "R12-01"}]}
```

The baseline has no status concept, so everything it cites is scored as current.

## Roles

- **Quinton:** pipeline and relevancy check
- **Sanjali:** passages, release notes, and evaluation

## Working conventions

- Prefer small, readable Python scripts over frameworks. Explain non-obvious code in short comments.
- Keep ingest, retrieval, answering, and eval as separate modules.
- When finishing a chunk of work, summarize what was done step by step so it can be shared with the team.
- Writing style for docs and messages: no em-dashes, and avoid the "not x, not y, but z" sentence structure.