# Prompt 2: Questions

Generates `eval/questions/questions.json`. Run this only after `eval/labels/complaint_labels.json` has been reviewed and committed.

**Inputs to paste in**
- `{{CHANGELOG_README}}`: full text of `eval/tessera_changelog_README.md`
- `{{COMPLAINT_LABELS_JSON}}`: the reviewed `eval/labels/complaint_labels.json`
- `{{TOPIC_BRIEFS}}`: `eval/topic_briefs.json`
- `{{COMPLAINT_INDEX}}`: one line per complaint: `complaint_id, date, group`. No titles or text.
- `{{CHANGELOG_INDEX}}`: one line per item: `item_id, release_date, product_area, title`. No descriptions.

Complaint text is left out on purpose. Questions must be written from the topic, so the model writing them never sees complaint wording it could copy.

**What code does, not this prompt.** `relevant_complaints` is not stored. The harness computes it as every complaint in the pair's group dated on or before `as_of`, and gets expected statuses from the label file at that date. This prompt only chooses questions, dates, and what each pair is testing.

**How to run it**
- Same model and settings as Prompt 1, at temperature 0.
- Check the output with code before review: every `as_of` is 3 or more days from any release in its group, before and after pairs share wording, every invalidator, decoy, and partial item is covered, and each `target_complaints` status at `as_of` matches what the `type` claims.

---

## Prompt

You are writing evaluation questions for research agents. The agents answer questions about Tessera, a fictional workspace app, from a store of customer complaints and changelog items. Each question is asked "as of" a date, and the agent only sees records dated on or before it.

Each pair tests whether the agent knows which complaints are still true at that date. You are given each changelog item's role (README), reviewed complaint labels with fix histories, a topic brief per group, and dates.

### Computing a complaint's status at a date

Use this to choose dates and check your pairs. Code recomputes it later.
- Complaint dated after `as_of`: not visible to the agent
- No `history` entry dated on or before `as_of`: **current**
- Otherwise take the latest such entry: `full` gives **outdated**, `partial` gives **partial**

### What to produce

One record per (question, as_of) pair, following this coverage:

| README role | Pairs per item | type | as_of rule | target_complaints |
| --- | --- | --- | --- | --- |
| Invalidator | 2 | `invalidator_before`, `invalidator_after` | Before: after the latest target complaint's date and before the release. After: after the release and before the next release that changes any target complaint's status. | Complaints whose history includes this item. Same list for both pairs. |
| Decoy | 1 | `decoy` | After the decoy's release and before the next release that changes any target complaint's status. | Both halves: the complaints expressing the README target finding (status must not change because of the decoy), plus any complaints the decoy itself fixes (status must change). |
| Partial | 1 | `partial` | After the release and before any later fix to its target complaints. | Complaints with a `partial` entry for this item. |
| Neutral | 0 | none | Skip, unless the labels show it fixes a complaint. Then treat it like a decoy with an empty target finding half, and say so in `notes`. | |

Add one `still_true` pair for each group with complaints whose history is empty, with `as_of` 2026-10-31. Its `target_complaints` are those complaints.

### Rules

1. **Before and after pairs use identical question wording.** Only `as_of` differs, so time is the only variable.
2. **Write from the topic brief, as a researcher would ask.** Write open questions such as "What problems do people have with search?". Never copy or paraphrase a specific complaint, and never name a fix, feature, or release.
3. **Questions must not reveal the answer.** Avoid words like "still", "anymore", "after the update", "now that", or "recently".
4. **Date spacing.** Every `as_of` sits at least 3 days from any release in its group. A release is in a group if it contains the pair's `target_item` or any item in the history of a complaint in that group. This keeps an off-by-one date bug from flipping a result.
5. **Visibility.** Every complaint in `target_complaints` must be dated on or before `as_of`.
6. **Merge overlaps.** If two items would produce the same question and the same `as_of`, write one record. Set `target_item` to the invalidator over the decoy, combine `target_complaints`, and list the other item in `notes`.
7. **Verify each pair.** Using the status rule above, `invalidator_before` targets must be current, `invalidator_after` targets outdated, and `partial` targets partial. For `decoy`, the target-finding half keeps the status it had just before the decoy, and the decoy's own complaints are outdated or partial. If a pair cannot satisfy this, leave it out and explain in the summary.
8. Number pairs Q001 upward, ordered by group, then `as_of`.

### Output format

Return a JSON array, then a short summary.

```json
[
  {
    "question_id": "Q001",
    "question": "What do we know about checkout?",
    "as_of": "2026-05-25",
    "group": "checkout and billing",
    "type": "invalidator_before",
    "target_item": "R12-01",
    "target_complaints": ["C054"],
    "notes": ""
  },
  {
    "question_id": "Q002",
    "question": "What do we know about checkout?",
    "as_of": "2026-07-01",
    "group": "checkout and billing",
    "type": "invalidator_after",
    "target_item": "R12-01",
    "target_complaints": ["C054"],
    "notes": ""
  }
]
```

The summary must include:
- Pair counts by `type` and by `group`
- Every invalidator, decoy, and partial item in the README, with the question_ids that test it (none may be missing)
- Every merge you made
- Every item left out under rule 7, and why

### Inputs

<changelog_readme>
{{CHANGELOG_README}}
</changelog_readme>

<complaint_labels>
{{COMPLAINT_LABELS_JSON}}
</complaint_labels>

<topic_briefs>
{{TOPIC_BRIEFS}}
</topic_briefs>

<complaint_index>
{{COMPLAINT_INDEX}}
</complaint_index>

<changelog_index>
{{CHANGELOG_INDEX}}
</changelog_index>
