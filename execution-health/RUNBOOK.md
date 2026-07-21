# Execution Health dashboard — refresh runbook

Regenerates the **Execution Health** dashboard for MakAnalytics engineering from
live Jira data and republishes it to the same artifact URL.

- **Artifact URL (keep stable):** https://claude.ai/code/artifact/9628d0fe-b8f1-48f9-9086-70790bbf1558
- **Jira site / cloudId:** `makanalytics.atlassian.net` → `09efcbc5-a5a4-4246-9e23-a0f819ee596f`
- **Projects:** PRC, PP, ES, REV, LEG, MA
- **Connector tool:** `mcp__Atlassian_Rovo__searchJiraIssuesUsingJql`

The Rovo connector returns **no total counts** and caps pages at **100**, so
paginate with `nextPageToken` until `pageInfo.hasNextPage` is `false`, and save
each raw response to `raw/`. Large results are written to disk by the tool
automatically — copy/move them to the `raw/<name>.json` shown below.

**Always pass an explicit `fields` list** (below). The connector's *default* field
set can omit `resolutiondate` — when that happens, resolved counts and lead time
silently zero out. Requesting fields explicitly is safe either way: if the
connector honors the list you get exactly these; if it ignores it, the full payload
still contains them.

## 1. Pull the data

All queries use `cloudId = 09efcbc5-a5a4-4246-9e23-a0f819ee596f`, `maxResults: 100`,
and:
```
fields: ["key","created","resolutiondate","issuetype","status","project","updated","priority"]
```
Sanity-check every history page: it must contain non-null `resolutiondate` on
resolved issues. If build.py prints `resolved=0` or `net8wk` equal to total created,
the field is missing — re-pull with the explicit `fields` list above.

**A. History (flow trend + cycle time)** — one query per project, paginate all pages:
```
project = <P> AND (created >= -56d OR resolutiondate >= -56d) ORDER BY created DESC
```
Save pages to `raw/hist-<P>-1.json`, `raw/hist-<P>-2.json`, … for each of
PRC, PP, ES, REV, LEG, MA.

**B. Work in progress (WIP + aging)** — paginate all pages:
```
project in (PRC,PP,ES,REV,LEG,MA) AND statusCategory = "In Progress" ORDER BY updated ASC
```
Save to `raw/wip-1.json`, `raw/wip-2.json`, …

**C. Open bugs** — paginate all pages:
```
project in (PRC,PP,ES,REV,LEG,MA) AND issuetype = Bug AND resolution = Unresolved ORDER BY created ASC
```
Save to `raw/bugs-1.json`, `raw/bugs-2.json`, …

**D. Sprint issue counts (optional, refreshes section 5)** — one per project that has
an active sprint:
```
project = <P> AND sprint in openSprints()
```
Save to `raw/sprint-<P>.json`. If skipped, sprint issue counts fall back to
`sprints.json`. Sprint **commitment points** (`committed`, `donePts`, `window`,
`daysLeft`) are not reliably derivable from JQL and are maintained by hand in
`sprints.json` — update it when sprints roll over.

## 2. Build
```
python3 execution-health/build.py          # uses today's date
python3 execution-health/build.py --today 2026-07-21   # or pin a date
```
Writes `report_data.json` and `execution-health.html`. Sanity line prints
`net8wk`, `wip`, `bugs`, `hist` counts.

## 3. Republish (same URL)
Publish `execution-health/execution-health.html` with the **Artifact** tool,
passing `url = https://claude.ai/code/artifact/9628d0fe-b8f1-48f9-9086-70790bbf1558`
and `favicon = 📈` so the link and identity stay stable.

If the Artifact tool is unavailable in the session, fall back to committing the
built outputs to the branch and pushing, then report that. Note these are
git-ignored, so **force-add**:
```
git add -f execution-health/report_data.json execution-health/execution-health.html
git commit -m "Execution Health data refresh $(date +%F)" && git push
```

## Notes
- `raw/`, `report_data.json`, and `execution-health.html` are generated — git-ignored.
- Flow is measured in **issue counts** (estimation is inconsistent across projects).
- "Cycle time" is **lead time** (created → resolved); true in-progress cycle time needs
  status-transition history (changelog), not yet captured.
