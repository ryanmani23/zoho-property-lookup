# Daily Delivery Dashboard — methodology

A self-contained HTML artifact summarizing yesterday's Jira delivery across six
active MakAnalytics projects. Refreshed every morning by a scheduled routine and
published as a Claude artifact.

- **Artifact URL (stable):** https://claude.ai/code/artifact/63e114c4-7fd5-4142-b2e9-8530a1662f4e
- **Source file:** `tools/delivery-dashboard/dashboard.html` (this dir) — a
  self-contained page; all data lives in the `const` arrays inside its `<script>`.
- **Projects covered:** ES, PP, PRC, REV, LEG, MA.

## How the daily refresh works

A routine fires at 07:00 America/Chicago, runs in a **fresh session** (so it
never accumulates context), and:

1. Reads this file (`dashboard.html`) for structure + render code.
2. Pulls **yesterday's** Jira activity and **current** sprint state.
3. Overwrites the data constants + header date.
4. Republishes to the stable artifact URL (`Artifact` tool, `url` param).

Structural/design changes are made in interactive sessions and committed here;
the daily routine only overwrites data, so it does not need to commit back.

## Jira connection

- **cloudId:** `09efcbc5-a5a4-4246-9e23-a0f819ee596f`
- **Fields:** Story Points = `customfield_10033` (fallback `customfield_10016`);
  Sprint = `customfield_10020`; parent link = issue `parent.key`;
  Epic Link = `customfield_10014`.
- `searchJiraIssuesUsingJql` returns large payloads to a file — process with
  jq/python, paginate via `nextPageToken` until `pageInfo.hasNextPage` is false,
  and combine **all** pages before computing (a by-project count bug came from
  using only the first 100-row page).

## Sprint Health — story-level rollup (validated against the Jira board)

- Derive **current active sprints each run** via JQL `sprint in openSprints()` —
  never reuse sprint ids (sprints roll over; quiet-but-open sprints must still
  appear).
- **Exclude `WON'T DO`/cancelled** items entirely.
- The **done / in-progress / to-do bar counts PARENT work items only** (exclude
  `Sub-task`), by statusCategory (`new`=to-do, `indeterminate`=in-progress,
  `done`=done).
- **Committed points = per parent, `max(parent's own points, sum of its
sub-tasks' points)`** — use the parent estimate when it has one; fold in
  sub-task points only when the parent is unestimated. Add points of any orphan
  sub-task whose parent isn't in the sprint. This avoids double-counting teams
  that point both levels (PRC) while capturing teams that estimate bottom-up
  (PP). **Done points** = same rollup restricted to done parents.
- Numbers may differ slightly from Jira's board where a team estimates on
  sub-tasks (e.g. PP reads ~1.5 pts above the board). That divergence is
  intended.
- Show each sprint's sub-task count as `+N sub-tasks (nested)`.

## Throughput — per-day (separate from sprint health)

"Shipped yesterday", points closed, top movers, shipped-by-project:

- **Count completed sub-tasks** as work shipped (tag them `↳ sub-task`).
- **Drop `WON'T DO`/cancelled** — never counts as shipped anywhere.
- Shipped = `resolutiondate` within `[yesterday, today)`;
  Opened = `created` within the same window;
  window is America/Chicago.

## Render notes

- Keep the design, favicon 📊, title, the "story-level rollup" sprint note,
  the `↳ sub-task` chips, and the reconciliation note.
- Issue keys link to `https://makanalytics.atlassian.net/browse/<KEY>`.
- Empty-state handling exists for zero-activity days (weekends).
