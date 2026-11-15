# Relevancy check eval: original complaints vs. near misses

**Run tag:** `nearmiss-rerun-2026-11-15` (2026-11-15, UTC)
**Status:** 2 of 4 methods complete. `llm` and `hybrid` are **incomplete** and will be rerun once the Gemini daily quota resets.

This scores each relevancy method's status log against `eval/labels/complaint_labels.json`. It checks whether each method marked the right complaints outdated by the right release, before any question is asked. The labels are still a draft and there is no dev/test split yet, so treat these as development numbers.

Reproduce:

```bash
.venv/bin/python -m eval.score_relevancy --tag nearmiss-rerun-2026-11-15 --show-errors
```

## Setup

- **Store:** re-embedded with `python -m src ingest` so C101 to C115 have vectors (164 records, `gemini-embedding-2`, 768d). Scores on C001 to C100 are identical to the 2026-11-09 run, so re-embedding did not shift the original results.
- **Methods:** `area` (same product area), `similarity` (cosine >= 0.80), `llm` (model judges the 10 most similar earlier complaints per release), `hybrid` (platform and plan gates, then the llm step).
- **Subsets:** *original* is C001 to C100 (100 complaints). *Near miss* is C101 to C115 (15 complaints), each dated before a release in the same area that does not fix it. All 15 are labeled never fixed.
- **Logs:** status logs are now append-only. This run is one tagged line in `data/status/<method>.jsonl`. The earlier runs in `data/status/area.json` and `similarity.json` are unchanged and load as tag `legacy`.

## Scores

Precision = correct / all flagged. Recall = correct / all labeled fixed (partials excluded). A flag by the wrong release counts against both.

| Method | Status | Original P | Original R | Original F1 | Near-miss false flags | Near-miss P | Near-miss R | Near-miss F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| area | complete | 0.42 | 0.62 | 0.50 | **15 / 15** | 0.00 | n/a | n/a |
| similarity | complete | 0.96 | 0.79 | 0.87 | **6 / 15** | 0.00 | n/a | n/a |
| llm | **incomplete** | | | | | | | |
| hybrid | **incomplete** | | | | | | | |

**How to read the near-miss columns.** Every near miss is labeled never fixed, so the subset has no positives. Recall and F1 have no denominator (n/a), and precision is 0.00 whenever a method flags anything. The informative number is false flags out of 15: lower is better, and 0 is perfect.

All 115 complaints together: area P 0.36, R 0.62, F1 0.46; similarity P 0.85, R 0.79, F1 0.82.

Counts behind the original-set scores:

| Method | Correct | Wrong release | Missed | False flag | Partial | Correctly current |
| --- | --- | --- | --- | --- | --- | --- |
| area | 36 | 22 | 0 | 27 | 2 | 13 |
| similarity | 46 | 1 | 11 | 1 | 2 | 39 |

**Main finding.** The near misses expose the weakness that the original set hid. On C001 to C100, similarity looked almost perfectly precise (1 false flag), because most of the original near misses are dated after their release and are never checked. Once near misses come before a same-area release, similarity wrongly marks 6 of 15 outdated. Area matching marks every one of them outdated.

## Hybrid: metadata gating vs. LLM

**Incomplete.** The hybrid run never started (see Failed API calls). The scorer now reports the breakdown from each hybrid run's log: (release, complaint) pairs rejected by the gates, gated pairs among the top 10 by similarity, pairs sent to the LLM, call count, and failed calls, all split by original and near miss. It will be filled in after tomorrow's run.

What to expect, from the labels and not yet measured: six near misses differ from their release only by platform or plan, so the gates should stop them before any model call (C101, C103, C106, C107, C111, C112). Five of the six similarity false flags are in that list. The sixth, C114, matches its release on both platform and plan, so it will need the LLM's judgment.

## Near-miss complaints wrongly flagged

The first release to flag a complaint is the one recorded as outdating it. Once outdated, a complaint stays outdated, so area often flags a near miss with an earlier, unrelated release in the same area before its target release ships.

