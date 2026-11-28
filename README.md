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
| Questions | **Approved** 2026-11-26: 79 pairs in `eval/questions/questions.json` (dev 17, train 30, test 32), from `python -m eval.make_questions`. Decision 1: option (a), two questions per cross-group decoy. Decision 2: R01-01, R19-01 and R10-04 are skipped. Partials are scored as partial. Approved by Sanjali and Quinton 2026-11-26. |
| Split | Done 2026-11-20 (`eval/split.json`, seed in `eval/config.json`): test 40% (46 complaints, held out), dev 20% (23), train 40% (46), split by group. |
| Eval harness, question-level scoring | **Built** 2026-11-26: `eval/harness.py` and `eval/scoring.py` (Test 2). Checked with the oracle agent and unit tests; not yet run on a real agent. `eval.score_relevancy` scores the relevancy check per split. |
| Full agent | First version built: four relevancy methods (area, similarity, llm, hybrid), status log, `ask-full`. All four methods run on OpenAI (run tag `openai-v1`, 2026-11-20). **V2** (judge v2, requirements checklist and a partial status) run 2026-11-27; **V2.1** (judge v2.1) run 2026-11-27, frozen. **Decisions judge** (OpenAI Decisions API) run 2026-11-27, frozen. **Test split run once for every version, 2026-11-28**: see [Final results](#final-results-test-split). |
| Models | Switched from Gemini to OpenAI on 2026-11-20 (`text-embedding-3-small`, `gpt-4.1`). See [Attempts so far](#attempts-so-far). |

## Open decisions

1. ~~**Cross-group decoys.**~~ Decided 2026-11-26: option (a). Each half of a cross-group decoy gets its own pair in its own group.
2. ~~**Items that fix no complaint.**~~ Decided 2026-11-26: R01-01, R10-04, and R19-01 are left out of Test 2 coverage.
3. **Labels marked REVIEW:** C045, C092, C095.
4. **Small groups.** api v1, microsoft teams, and slash menu hold one complaint each. Consider merging some before the split.
5. ~~**Re-embed after adding complaints.**~~ Done 2026-11-20 with the OpenAI re-ingest: `data/store.json` now holds all 164 records, including C101 to C115, and every method has been re-run.
6. ~~**Partial status.**~~ Decided 2026-11-26: V2 adds a partial status, produced by judge v2. Runs with judge v1 (such as `openai-v1`) still have two statuses. Test 2 and Test 1 both score partials.
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
  embed.py               OpenAI embeddings
  llm.py                 OpenAI client and chat calls, shared by both agents
  store.py               JSON vector store with as_of filter
  retry.py               retries for rate limits, server errors, and dropped connections
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
cp .env.example .env     # then add your own OPENAI_API_KEY
```

Get a key at https://platform.openai.com/api-keys. `.env` is gitignored; never commit it.

**Models** (set in `.env`):
- Embeddings: `text-embedding-3-small`, 1536 dimensions
- Answers: `gpt-4.1`, temperature 0. The full agent must use the same model.

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

1. **Ingest:** complaints and changelog items are mapped to one shared schema and embedded with `text-embedding-3-small`.
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

**First seed results (Gemini, k = 8, dates shown).** All five questions returned cited answers. Most misses were in retrieval. On the webhooks question, 3 of 6 expected records ranked outside the top 8, at ranks 9, 19, and 24. When dates were shown, the model often noticed on its own that a later release had fixed a complaint, which narrows the gap the project measures. Runs without dates are also in `runs/` for comparison.

## How the full agent works

Same retrieval, ranking, model, temperature, and log format as the baseline. What it adds:

1. **Relevancy check** (`python -m src update --method <method>`): walks the releases in date order. For each release, it decides which earlier, still-current complaints the release fixes, and writes them to `data/status/<method>.json` with the release ID, date, reason, and quoted evidence. Every decision (yes or no) is kept under `checks` for error analysis. Once outdated, a complaint stays outdated.
2. **Status as of a date:** a complaint is outdated as of `as_of` only if its outdating release is dated on or before `as_of`. The same log answers "as of May" and "as of July."
3. **Prompt:** each retrieved complaint gets a line like `status: OUTDATED as of 2026-06-16, fixed by R12-01` or `status: CURRENT`, and the system prompt says to present outdated complaints as resolved and cite the release.
4. **Output:** code fills the `cited` statuses from the status log; the model never writes them. The eval then measures the relevancy check, not how well the model copies a label.

**Judge v2 and v2.1 (V2, V2.1).** The llm and hybrid methods take `--judge v1`, `--judge v2`, or `--judge v2.1` (default v2.1):
- **v1** asks one yes or no question per complaint: does this release fully fix it?
- **v2** asks the model for a requirements checklist. It lists what the customer needs (1 to 4 items, the core need first) and checks each one against the release as met, partly, or not met, quoting the release. Code then turns the checklist into a verdict: every item met is **fixed** (outdated), core need not met is **not fixed**, anything in between is **partial**. A partial complaint stays open, so a later release can still fix it fully.
- The checklist is kept in each check, so `score_relevancy --show-errors` shows why each verdict was reached.
- The prompt gets a PARTIAL instruction only when the status log came from judge v2, so v1 runs keep exactly the v1 prompt.
- Built from the v1 mistakes on train: C115 (a related feature that covers a different property type) and C014 and C061 (partly fixed, which v1 could only call fixed). Dev and test were not used to design it.
- **decisions** (`--judge decisions`) uses the OpenAI Decisions API (`POST /v1/decisions`, model `gpt-6-luna`, set with `DECISIONS_MODEL`). One call per release: the release is the input, and each candidate complaint is a choice question with three options (fixed, partial, not fixed) whose descriptions restate the v2.1 rule. The API returns a choice, a confidence, and probabilities, and writes no text, so these checks have no quoted evidence or written reason. The status log keeps the confidence and probabilities, plus token counts in `meta.counts`. Note for comparisons: the API runs a different model from gpt-4.1, so a difference against v2.1 mixes the API with the model.
- **v2.1** changes two things, both from the v2 mistakes on train. Partial now needs the core need fully met; a core need that is only partly met means not fixed (the model marked a related feature for a different case as "partly", C115). The instruction to add a "default experience changes" requirement is gone (it made v2 call fully fixed C077 partial, and did not change C014 or C061).

**Relevancy methods** (the research question, one flag):

| Method | Decides "release fixes complaint" when | Model calls |
| --- | --- | --- |
| `area` | same product area, complaint dated before the release | none |
| `similarity` | cosine similarity >= `SIMILARITY_THRESHOLD` (default 0.55) | none |
| `llm` | the model says yes, judging the `RELEVANCY_CANDIDATES` (10) most similar earlier complaints | 1 per release (49) |
| `hybrid` | platform and plan overlap (metadata gates), then the llm step on what passes | 1 per release (49) |

The threshold depends on the embedding model. With Gemini it was 0.80 (the 98th percentile of release-to-earlier-complaint similarity). OpenAI's `text-embedding-3-small` scores much lower (median pair 0.22, 99th percentile 0.60), so it is now 0.55, set from the score distribution without looking at labels. Tune it on the dev split once the split exists.

```bash
.venv/bin/python -m src update --method hybrid --tag v2.1         # judge v2.1 by default; appends a run to data/status/hybrid.jsonl
.venv/bin/python -m src update --method hybrid --judge v1 --tag T  # the original yes/no judge
.venv/bin/python -m src ask-full "What do we know about checkout?" --as-of 2026-07-15 --method hybrid [--status-tag v2.1]
.venv/bin/python -m eval.run_seeds --method hybrid
.venv/bin/python -m eval.score_relevancy --show-errors   # compare methods against the labels
```

**Latest relevancy scores: dev split** (OpenAI, run tag `openai-v1`, 23 complaints in 5 groups; labels still a draft):

| Method | Correct | Wrong release | Missed | False flag | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| area | 9 | 4 | 0 | 7 | 0.45 | 0.69 | 0.55 |
| similarity (0.55) | 10 | 0 | 3 | 1 | 0.91 | 0.77 | 0.83 |
| llm | 13 | 0 | 0 | 1 | 0.93 | 1.00 | 0.96 |
| hybrid | 13 | 0 | 0 | 1 | 0.93 | 1.00 | 0.96 |

On dev's 3 near misses, false flags were: area 3, similarity 1, llm 0, hybrid 0. In the hybrid run, the platform and plan gates rejected 155 of the pairs llm would have judged, and llm and hybrid still reached the same verdicts. Tune on dev only (`--split dev`). The test split is scored once per agent after freezing.

Score with `.venv/bin/python -m eval.score_relevancy --tag openai-v1 --split dev`.

## Attempts so far

A running record of what has been tried, so results from different setups are not mixed up.

**1. Baseline on Gemini (2026-11-04).** `gemini-embedding-2` (768 dimensions) and `gemini-3.6-flash` at temperature 0. The five seed questions all returned cited answers. Most misses were in retrieval (on the webhooks question, 3 of 6 expected records ranked 9, 19, and 24). With dates in the prompt, the model sometimes noticed on its own that a later release fixed a complaint. Logs are the 2026-11-04 files in `runs/`.

**2. Full agent v1 on Gemini (2026-11-09).** Four relevancy methods added. area and similarity (threshold 0.80) were scored on the original 100 complaints:

| Method | Correct | Wrong release | Missed | False flag | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- |
| area | 36 | 22 | 0 | 27 | 0.42 | 0.62 |
| similarity | 46 | 1 | 11 | 1 | 0.96 | 0.79 |

Similarity's precision was inflated: the near misses in C001 to C100 are dated after their releases, so the check never saw them.

**3. Near misses added (2026-11-09).** C101 to C115, each dated before a release in the same product area that does not fix it, so the relevancy check is actually tested on them. A Gemini re-run of the llm method on 2026-11-15 hit the free-tier quota (429 errors, logged in `data/status/failed_calls.jsonl`), so llm and hybrid were never fully run on Gemini.

**4. Switch to OpenAI (2026-11-20).** To get past the free-tier limits, both agents moved to OpenAI: `text-embedding-3-small` (1536 dimensions) for embeddings, and `gpt-4.1` at temperature 0 for answers and the relevancy judge. All API calls go through `src/llm.py`, so the baseline and the full agent call the model the same way. The baseline's prompt and logic are unchanged. The store was re-embedded (all 164 records), the similarity threshold was lowered to 0.55 to fit the new score range, and all four methods were re-run under tag `openai-v1`. The first hybrid run stalled for about 40 minutes on what was most likely one stuck API call, so calls now have a 120-second timeout (`LLM_TIMEOUT`) and a 4,000-token output cap (`LLM_MAX_TOKENS`); the rerun finished in a few minutes with no failed calls. One llm or hybrid run costs roughly $0.30 at gpt-4.1 list prices.

Scores on all 115 complaints, taken before the split existed. These include the test groups, so they are for the record only and should not guide tuning:

| Method | Correct | Wrong release | Missed | False flag | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| area | 36 | 22 | 0 | 42 | 0.36 | 0.62 | 0.46 |
| similarity (0.55) | 46 | 0 | 12 | 9 | 0.84 | 0.79 | 0.81 |
| llm | 58 | 0 | 0 | 2 | 0.97 | 1.00 | 0.98 |
| hybrid | 58 | 0 | 0 | 2 | 0.97 | 1.00 | 0.98 |

**5. Train, dev, and test split (2026-11-20).** Groups split whole with seed 20261120: test 40% (46 complaints, held out), dev 20% (23), train 40% (46). Groups are weighted by complaint count until `questions.json` exists. Each split has both fixed and never-fixed complaints and at least 3 near misses. Dev scores are the table above. Gemini status-log runs are kept in `data/status/*.jsonl` under their own tags. Gemini run logs in `runs/` are not comparable with OpenAI runs.

**6. Test 2 "before" runs (2026-11-26).** Baseline and full hybrid (status log `openai-v1`, judge v1) on dev and train, k=8, no failed pairs. Run files are in `eval/runs/`.

| Run | Pairs | Stale answer rate | Lost finding rate | Retrieval recall |
| --- | --- | --- | --- | --- |
| Baseline, dev | 17 | 0.74 | 0.33 | 0.71 |
| Hybrid v1, dev | 17 | 0.00 | 0.39 | 0.71 |
| Baseline, train | 30 | 0.46 | 0.68 | 0.38 |
| Hybrid v1, train | 30 | 0.00 | 0.70 | 0.38 |

Hybrid never reported a fixed complaint as current. Almost every lost finding is a retrieval miss shared by both agents (dev 10 of 13, train 48 of 50 for hybrid). The only lost findings hybrid caused itself were C040 (dev, false flag) and C061 (train, partial called fixed), 2 per split. Some topics retrieve very little with one question per topic (webhooks 0 of 15, Slack 1 of 8, mobile 9 of 47 relevant complaints).

**7. V2: judge v2 with partial status (2026-11-27).** Built on train mistakes only; see "Judge v2 and v2.1" above. Run tag `v2`, no failed calls.

Test 1 (relevancy check):

| Split | Version | Correct | Missed | False flag | False partial | Partial wrong | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Train | v1 | 22 | 0 | 1 | 0 | 2 | 0.96 | 1.00 |
| Train | v2 | 21 | 1 | 0 | 1 | 2 | 1.00 | 0.95 |
| Dev | v1 | 13 | 0 | 1 | 0 | 0 | 0.93 | 1.00 |
| Dev | v2 | 13 | 0 | 0 | 1 | 0 | 1.00 | 1.00 |

Test 2 (stale answer rate / lost finding rate): train v1 0.00 / 0.70, v2 0.03 / 0.70; dev v1 0.00 / 0.39, v2 0.00 / 0.39.

What changed per complaint: C115 (train) and C040 (dev) moved from fixed to partial, but they are never fixed, so they still count as errors (the judge's own reasons say the release covers a different case, yet it marked the core need "partly"). C014 and C061 stayed fixed: the customers asked for an option and the release gives one, while the labels say partial because grouping stays the default. C077 (train) was a new error: fully fixed, called partial because of the "default experience" instruction, which produced 2 stale answers in Test 2. V2 was no better than V1.

**8. V2.1: judge v2.1 (2026-11-27).** Two fixes from the v2 train mistakes; see "Judge v2 and v2.1" above. Run tag `v2.1`, no failed calls. Frozen after this run.

| Split | Version | Correct | Missed | False flag | False partial | Partial wrong | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Train | v2.1 | 22 | 0 | 0 | 0 | 2 | 1.00 | 1.00 |
| Dev | v2.1 | 13 | 0 | 0 | 0 | 0 | 1.00 | 1.00 |

Test 2 (stale answer rate / lost finding rate): train 0.00 / 0.70, dev 0.00 / 0.33. On dev every lost finding is a retrieval miss, the same ones the baseline has. On train the only judge-caused lost findings are C061 (labeled partial, called fixed).

The judge returned no partial verdicts at all, so v2.1's gain over v1 comes from the checklist and the stricter rule: C115 and C040 are no longer false flags. C014 and C061 are still called fixed: their customers asked for an option and the release adds one, while the labels say partial because grouping stays the default. Whether those two labels should be "fixed" is an open question.

**9. Decisions judge (2026-11-27).** Added at Quinton's request as another version of the full agent; see `--judge decisions` above. One design, one run on train and dev, then frozen (no tuning rounds). Run tag `decisions`, no failed calls, about 120,000 input tokens and 0 output tokens for the whole run.

Test 1: train 21 correct, 1 missed (C005), 0 false flags, 2 partial wrong (C014, C061 called fixed); dev perfect. Test 2 (stale / lost): train 0.03 / 0.70, dev 0.00 / 0.33. The miss: it judged R01-03 "not fixed" for C005 with 0.96 confidence, while v2.1 called it fixed and quoted the release. With no written reason, the cause cannot be inspected, and the confidence score did not flag the error. Like v2.1 it never returned partial.

**10. Test split, once per version (2026-11-28).** All versions frozen first. See [Final results](#final-results-test-split).

## Final results (test split)

Run once per version on 2026-11-28, after every version was frozen. Test split: 46 complaints in 10 groups (7 near misses), 32 question and date pairs. No failed calls or pairs.

**Test 1: does each method mark the right complaints outdated?**

| Method | Correct | Wrong release | Missed | False flag | Near-miss false flags | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| area (v1) | 16 | 7 | 0 | 19 | 7 of 7 | 0.38 | 0.70 |
| similarity (v1) | 18 | 0 | 5 | 5 | 4 of 7 | 0.78 | 0.78 |
| llm (v1) | 23 | 0 | 0 | 0 | 0 of 7 | 1.00 | 1.00 |
| hybrid v1 | 23 | 0 | 0 | 0 | 0 of 7 | 1.00 | 1.00 |
| hybrid v2.1 | 23 | 0 | 0 | 0 | 0 of 7 | 1.00 | 1.00 |
| hybrid decisions | 23 | 0 | 0 | 0 | 0 of 7 | 1.00 | 1.00 |

**Test 2: are the answers better?** Rates with counts; 95% confidence intervals for the difference from the baseline come from a paired bootstrap over the 32 pairs (10,000 resamples).

| Agent | Stale answer rate | Lost finding rate | Retrieval recall | Stale vs baseline (95% CI) |
| --- | --- | --- | --- | --- |
| Baseline | 0.32 (27 of 84) | 0.69 (65 of 94) | 0.33 | |
| Hybrid v1 | 0.00 (0 of 80) | 0.69 (65 of 94) | 0.33 | -0.32 [-0.48, -0.20] |
| Hybrid v2.1 | 0.00 (0 of 81) | 0.68 (64 of 94) | 0.33 | -0.32 [-0.49, -0.20] |
| Hybrid decisions | 0.00 (0 of 81) | 0.68 (64 of 94) | 0.33 | -0.32 [-0.49, -0.20] |

What the results show:
- **Research question.** A model's judgment beats product area and text similarity, most clearly on near misses: area flagged all 7, similarity 4, the model-based methods none.
- **Stale answers.** Every full-agent version removed stale answers on test, including before releases and on decoys. The baseline presented an outdated complaint as current about a third of the time.
- **Lost findings are a retrieval limit.** 63 of 64 or 65 lost findings per agent were never retrieved (k=8, one question per topic), and retrieval is identical for both agents. The relevancy check caused no lost findings on test. The lost finding difference from the baseline is within noise (95% CI for v2.1: -0.04 to 0.00).
- **v1 vs v2.1 vs decisions.** They tie on test. The test split has no partial-labeled complaints and none of the fine-print near misses v1 failed on in train and dev (C115, C040), so v2.1's gain there is not confirmed on test. The decisions judge matched v2.1 on test, missed C005 on train with 0.96 confidence, and gives no reasons.
- **Partial status.** No version ever returned partial. C014 and C061 (labeled partial) were called fixed by v2.1 and the decisions judge alike; the labels may be the issue.

## Evaluation

Full spec in `docs/eval_plan.md`.

- **Errors counted:** a **stale answer** (an outdated complaint presented as current) and a **lost finding** (a still-true complaint missed or marked outdated).
- **Answer key:** `eval/labels/complaint_labels.json` gives each complaint a `history` of fixes. A complaint's status at any date is computed from it. Any changelog item can fix a complaint, including items the README calls decoys.
- **Grading is deterministic:** code compares the agent's `cited` block to statuses computed from the labels. No model grades the headline metrics.
- **Isolation:** the agent only ever receives `{question, as_of}`. `tests/test_isolation.py` fails if anything in `src/` references `eval/` or the changelog README.
- **Split:** groups are shuffled with a fixed seed into test (40%, held out), dev (20%), and train (40%) by `python -m eval.make_split`. Tune on dev only; run test once per agent after freezing.

### Test 2: question-level eval

```bash
.venv/bin/python -m eval.make_questions --check                       # validate questions.json against the prompt-2 rules
.venv/bin/python -m eval.harness --agent baseline --split dev
.venv/bin/python -m eval.harness --agent full --method hybrid --split dev
.venv/bin/python -m eval.harness --compare eval/runs/<baseline>.json eval/runs/<full>.json
.venv/bin/python -m eval.harness --agent oracle --split dev            # no API calls; should score 0 stale, 0 lost
```

Questions are generated by code instead of a model run of `eval/prompts/02_questions.md`, using the same coverage table and rules: code picks every `as_of` and target, and the wording is one hand-written question per group (`eval/questions/group_questions.json`). Each lost finding is tagged never retrieved, retrieved but not cited, or cited with the wrong status, so retrieval misses are separated from relevancy-check misses. The test split refuses to run without `--final`.

### Building the answer key

1. ~~Run `eval/prompts/01_complaint_labels.md` to draft labels.~~ Done; drafted by Claude Opus 5.5, which is not either agent's answer model.
2. Review the labels together, starting with `eval/labels/DRAFT_SUMMARY.md`. After any edit, run `python -m eval.validate_labels`.
3. Settle open decisions 1 and 2 above.
4. Run `eval/prompts/02_questions.md` with the reviewed labels and `eval/topic_briefs.json`.
5. Generate and commit `eval/split.json`.

## Data

Both datasets are synthetic and describe **Tessera**, a fictional Notion-like workspace. They share the same product area and platform enums, so they live in one store (164 records). `eval/tessera_changelog_README.md` documents the schema and each changelog item's role: invalidator, partial, decoy, or neutral.
