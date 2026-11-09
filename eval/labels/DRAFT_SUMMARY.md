# Complaint labels: draft summary

Draft of `complaint_labels.json` from `eval/prompts/01_complaint_labels.md`, 2026-11-04. Drafted by Claude Opus 5.5 in Claude Code (not either agent's answer model). **Status: awaiting review by Quinton and Sanjali.** Re-check after any edit with `python -m eval.validate_labels`.

## Counts

| Final status after the last release (2026-10-13) | Complaints |
| --- | --- |
| Fully fixed | 58 |
| Partially fixed | 2 (C014, C061, both by R16-01) |
| Never fixed (empty history) | 55 (40 original, plus C101 to C115) |

No complaint has more than one fix, so there are no partial-then-full chains.

## Known cases

All six rows of the known-cases table match: R02-01 fixes C008; R03-02 fixes C007 and C013 and not C021; R09-02 fixes C046 and C049; R13-01 fixes C062 and C067; R20-02 fixes C097; R01-03 fixes C002 and C005 and not C016. All 16 statuses in the PRD seed table also match.

## Items that fix no complaint

| Item | README role | Why |
| --- | --- | --- |
| R01-01 Redesigned sidebar | Invalidator | No complaint before 2026-01-13 says the flat sidebar list is hard to scan. The sidebar complaints (C008, C014, C061) all come after the redesign. |
| R10-04 API v1 page endpoints deprecated | Partial | No complaint before 2026-05-19 is about building on v1 endpoints. |
| R19-01 API v1 page endpoints removed | Invalidator | Same missing finding as R10-04. C095 is a breakage caused by the removal, not a complaint it fixes. |

These three cannot produce before and after pairs from complaints alone. Options: drop them from coverage, or add complaints (or research passages) that express their target findings.

## Decoys and neutrals that fix complaints

Every one of the 18 decoys and all 5 neutrals fix at least one narrow complaint. The five neutrals: R01-03 (C002, C005), R02-02 (C006), R04-01 (C015), R14-02 (C071), R17-02 (C086).

## Needs a decision before Prompt 2: cross-group decoys

The plan scores both halves of a decoy test in one pair, but `relevant_complaints` is computed from the pair's group only. For four decoys, the narrow complaint lives in a different group from the target finding, so one half would be scored as off-topic:

| Decoy | Target finding group | Narrow complaint and its group |
| --- | --- | --- |
| R01-02 code block languages | slash menu | C001, C004 in code blocks and pages |
| R03-02 large database speed | relations | C007, C013 in large databases |
| R06-02 AI languages | ai trust | C024 in ai usage and languages |
| R19-03 faster AI answers | ai trust | C092, placed in ai trust to avoid this (see REVIEW) |

Options: (a) score each half under its own group, with two pairs per cross-group decoy; (b) compute `relevant_complaints` from the union of groups in `target_complaints`; (c) merge the groups.

## REVIEW

- **C045** "Ctrl+P doesn't print anymore": filed two days after R08-02, which already offers Cmd/Ctrl+Shift+P and a setting to change the shortcut. By rule 3 it stays current, but the customer's problem was arguably already solved.
- **C092** "AI takes 8+ seconds": the fix (R19-03) is clear. The question is the group. It is placed in ai trust so the R19-03 decoy pair can test both halves. Alternatively, start an ai performance group.
- **C095** "410 errors": caused by R19-01, filed the next day. Labeled current (nothing restores v1).

## Lower-confidence calls worth a glance

- **C014, C061:** partial per the README and the PRD seed table, though R16-01 gives exactly the option C014 asked for.
- **C004:** full, though R01-02 says existing Plain Text blocks must be switched by hand.
- **C071:** full, assuming the tablet is 8 inches or larger (R14-02's threshold).
- **C059:** full; R12-01 supports Apple Pay on mobile for Free users upgrading.

## New groups

Three groups were added beyond the suggested list, with briefs in `eval/topic_briefs.json`:
- **desktop apps:** C006, C023, C050 (desktop crashes and memory)
- **security and sign-in:** C015, C058
- **microsoft teams:** C033

Groups with a single complaint (api v1, microsoft teams, slash menu) are small for the split. Consider merging them, such as api v1 into webhooks as "api".

## Added near misses (2026-11-09)

C101 to C115 were added so the relevancy check meets near misses. Before this, all but one near miss (C073) was dated after the release it resembles, and the check only compares a release with complaints dated before it. Each new complaint is dated before a release in the same area that does not fix it, and no later release fixes it either, so every history is empty.

| Complaint | Near miss for | Why the release does not fix it | Stopped by hybrid gate? |
| --- | --- | --- | --- |
| C101 | R02-02 | Windows only; complaint is Mac | platform |
| C102 | R03-02 | Gallery view excluded | no |
| C103 | R05-02 | Android only; complaint is iOS | platform |
| C104 | R06-02 | Hebrew not among the new languages | no |
| C105 | R08-01 | PowerPoint not indexed (PDF and Word only) | no |
| C106 | R10-01 | Offline on iOS and Android only; complaint is Mac | platform |
| C107 | R11-01 | Booking links are Plus and above; complaint is Free | plan |
| C108 | R12-01 | No invoice or bank transfer payment | no |
| C109 | R13-01 | Currency fix only; no invoice language | no |
| C110 | R14-01 | Launch speed only; complaint is scrolling | no |
| C111 | R16-01 | Compact sidebar on web, Mac, Windows; complaint is iOS | platform |
| C112 | R16-03 | Business only; complaint is Plus | plan |
| C113 | R17-01 | Gallery view deferred | no |
| C114 | R19-02 | Webhooks cover rows, not comments | no |
| C115 | R20-01 | Autofill covers text and select properties, not person | no |

`data/store.json` must be re-embedded (`python -m src ingest`) before these appear in retrieval or the relevancy check.
