# Rele-search

**A Continual Learning Research Agent for Product Organizations.** Final project by Quinton King and Sanjali Roy (UC Berkeley I School).

Product teams collect research (complaints, interviews, findings) while the product keeps shipping. A finding like "checkout is confusing" can be outdated once checkout is redesigned, and standard RAG returns it with no warning. This project builds an agent that tracks release notes and flags research a later release has made outdated, and measures it against a plain RAG baseline.

**Research question:** how should the agent decide that a release affects a finding: by product area, by text similarity, or by a model's judgment?

## Status

| Piece | State |
| --- | --- |
| Baseline RAG agent | Built. Ingest, retrieve, rank, answer, log. Seed questions run with and without dates in the prompt. |
| Complaint labels | Drafted and passing all checks, **awaiting review** (`eval/labels/DRAFT_SUMMARY.md`). 58 fully fixed, 2 partially fixed, 55 never fixed (includes 15 near misses added 2026-11-09). |
| Topic briefs | Drafted for 23 groups, awaiting review |
| Questions | Not generated yet. Blocked on the open decisions below. |
| Eval harness, split, scoring | Not started |
| Full agent | First version built on branch `full-agent`: four relevancy methods (area, similarity, llm, hybrid), status log, `ask-full`. area and similarity have been run; llm and hybrid need a first run with an API key. |

## Open decisions

1. **Cross-group decoys.** For three decoys (R01-02, R03-02, R06-02), the complaint the decoy fixes sits in a different group from the finding it is a decoy for. `relevant_complaints` is computed from one group, so half of each decoy test would be scored as off-topic. Options are in `eval/labels/DRAFT_SUMMARY.md`. Needs deciding before Prompt 2.
2. **Items that fix no complaint.** R01-01, R10-04, and R19-01 have no complaint expressing their target finding, so they cannot get before and after pairs. Drop them from coverage, or add complaints for them.
3. **Labels marked REVIEW:** C045, C092, C095.
4. **Small groups.** api v1, microsoft teams, and slash menu hold one complaint each. Consider merging some before the split.
5. **Re-embed after adding complaints.** C101 to C115 are new near misses, each dated before a release in the same area that does not fix it (before this, only C073 tested the relevancy check, since the other near misses come after their release). `data/store.json` does not have vectors for them yet: run `python -m src ingest`, commit the new store, then re-run `python -m src update` for every method.
6. **Partial status.** The full agent has two statuses (current, outdated). The scoring table counts a partial complaint reported as current as a stale answer, which affects C014 and C061.
7. **Agent run logs** stay in `runs/` at the root, since agent code may not reference `eval/`. `eval/runs/` is for the harness only. The eval plan's file layout should list `runs/`.

## Repo layout

```
src/                     agent code (must never read eval/)
  baseline.py            ingest, retrieve, answer, log
  relevancy.py           full agent: relevancy check (area, similarity, llm, hybrid)
  status.py              full agent: status log with as_of lookup
  agent.py               full agent: baseline retrieval + status in prompt + cited statuses from the log
  config.py              settings from .env
  schema.py              unified record schema for both datasets
  embed.py               Gemini embeddings
  store.py               JSON vector store with as_of filter
  retry.py               retries for rate limits and overload
data/
  tessera_complaints.json   115 complaints, 2025-12-04 to 2026-10-21 (C101 to C115 are added near misses)
  tessera_changelog.json    20 releases, 49 items, 2026-01-13 to 2026-10-13
  store.json                embedded store (committed so both of us use identical vectors)
  status/<method>.json      full agent status log per relevancy method (events + every check)
eval/                    answer key and eval code (the agent never sees this)
  tessera_changelog_README.md   role of each changelog item; input to the answer key
  prompts/                      generation prompts for labels and questions
  labels/complaint_labels.json  fix history per complaint (draft; see labels/DRAFT_SUMMARY.md)
  validate_labels.py            rule checks and coverage report for the labels
  topic_briefs.json             one brief per group (23), input to the question prompt
  seeds.py, run_seeds.py        five seed questions from the PRD (--method runs the full agent)
  score_relevancy.py            scores each method's status log against the labels
runs/                    one JSON log per agent run
tests/                   isolation test; offline tests for the full agent (fake model)
docs/
  baseline_rag_prd.md    baseline spec
  eval_plan.md           eval spec
CLAUDE.md                project context for Claude Code
```

## Setup

Requires Python 3.12.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env     # then add your own GOOGLE_API_KEY
```

Get a free key at https://aistudio.google.com/apikey. `.env` is gitignored; never commit it.

**Models** (set in `.env`):
- Embeddings: `gemini-embedding-2`, 768 dimensions
- Answers: `gemini-3.6-flash`, temperature 0. The full agent must use the same model.

## Usage

```bash
# Embed both datasets into data/store.json (only needed if data or embedding settings change)
.venv/bin/python -m src ingest

# Ask one question, as of a past date
.venv/bin/python -m src ask "What do we know about checkout?" --as-of 2026-07-15

# Run the five seed questions and show which expected records were retrieved
.venv/bin/python -m eval.run_seeds
.venv/bin/python -m eval.run_seeds --no-dates    # hide record dates from the LLM

# Check the complaint labels against the labeling rules and print a coverage report
.venv/bin/python -m eval.validate_labels

