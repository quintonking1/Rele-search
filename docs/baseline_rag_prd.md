# Baseline RAG Agent PRD

2026-11-04 · Quinton King

## Overview

The baseline is a plain RAG agent that answers questions about Tessera from one shared store of customer complaints and changelog items. It has no idea whether a complaint is still true after a release ships.

It is the control condition for the project. The full agent adds the change note step, the relevancy check, and a current or outdated status on each stored item (the orange boxes in the deck). Everything else in the pipeline is shared, so the eval can attribute any difference to those additions.

In the deck's example, a researcher asks in July what the team knows about checkout. The baseline should answer from whatever it retrieves, which may include a May complaint that checkout spans four confusing screens, even though checkout was redesigned in June.

## Goals and non-goals

**Goals**

- Answer natural-language questions about Tessera using retrieved complaints and changelog items, citing the IDs it used
- Store both datasets in one index with a shared schema, so a single query can pull from either source
- Let a question be asked "as of" a past date, so the deck's March, June, July scenario can be replayed
- Log every run in a form the eval can score later against the full agent, with identical questions
- Stay small enough to build and run quickly on free tiers

**Non-goals (the orange boxes, saved for the full agent)**

- Ingesting a new release note as an event that triggers anything
- A relevancy check between releases and stored items
- A current or outdated status field on stored items
- Staleness warnings or any instruction to reason about whether a finding still holds

## Data sources

Both datasets are synthetic, describe the same fictional product, and share the same product area and platform enums, so they can live in one store. Together they produce 149 chunks.

| Dataset | File | Records | Date range | One chunk is |
| --- | --- | --- | --- | --- |
| Complaints | tessera_complaints.json | 100 complaints | 2025-12-04 to 2026-10-21 | One complaint: title + text |
| Changelog | tessera_changelog.json | 49 items in 20 releases | 2026-01-13 to 2026-10-13 | One release item: release title + item title + description |

Each record is small (complaints are a few sentences, changelog items average 119 words), so no further splitting is needed. The changelog file name in the project currently has a stray space before `.json`, worth renaming before writing loaders.

**Unified record schema**

| Field | From complaints | From changelog |
| --- | --- | --- |
| id | complaint_id | item_id |
| source_type | `complaint` | `changelog` |
| date | date | release_date |
| product_area | product_area | product_area |
| title | title | title |
| text | text | description, with the release title prepended |
| platforms | platforms | platforms |
| plan | plan (single value) | plan_availability (list) |
| audience | customer_role | audience |
| extra | channel, severity, customer_id | version, release_id, change_type |
| vector | embedding of title + text | embedding of title + text |

## System design

The baseline keeps the gray boxes from the deck: one ingest path that fills the store, and one query path that reads from it.

```
INGEST (run once, re-run when data changes)

  tessera_complaints.json ─┐
                           ├─> normalize to unified schema ─> embed (Gemini) ─> memory store (JSON)
  tessera_changelog.json ──┘                                                     text, vector, date,
                                                                                 area, source_type

QUERY (per question)

  researcher question + as_of
        │
        ▼
  embed question ─> retrieve (records dated <= as_of, cosine similarity)
        │
        ▼
  rank (top k by similarity) ─> LLM answer with cited IDs ─> run log (JSON)
```

1. **Ingest:** both files are mapped to the unified schema, embedded, and written to one JSON store.
2. **Store:** text, vector, date, product area, and source type per record. No status field.
3. **Retrieve:** the question is embedded with the same model; only records dated on or before `as_of` are candidates.
4. **Rank:** candidates are ordered by cosine similarity and the top k are kept.
5. **Answer:** the LLM answers from the ranked chunks only and cites their IDs.
6. **Log:** every run is saved for the eval.

## Requirements

**Ingest**

1. Load both JSON files and map every record into the unified schema above.
2. Embed `title + text` for each record with the Gemini free-tier embedding model, and use the same model for questions.
3. Re-running ingest is idempotent: records are keyed by `id` and overwritten, never duplicated.

**Store**

1. Persist all 149 records, vectors included, in a single JSON file (agreed on 10/26; migrate to SQLite later).
2. No `status` field. Every record is treated as equally valid.

**Retrieve and rank**

1. Each query takes a question and an optional `as_of` date. Only records dated on or before `as_of` are candidates, which replays what the team would have known at that moment.
2. Score candidates by cosine similarity to the question vector and keep the top k (default 8, adjustable).
3. Rank by similarity score alone. Retrieval does not filter or boost by source type, recency, or product area.

**Answer**

1. Pass the ranked chunks to the LLM with their id, source type, date, and product area, and ask it to answer the question from those chunks only.
2. Every claim in the answer cites the IDs it came from (for example C054, R12-01).
3. The prompt gives no instruction about staleness or comparing complaints against releases.
4. Temperature 0, so repeated runs are comparable.

**Logging**

1. Save one JSON record per run: question, `as_of`, retrieved IDs with scores and ranks, the prompt, the answer, model names, and a timestamp.
2. Logs are the input to the eval, so the full agent must write the same format.

## Success criteria and quick eval

The baseline is done when all 149 records are ingested, every seed question below returns a cited answer, and each run is logged. Full eval design comes later; this is a smoke test that also previews where the baseline should fail.

For each run, note the deck's two errors: a **stale answer** (an outdated complaint presented as current) and a **lost finding** (a still-true complaint left out or dismissed).

| Question | as_of | Outdated by then | Still true by then |
| --- | --- | --- | --- |
| What do we know about checkout? | 2026-07-15 | C054 four-screen upgrade flow (R12-01, Jun 16) | C070 no PayPal |
| What are users' problems with search? | 2026-05-15 | C019 and C034 coverage gaps (R08-01, Apr 21); C046 mobile filters reset (R09-02, May 5) | C052 Excel attachments not indexed |
| Can people use Tessera on mobile without a connection? | 2026-06-30 | C035 and C048 no offline access (R10-01, May 19) | C060 large databases only partly download |
| What do users think of the sidebar? | 2026-09-01 | C008 collapsed sections reopen (R02-01, Jan 27) | C014 and C061 miss the flat list, now only partly resolved (R16-01, Aug 18) |
| What pain do developers have detecting database changes? | 2026-10-20 | C087 polling (R19-02, Sep 29); C097 duplicate events (R20-02, Oct 13) | C096 pages not covered; C098 20-subscription cap |

The sidebar row is the partial case. How to score it depends on whether the full agent gets a third status, which is still open.

## Open questions and next steps

**Open questions**

- Which LLM generates answers? It should be the same model the full agent uses.
- Which Gemini embedding model and dimension? 149 records plus questions should sit well inside the free tier.
- What is the "system one model" in the deck's rank step? This draft ranks by similarity only; an LLM reranker would also go in the full agent.
- Should dates reach the prompt? Showing them is realistic, but a capable model may notice a June release answers a May complaint on its own, which narrows the gap the project is measuring. Worth running both ways once.
- Is k = 8 enough when a question spans both a complaint and the release that resolved it?

**Next steps**

- [ ] Set up Gemini embeddings
- [ ] Build the loader and unified schema; embed and write the JSON store
- [ ] Build retrieve, rank, and answer with the `as_of` filter
- [ ] Run the five seed questions and save logs
- [ ] Review logs together and start the eval design