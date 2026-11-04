# Eval Plan

2026-11-04 · Quinton King, Sanjali Roy

## Purpose

Measure how often each agent presents an outdated finding as current (stale answer) or drops a still-true finding (lost finding), and compare the baseline against the full agent on the same questions. The eval must be reproducible, cheap to rerun, and isolated from the agent so the agent never sees ground truth.

## Isolation rules

The agent may see:
- The two corpus files: `tessera_complaints.json` and `tessera_changelog.json`
- For each query, only the `question` text and the `as_of` date

The agent may never see:
- `tessera_changelog_README.md` (its role table is an answer key)
- Anything under `eval/`: labels, question metadata, expected answers, split assignments, scores

How this is enforced:
1. Agent code lives in `src/` and never imports or opens anything under `eval/`.
2. The harness reads a question record, strips it to `{question, as_of}`, and passes only that to the agent.
3. The `as_of` filter is applied inside the agent's retrieval, so nothing dated after `as_of` reaches the model.
4. A test fails the run if any file in `src/` references the `eval/` path or the README filename.

## Ground truth

### Complaint labels (defined once)

`eval/labels/complaint_labels.json`, one record per complaint:

| Field | Meaning |
| --- | --- |
| complaint_id | C001 to C100 |
| group | Topic or chain the complaint belongs to (see Groups) |
| history | List of fixes in date order, each `{item, date, resolution}` where resolution is `full` or `partial`. Empty if never fixed. |
| notes | One line on why, for review. Uncertain labels start with `REVIEW:` |

Status of a complaint at any `as_of` date is computed by code, never hand-written:
- Complaint dated after `as_of`: not in scope (the agent cannot see it)
- No `history` entry dated on or before `as_of`: **current**
- Otherwise take the latest such entry: `full` gives **outdated**, `partial` gives **partial**

A fix must be dated after the complaint it resolves.

### Which items can resolve a complaint

**Any** changelog item can resolve a complaint, including items the README calls decoy or neutral. The README's roles describe each item's effect on its **target finding**, and say nothing about narrower complaints.

Example: R09-02 is a decoy for the search coverage finding, because fixing mobile filters does nothing for coverage. But R09-02 fully resolves C046 ("Search filters reset every time I open a result"). Labeling C046 as never fixed would be wrong.

The complaints dataset was written so that most items resolve something. Examples from the README's decoys and neutrals:

| Item | README role | Resolves |
| --- | --- | --- |
| R02-01 Sidebar remembers collapsed sections | Decoy for R16-01 | C008 |
| R03-02 Faster loading for large databases | Decoy for R03-01 | C007, C013 (not C021, gallery view) |
| R09-02 Search filters stay applied on mobile | Decoy for R08-01 | C046, C049 |
| R13-01 Invoice PDFs show the correct currency | Decoy for R12-01 | C062, C067 |
| R20-02 Webhook events delivered once | Decoy for R19-02 | C097 |
| R01-03 Duplicated pages keep their cover images | Neutral | C002, C005 (not C016, old copies) |

So a decoy test has two halves: the decoy should outdate its own narrow complaint, and should leave the target finding's complaints unchanged. Both are scored.

### Questions

`eval/questions/questions.json`, one record per (question, as_of) pair:

| Field | Sent to agent | Meaning |
| --- | --- | --- |
| question_id | no | Q001, Q002, ... |
| question | **yes** | Researcher-style question, written from the topic, not copied from complaint text |
| as_of | **yes** | Date the question is asked |
| group | no | Used for the split |
| type | no | `invalidator_before`, `invalidator_after`, `decoy`, `partial`, `still_true` |
| target_item | no | The changelog item this pair tests |
| target_complaints | no | Complaint IDs the pair is specifically testing (for reporting by type) |

`relevant_complaints` is not stored. Code computes it as every complaint in the pair's group dated on or before `as_of`, and expected statuses come from the label file at that date. Nothing about the expected answer is written by hand per question.

Every `as_of` sits at least 3 days from any release in its group, so an off-by-one date bug cannot flip a result.

### Coverage

| Changelog role | Count | Pairs per item | What it tests |
| --- | --- | --- | --- |
| Invalidator | 24 | 2: one `as_of` before the release, one after | Status should flip from current to outdated |
| Decoy | 18 | 1: `as_of` after the decoy, before any real fix in that area | Target finding's complaints should not flip; the decoy's own narrow complaint should |
| Partial | 2 | 1: `as_of` after the release | Status should be partial |
| Neutral | 5 | 0 | Skipped; no finding affected |