| Complaint | Title | Target release (does not fix it) | area flagged by | similarity flagged by |
| --- | --- | --- | --- | --- |
| C101 | Mac app crashes when pasting a big table | R02-02 Windows paste fix | R02-01 | R02-02 (0.830) |
| C102 | Gallery view takes forever on our photo library | R03-02 large database speed | R03-01 | |
| C103 | New mail shows up late on my iPhone | R05-02 Android mail sync | R05-01 | R05-02 (0.816) |
| C104 | Tessera AI answers in English when we ask in Hebrew | R06-02 new AI languages | R06-01 | |
| C105 | Search doesn't find text in attached slide decks | R08-01 rebuilt search | R08-01 | |
| C106 | Desktop app is useless without wifi | R10-01 offline pages on mobile | R12-02 | |
| C107 | Let me share a scheduling link | R11-01 booking links (Plus and up) | R11-01 | R11-01 (0.832) |
| C108 | Can't pay by invoice or bank transfer | R12-01 new checkout | R11-02 | |
| C109 | Invoices only come in English | R13-01 invoice currency fix | R13-01 | |
| C110 | Scrolling big databases on iPhone is choppy | R14-01 faster app launch | R14-01 | |
| C111 | iPhone sidebar is just a stack of teamspace headers | R16-01 compact sidebar (desktop and web) | R16-01 | R16-01 (0.836) |
| C112 | Upgrade popups for people who can't buy anything | R16-03 upgrade prompts (Business only) | R16-03 | R16-03 (0.865) |
| C113 | Gallery view can't be used with a keyboard | R17-01 database keyboard support | R17-01 | |
| C114 | Need webhooks when someone comments | R19-02 database webhooks | R19-01 | R19-02 (0.822) |
| C115 | Let AI assign an owner to new requests | R20-01 AI autofill | R20-01 | |
| | | | **15 flagged** | **6 flagged** |

Similarity flags the near miss with its own target release every time, with scores from 0.816 to 0.865. Raising the threshold enough to clear all six (above 0.865) would also drop true fixes. That trade-off should be tuned on the dev split once it exists.

## Failed API calls

The free tier allows **20 `generate_content` requests per day** for `gemini-3.6-flash` (quota metric `generate_content_free_tier_requests`). The llm method needs 49 calls and hybrid needs another 49. Earlier seed runs and the llm releases up to R09-01 used most of the day's quota. After that, calls failed except R10-01, which went through after retrying.

| Time (UTC) | Method | Release | Complaints it would have judged | Error |
| --- | --- | --- | --- | --- |
| 2026-11-15 23:00:42 | llm | R09-02 | C046, C049, C014, C016, C041, C047, C035, C045, C037, C048 | 429 RESOURCE_EXHAUSTED, daily limit 20 |
| 2026-11-15 23:06:20 | llm | R10-02 | C037, C106, C049, C103, C014, C016, C046, C047, C050, C025 | 429 RESOURCE_EXHAUSTED, daily limit 20 |

Each failed call went through 5 backoff retries (about 2.5 minutes) before it was logged in `data/status/failed_calls.jsonl`. The run was stopped by hand at about 23:10 UTC, a few releases after R10-02. A run is saved only when it finishes, so no llm run was saved to the status log, and the verdicts from the calls that did succeed (R01-01 to R09-01 and R10-01) were discarded. The hybrid run never started.

**For tomorrow:**
- Retrying a daily-quota 429 cannot succeed. The retry code should spot "per day" in the error and stop the run immediately rather than back off on every remaining release. This change is not made yet.
- At 20 requests a day, llm and hybrid together need about 5 days on the free tier. A billing-enabled key, or a second key, would let both finish in one run. Each method also has to finish within a single day's quota, since a run is saved only when it completes.

## Note: C014 and C061 as possible partial fixes

Both are sidebar complaints labeled **partial** by R16-01 (Compact sidebar layout, 2026-08-18). R16-01 adds an optional compact flat list, but teamspace grouping stays the default, so neither complaint is fully resolved.

- **C014** (2026-02-03, web): "Bring back the old flat page list"
- **C061** (2026-06-08, Mac): "Teamspace grouping wastes space in the sidebar"

These are left out of precision and recall above, because the full agent has only two statuses (current and outdated).

- **similarity** flags both with R16-01 (0.866 and 0.872), the right release. Since the agent has no partial status, it presents them as fully fixed.
- **area** flags both with R12-02 (Reorganized slash menu, 2026-06-16), an unrelated earlier release in the same area. That would make them look resolved two months before any sidebar change shipped.

Under the current scoring table, a partial complaint reported as current counts as a stale answer. We still need to decide whether status gets a third "partial" value (open decision 6). If it stays binary, these two cases decide whether "partial" should be scored as current or as outdated.