# Check that agent code never references the answer key
.venv/bin/python -m unittest discover tests
```

Options for `ask` and `run_seeds`: `-k N` sets how many records are retrieved (default 8), and `--no-dates` hides record dates from the answer prompt.

Each run writes a log to `runs/` with the question, `as_of`, retrieved IDs with scores and ranks, the full prompt, the output, and model names.

## How the baseline works

1. **Ingest:** complaints and changelog items are mapped to one shared schema and embedded with `gemini-embedding-2`.
2. **Retrieve:** the question is embedded, and only records dated on or before `as_of` are candidates.
3. **Rank:** top k by cosine similarity, with no boosting by source, date, or product area.
4. **Answer:** the LLM answers from the retrieved records only and cites their IDs. The prompt says nothing about staleness.
5. **Log:** every run is saved for the eval.

The baseline is the control condition. It deliberately has no status field, no relevancy check, and no staleness warnings; those belong to the full agent.

Output contract (both agents):

```json
{"answer": "prose", "cited": [{"id": "C054", "status": "current"}, {"id": "R12-01"}]}
```

The baseline has no status concept, so every complaint it cites is reported as `current`.

**First seed results (k = 8, dates shown).** All five questions returned cited answers. Most misses were in retrieval. On the webhooks question, 3 of 6 expected records ranked outside the top 8, at ranks 9, 19, and 24. When dates were shown, the model often noticed on its own that a later release had fixed a complaint, which narrows the gap the project measures. Runs without dates are also in `runs/` for comparison.

## How the full agent works

Same retrieval, ranking, model, temperature, and log format as the baseline. What it adds:

1. **Relevancy check** (`python -m src update --method <method>`): walks the releases in date order. For each release, it decides which earlier, still-current complaints the release fixes, and writes them to `data/status/<method>.json` with the release ID, date, reason, and quoted evidence. Every decision (yes or no) is kept under `checks` for error analysis. Once outdated, a complaint stays outdated.
2. **Status as of a date:** a complaint is outdated as of `as_of` only if its outdating release is dated on or before `as_of`. The same log answers "as of May" and "as of July."
3. **Prompt:** each retrieved complaint gets a line like `status: OUTDATED as of 2026-06-16, fixed by R12-01` or `status: CURRENT`, and the system prompt says to present outdated complaints as resolved and cite the release.
4. **Output:** code fills the `cited` statuses from the status log; the model never writes them. The eval then measures the relevancy check, not how well the model copies a label.

**Relevancy methods** (the research question, one flag):

| Method | Decides "release fixes complaint" when | Model calls |
| --- | --- | --- |
| `area` | same product area, complaint dated before the release | none |
| `similarity` | cosine similarity >= `SIMILARITY_THRESHOLD` (default 0.80) | none |
| `llm` | the model says yes, judging the `RELEVANCY_CANDIDATES` (10) most similar earlier complaints | 1 per release (49) |
| `hybrid` | platform and plan overlap (metadata gates), then the llm step on what passes | 1 per release (49) |

The 0.80 threshold is the 98th percentile of release-to-earlier-complaint similarity, chosen without looking at labels (about one flag per release). Tune it on the dev split once the split exists.

```bash
.venv/bin/python -m src update --method hybrid       # writes data/status/hybrid.json
.venv/bin/python -m src ask-full "What do we know about checkout?" --as-of 2026-07-15 --method hybrid
.venv/bin/python -m eval.run_seeds --method hybrid
.venv/bin/python -m eval.score_relevancy --show-errors   # compare methods against the labels
```

**First relevancy scores** (original 100 complaints, before C101 to C115 were added; no split yet, labels still a draft):

| Method | Correct | Wrong release | Missed | False flag | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- |
| area | 36 | 22 | 0 | 27 | 0.42 | 0.62 |
| similarity | 46 | 1 | 11 | 1 | 0.96 | 0.79 |
| llm | not run yet | | | | | |
| hybrid | not run yet | | | | | |

Similarity's precision here is inflated: the near misses in C001 to C100 are dated after their releases, so the check never sees them. C101 to C115 fix that; re-run after re-embedding (open decision 5). Six of them should be stopped by the hybrid's platform and plan gates (C101, C103, C106, C107, C111, C112), and nine need judgment.

## Evaluation

Full spec in `docs/eval_plan.md`.

- **Errors counted:** a **stale answer** (an outdated complaint presented as current) and a **lost finding** (a still-true complaint missed or marked outdated).
- **Answer key:** `eval/labels/complaint_labels.json` gives each complaint a `history` of fixes. A complaint's status at any date is computed from it. Any changelog item can fix a complaint, including items the README calls decoys.
- **Grading is deterministic:** code compares the agent's `cited` block to statuses computed from the labels. No model grades the headline metrics.
- **Isolation:** the agent only ever receives `{question, as_of}`. `tests/test_isolation.py` fails if anything in `src/` references `eval/` or the changelog README.
- **Split:** question groups are shuffled with a fixed seed into dev (about 40%) and test. Tune on dev only; run test once per agent after freezing.

### Building the answer key

1. ~~Run `eval/prompts/01_complaint_labels.md` to draft labels.~~ Done; drafted by Claude Opus 5.5, which is not either agent's answer model.
2. Review the labels together, starting with `eval/labels/DRAFT_SUMMARY.md`. After any edit, run `python -m eval.validate_labels`.
3. Settle open decisions 1 and 2 above.
4. Run `eval/prompts/02_questions.md` with the reviewed labels and `eval/topic_briefs.json`.
5. Generate and commit `eval/split.json`.

## Data

Both datasets are synthetic and describe **Tessera**, a fictional Notion-like workspace. They share the same product area and platform enums, so they live in one store (164 records). `eval/tessera_changelog_README.md` documents the schema and each changelog item's role: invalidator, partial, decoy, or neutral.
