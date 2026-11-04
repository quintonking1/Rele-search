# Tessera Changelog Dataset

Synthetic release notes for **Tessera**, a fictional Notion-like workspace (notes, docs, databases, calendar, mail). Built for a continual learning research agent that decides whether a research finding is still current after a product change.

- `tessera_changelog.json`: the dataset (20 releases, 49 items, January 13 to October 13, 2026)
- `tessera_changelog.md`: the same content as a readable changelog, newest first

Releases ship roughly every two weeks: minor versions (3.1, 3.2, ...) carry headline features, and patch versions (3.1.1, 3.1.2, ...) carry smaller features and fixes. Item descriptions average 119 words (range 74 to 166) and follow a consistent structure: context, what's new, how it works, and caveats.

## Schema

**Release level (one per update)**

| Field | Type | Example |
|---|---|---|
| release_id | string | `R12` |
| version | string | `3.5` or `3.5.1` |
| release_date | ISO date | `2026-06-16` |
| release_title | string | "A simpler way to upgrade" |
| release_summary | string | one or two sentences |

**Item level (one per change inside a release)**

| Field | Type | Allowed values |
|---|---|---|
| item_id | string | `R12-01` |
| release_id | string | links to parent release |
| title | string | short name of the change |
| description | markdown | full changelog text |
| change_type | enum | new feature, improvement, bug fix, performance, security, deprecation, breaking change |
| product_area | enum | editor/pages, databases, AI, search, sharing and permissions, calendar, mail, API, integrations, mobile, billing and plans |
| platforms | list | web, Mac, Windows, iOS, Android, API |
| plan_availability | list | Free, Plus, Business, Enterprise |
| audience | list | end user, workspace admin, developer |

`billing and plans` was added to the product area list so the checkout scenario from the project deck has a home.

## Evaluation hooks

Each item was written to play one of four roles against the relevancy check. Use the target findings to write research passages dated **before** the item's release date, and the dataset gives you a known right answer.

- **Invalidator** (24): the change makes a prior finding outdated
- **Partial** (2): the change weakens or complicates a finding without fully replacing it
- **Decoy** (18): same product area as an invalidator, but the finding's status should not change. This is the "shares an area but still true" risk from the deck.
- **Neutral** (5): no likely research finding is affected

