# Prompt 1: Complaint labels

Generates `eval/labels/complaint_labels.json`. Run this first. Prompt 2 depends on its output.

**Inputs to paste in**
- `{{CHANGELOG_README}}`: full text of `eval/tessera_changelog_README.md` (roles, target findings, chains)
- `{{COMPLAINTS_JSON}}`: full contents of `data/tessera_complaints.json`
- `{{CHANGELOG_JSON}}`: full contents of `data/tessera_changelog.json`

**How to run it**
- Use a strong model that is not either agent's answer model, at temperature 0.
- Save the raw output, then review every label together before committing. The labels become frozen ground truth, so a wrong label here becomes a wrong score for both agents.
- Check the output with code before review: 100 records, valid IDs, every `history` date matches its item's release date and is after the complaint date, entries in date order, nothing after a `full` entry.

---

## Prompt

You are building ground-truth labels for an evaluation of research agents. The product is Tessera, a fictional workspace app. You have three inputs:

1. A README that gives each changelog item a role (invalidator, partial, decoy, or neutral) against one **target finding**, plus chains of related items.
2. 100 customer complaints (C001 to C100), each with a date.
3. 49 changelog items in 20 releases, each with a release date and a full description.

For each complaint, write the history of changelog items that fixed it, fully or partially.

### Any changelog item can resolve a complaint

The README's roles describe each item's effect on its target finding. They say nothing about narrower complaints. **Any item can resolve a complaint, including items the README calls decoy or neutral.** Judge every complaint against every item's description, and use the README as a guide only.

Example: R09-02 "Search filters stay applied on mobile" is a decoy for the search coverage finding, because fixing filters does nothing for coverage. But R09-02 fully resolves C046 ("Search filters reset every time I open a result"). Labeling C046 as never fixed would be wrong.

Known cases, confirmed by the project team (your labels must agree with these):

| Item | README role | Resolves | Does not resolve |
| --- | --- | --- | --- |
| R02-01 Sidebar remembers collapsed sections | Decoy for R16-01 | C008 | |
| R03-02 Faster loading for large databases | Decoy for R03-01 | C007, C013 | C021 (gallery view) |
| R09-02 Search filters stay applied on mobile | Decoy for R08-01 | C046, C049 | |
| R13-01 Invoice PDFs show the correct currency | Decoy for R12-01 | C062, C067 | |
| R20-02 Webhook events delivered once | Decoy for R19-02 | C097 | |
| R01-03 Duplicated pages keep their cover images | Neutral | C002, C005 | C016 (old copies) |

The README is still reliable about target findings in two ways:
- An **invalidator** fully resolves the complaints that express its target finding, and a **partial** item partially resolves them.
- A **decoy** does not resolve the complaints that express the target finding it is a decoy for. It may resolve other, narrower complaints, as in the table above.

### Definitions

- **full:** after this item, the complaint's core problem is no longer true for the customer who raised it.
- **partial:** the item addresses the complaint, but part of the problem is still true. For example, the fix is optional, covers only some platforms or plans, or covers only part of what was asked.
- An item that improves the same area without touching the specific problem is not a fix. Read the complaint's exact problem and the item's caveats ("Good to know", limits, plan or platform restrictions) before deciding.

### Rules

1. Output exactly 100 records, one per complaint, ordered C001 to C100.
2. `history` lists fixes in date order, each `{"item", "date", "resolution"}`. `date` is the item's release date. `resolution` is `full` or `partial`. Use an empty list if nothing fixes the complaint by the last release (2026-10-13).
3. Every fix must be dated strictly after the complaint's date. A complaint filed after an item shipped is about a problem that item did not solve, so that item cannot be in its history.
4. A `partial` entry may be followed by a later `full` entry (for example, a partial fix in August and a full fix later). Nothing comes after a `full` entry.
5. A caveat matters. If the complaint's platform, plan, or specific case falls outside what the item covers, that item does not fix it, or fixes it only partially.
6. `group` is a short lowercase storyline name shared by complaints about the same problem. Use one of these where it fits: sidebar, code blocks and pages, relations, large databases, mobile, calendar, mail, ai trust, ai usage and languages, guests and permissions, recurring templates, search, slack, checkout and billing, slash menu, github, accessibility, api v1, webhooks, ai autofill. Add a new group only if none fits, and list it in your summary.
7. `notes` is one line explaining the decision, quoting the item wording that makes it a fix or the complaint wording that keeps it true. For a complaint in the same area as a decoy that does not fix it, name the decoy and say why.
8. Do not guess. If you are unsure, give your best label and start `notes` with `REVIEW:`.

### Output format

Return a JSON array, then a short summary.

```json
[
  {
    "complaint_id": "C046",
    "group": "search",
    "history": [{"item": "R09-02", "date": "2026-05-05", "resolution": "full"}],
    "notes": "R09-02 keeps search filters applied when returning from a result; the README decoy role applies only to the coverage finding."
  },
  {
    "complaint_id": "C070",
    "group": "checkout and billing",
    "history": [],
    "notes": "Filed after R12-01; no later release adds PayPal."
  }
]
```

The summary must include:
- Counts of complaints whose final entry is `full`, whose final entry is `partial`, and with an empty history
- For every one of the 49 changelog items: the complaints it fixes (full or partial), or "none"
- Every invalidator or partial item whose target-finding complaints you could not find, with an explanation
- Every row in the known-cases table above, confirmed as matching your labels
- All `REVIEW:` complaint IDs
- Any new groups you added

### Inputs

<changelog_readme>
{{CHANGELOG_README}}
</changelog_readme>

<complaints>
{{COMPLAINTS_JSON}}
</complaints>

<changelog>
{{CHANGELOG_JSON}}
</changelog>