Roughly 60 to 70 pairs after merging overlaps (for example, a decoy and an invalidator that share a question and date). Before and after pairs reuse identical question wording so time is the only variable.

## Groups and split

Pairs are split by **group**, not individually, so pairs that share a storyline stay on the same side.

Groups follow the README chains and product areas: sidebar, code blocks and pages, relations, large databases, mobile, calendar, mail, AI trust, AI usage and languages, guests and permissions, recurring templates, search, Slack, checkout and billing, slash menu, GitHub, accessibility, API v1, webhooks, AI autofill. Final list is set when labels are written.

Split procedure (`eval/make_split.py`):
1. Read all groups from `questions.json`.
2. Shuffle groups with a fixed seed from `eval/config.json`.
3. Assign groups to dev until dev holds about 40% of pairs; the rest go to test.
4. Write `eval/split.json` with the seed, the group assignments, and pair counts.

The seed is recorded in every run log. The split is generated once and committed; regenerating it requires a new seed and a note explaining why.

## Agent output contract

Both agents return the prose answer plus a structured block:

```json
{
  "answer": "prose answer for the researcher",
  "cited": [
    {"id": "C054", "status": "outdated", "outdated_by": "R12-01"},
    {"id": "C070", "status": "current"}
  ]
}
```

- `status` is one of `current`, `outdated`, `partial`.
- The baseline has no status concept. Everything it cites is scored as `current`.
- Changelog IDs can be cited as evidence but are not scored for status.

## Scoring

Mechanical scoring compares each cited complaint against its expected status at `as_of`.

| Expected \ Agent says | current | partial | outdated | not cited |
| --- | --- | --- | --- | --- |
| current | correct | lost finding | lost finding | lost finding |
| partial | stale answer | correct | lost finding | lost finding |
| outdated | stale answer | stale answer | correct | ignored |

Notes:
- An outdated complaint left out is fine; omitting dead findings is acceptable behavior.
- A complaint the agent cites that is not in `relevant_complaints` is logged as off-topic and not scored.

Metrics reported per agent, per split, and per question type:
- **Stale answer rate:** stale answers / relevant complaints expected as outdated or partial
- **Lost finding rate:** lost findings / relevant complaints expected as current or partial
- **Retrieval recall@k:** relevant complaints in the top k / relevant complaints in scope
- **Status confusion matrix** (the table above, with counts)

Retrieval recall separates "never retrieved" from "retrieved but mislabeled," which tells you whether a failure is in retrieval or in the relevancy check.

## Determinism

All headline metrics come from mechanical scoring of the `cited` block against the frozen label file. Same inputs, same score, every run. No model is involved in grading.

The answer key is drafted once (by prompt or by hand), reviewed, and committed. After that it is static data.

**Optional diagnostic, not a headline metric:** an LLM check that the prose agrees with the `cited` block (for example, the JSON marks C054 outdated but the prose still says checkout is confusing). It runs in a separate call, never shares context with the agent, and is reported apart from the main scores. Skip it unless prose and JSON disagreements show up in dev.

## Harness flow

1. Load `questions.json`, `split.json`, and `complaint_labels.json`.
2. Select pairs for the requested split (`dev` or `test`).
3. For each pair, send `{question, as_of}` to the agent.
4. Validate the structured block; malformed output counts as a failed pair and is logged.
5. Score mechanically (and run the optional prose check if enabled).
6. Write a run file to `eval/runs/` with agent name, model names, seed, split, per-pair results, and summary metrics.

## Workflow

1. Write `complaint_labels.json` from the README and the two datasets; review together.
2. Write `questions.json`: questions from topic briefs, `relevant_complaints` from the labels.
3. Generate and commit `split.json`.
4. Build and tune both agents against **dev** only, as often as needed.
5. Freeze both agents (record commit hash and settings).
6. Run **test** once per agent and report.

## File layout

```
src/                         agent code (never touches eval/)
data/
  tessera_complaints.json
  tessera_changelog.json
eval/
  tessera_changelog_README.md
  config.json                seed, dev ratio, k, model names
  labels/complaint_labels.json
  questions/questions.json
  split.json
  make_split.py
  harness.py
  scoring.py
  judge.py                   optional prose check
  prompts/
    01_complaint_labels.md
    02_questions.md
  topic_briefs.json
  runs/
```