| Item | Date | Role | Target finding |
|---|---|---|---|
| R01-01 Redesigned sidebar | 2026-01-13 | Invalidator | Users struggle to find pages in a long flat sidebar list |
| R01-02 12 new code block languages | 2026-01-13 | Decoy for R12-02 | (slash menu finding still holds) |
| R01-03 Duplicated pages keep their cover images | 2026-01-13 | Neutral |  |
| R02-01 Sidebar remembers collapsed sections | 2026-01-27 | Decoy for R16-01 | (the post-redesign finding that users miss the flat list still holds) |
| R02-02 Windows app no longer crashes on large pastes | 2026-01-27 | Neutral |  |
| R03-01 Guided relation builder | 2026-02-10 | Invalidator | Users find relations confusing and give up setting them up |
| R03-02 Faster loading for large databases | 2026-02-10 | Decoy for R03-01 | (relation finding still holds) |
| R03-03 Board view drag and drop on iOS | 2026-02-10 | Decoy for R10-01 | (offline finding still holds) |
| R04-01 Shorter session expiry for SSO workspaces | 2026-02-24 | Neutral |  |
| R04-02 All-day events no longer shift across timezones | 2026-02-24 | Decoy for R12-03 | (calendar deadlines finding still holds) |
| R05-01 Threaded conversations in Tessera Mail | 2026-03-03 | Invalidator | Mail users lose track of replies because related messages aren't grouped together |
| R05-02 New mail arrives faster on Android | 2026-03-03 | Decoy for R05-01 | (threading finding still holds) |
| R06-01 AI answers cite their sources | 2026-03-17 | Invalidator | Users don't trust AI answers because they can't verify where they came from |
| R06-02 Tessera AI in six more languages | 2026-03-17 | Decoy for R06-01 | (trust finding still holds) |
| R06-03 Guest access audit | 2026-03-17 | Invalidator | Admins can't tell which guests have access to what |
| R07-01 Repeating database templates | 2026-03-31 | Invalidator | Users recreate the same recurring pages (weekly syncs, reports) by hand every time |
| R07-02 AI usage dashboard for admins | 2026-03-31 | Invalidator | Admins can't see how much, or how, their workspace uses AI |
| R08-01 Rebuilt search with filters | 2026-04-21 | Invalidator | Search misses content inside databases, comments, and attachments |
| R08-02 Open search with Cmd/Ctrl + P | 2026-04-21 | Decoy for R08-01 | (search coverage finding: tests whether a search-area shortcut is mistaken for a coverage fix) |
| R08-03 Slack notification digests | 2026-04-21 | Invalidator | Slack notifications from Tessera are too noisy |
| R09-01 Permissions preview when moving pages | 2026-05-05 | Invalidator | Users accidentally expose private pages when moving them into shared teamspaces |
| R09-02 Search filters stay applied on mobile | 2026-05-05 | Decoy for R08-01 | (search coverage finding stays outdated) |
| R10-01 Offline pages on iOS and Android | 2026-05-19 | Invalidator | Mobile users can't open pages without a connection |
| R10-02 Recent pages home screen widget | 2026-05-19 | Decoy for R10-01 | (offline finding: same release, same area, different change) |
| R10-03 Dark mode icons render correctly | 2026-05-19 | Decoy for R10-01 | (offline finding: same release, same area, different change) |
| R10-04 API v1 page endpoints deprecated | 2026-05-19 | Partial | Developers build integrations on the v1 page endpoints (still works, but now on notice) |
| R11-01 Booking links in Tessera Calendar | 2026-06-02 | Invalidator | Users leave Tessera for other tools to share availability with external people |
| R11-02 FAQ on the plan comparison page | 2026-06-02 | Decoy for R12-01 | (two weeks before the checkout redesign: checkout finding still holds) |
| R12-01 Redesigned checkout | 2026-06-16 | Invalidator | Checkout is confusing; users abandon at plan comparison (the deck scenario) |
| R12-02 Reorganized slash menu | 2026-06-16 | Invalidator | The slash menu is overwhelming and blocks are hard to discover |
| R12-03 Database dates on your calendar | 2026-06-16 | Invalidator | Users want task deadlines to show up on their calendar |
| R13-01 Invoice PDFs show the correct currency | 2026-07-07 | Decoy for R12-01 | (checkout finding stays outdated; this item should change nothing) |
| R13-02 Relation builder no longer crashes on archived databases | 2026-07-07 | Decoy for R03-01 | (relation finding stays outdated) |
| R14-01 Mobile apps open up to 2x faster | 2026-07-21 | Invalidator | The mobile app is slow to open, so users reach for other notes apps instead |
| R14-02 Android tablet layout | 2026-07-21 | Neutral |  |
| R15-01 Two-way GitHub issue sync | 2026-08-04 | Invalidator | Engineering teams duplicate task tracking between GitHub and Tessera |
| R15-02 Daily Slack digests respect your timezone | 2026-08-04 | Decoy for R08-03 | (Slack noise finding stays outdated) |
| R16-01 Compact sidebar layout | 2026-08-18 | Partial | Users miss the old flat page list (written after January); now optional, so only half resolved |
| R16-02 Auto-labels in Tessera Mail | 2026-08-18 | Invalidator | The mail inbox is cluttered with newsletters and notifications |
| R16-03 Upgrade prompts limited to admins in Business workspaces | 2026-08-18 | Invalidator | Business members are annoyed by upgrade prompts (same area as checkout, different finding) |
| R17-01 Keyboard and screen reader support in databases | 2026-09-01 | Invalidator | Keyboard and screen reader users can't navigate database views |
| R17-02 High-contrast theme | 2026-09-01 | Neutral |  |
| R18-01 Downgrades and seat changes in checkout | 2026-09-15 | Invalidator | Users like the new checkout but can't figure out how to downgrade or remove seats (written after June 16) |
| R18-02 Apple Pay works with more European cards | 2026-09-15 | Decoy for R18-01 | (downgrade finding: same release, same area, different change) |
| R19-01 API v1 page endpoints removed | 2026-09-29 | Invalidator | Same developer finding as R10-04, now fully outdated |
| R19-02 Database webhooks | 2026-09-29 | Invalidator | Developers have to poll the API repeatedly to detect database changes |
| R19-03 Faster AI answers on large workspaces | 2026-09-29 | Decoy for R06-01 | (trust finding stays outdated) |
| R20-01 AI autofill for database properties | 2026-10-13 | Invalidator | Users spend a lot of time manually tagging and categorizing database rows |
| R20-02 Webhook events delivered once | 2026-10-13 | Decoy for R19-02 | (webhook finding stays outdated) |

### Chains worth testing

- **Sidebar (R01-01 → R02-01 → R16-01)**: a finding outdated in January spawns a new finding ("users miss the flat list"), which survives a sidebar bug fix and is then only partially resolved in August.
- **API (R10-04 → R19-01)**: deprecation then removal. Tests whether "on notice" is treated differently from "outdated".
- **Billing (R11-02 → R12-01 → R13-01 → R16-03 → R18-01 → R18-02)**: six items in one area. A billing tweak two weeks before the checkout redesign should not outdate the checkout finding, the redesign should, a later invoice fix should change nothing, and two later items each resolve a different, newer finding. Topic matching alone will get most of these wrong.
- **Webhooks (R19-02 → R20-02)**: a new capability followed by a fix to it. The fix should not revive the polling finding.
- **Search (R08-01, R08-02, R09-02)**: a shortcut change in the same release as the real fix, then a mobile filter fix afterward.