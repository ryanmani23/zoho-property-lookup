#!/usr/bin/env python3
"""
Build the Execution Health dashboard from raw Jira JQL responses.

Reads raw/*.json (saved verbatim from the Atlassian connector's
searchJiraIssuesUsingJql results — the tool writes them to disk), aggregates
them into report_data.json, and injects that into template.html to produce
execution-health.html.

Raw file naming (see RUNBOOK.md):
  raw/hist-<PROJ>-<page>.json   issues created OR resolved in the last 56 days
  raw/wip-<page>.json           issues currently statusCategory = "In Progress"
  raw/bugs-<page>.json          open bugs (issuetype=Bug, resolution=Unresolved)
  raw/sprint-<PROJ>.json        issues in openSprints() for a project (optional)

Sprint commitment points are not reliably reconstructable from JQL (estimation
is inconsistent across projects), so committed/donePts come from sprints.json,
a small hand-maintained file; issue counts (done/prog/todo) are refreshed from
raw/sprint-*.json when present.

Usage:  python3 build.py [--today YYYY-MM-DD]
"""
import json, glob, os, sys, datetime, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "raw")
PROJS = ["PRC", "PP", "ES", "REV", "LEG", "MA"]

def arg_today():
    if "--today" in sys.argv:
        return datetime.date.fromisoformat(sys.argv[sys.argv.index("--today") + 1])
    return datetime.date.today()

TODAY = arg_today()

def d(s):
    return datetime.date.fromisoformat(s[:10]) if s else None

def wkstart(x):
    return x - datetime.timedelta(days=x.weekday())

WEEKS = [(wkstart(TODAY) - datetime.timedelta(weeks=i)).isoformat() for i in range(7, -1, -1)]

def wbucket(x):
    if not x:
        return None
    w = wkstart(x).isoformat()
    return w if w in WEEKS else None

def load_nodes(pattern):
    """Load + dedupe issue nodes across every file matching a glob prefix."""
    issues = {}
    for f in sorted(glob.glob(os.path.join(RAW, pattern))):
        js = json.load(open(f))
        for n in js.get("issues", {}).get("nodes", []):
            issues[n["key"]] = n["fields"]
    return issues

def pct(lst, q):
    s = sorted(lst)
    return s[min(len(s) - 1, int(q * len(s)))] if s else None

# ---- flow + cycle time (history) ----
hist = load_nodes("hist-*.json")
cre = {w: {p: 0 for p in PROJS} for w in WEEKS}
res = {w: {p: 0 for p in PROJS} for w in WEEKS}
lead, lead_p = [], {p: [] for p in PROJS}
for k, f in hist.items():
    p = f["project"]["key"]
    if p not in cre[WEEKS[0]]:
        continue
    c, r = d(f.get("created")), d(f.get("resolutiondate"))
    wc, wr = wbucket(c), wbucket(r)
    if wc: cre[wc][p] += 1
    if wr: res[wr][p] += 1
    if c and r and wr and (r - c).days >= 0:
        lt = (r - c).days
        lead.append(lt); lead_p[p].append(lt)

dist = {"0-2": 0, "3-7": 0, "8-14": 0, "15-30": 0, "31+": 0}
for lt in lead:
    dist["0-2" if lt <= 2 else "3-7" if lt <= 7 else "8-14" if lt <= 14 else "15-30" if lt <= 30 else "31+"] += 1

# ---- WIP + aging ----
wip = load_nodes("wip-*.json")
wip_by = {p: 0 for p in PROJS}; age = {"<7": 0, "7-14": 0, "14-30": 0, "30-60": 0, "60+": 0}; oldest = []
for k, f in wip.items():
    p = f["project"]["key"]; wip_by[p] = wip_by.get(p, 0) + 1
    a = (TODAY - d(f["updated"])).days
    age["<7" if a < 7 else "7-14" if a < 14 else "14-30" if a < 30 else "30-60" if a < 60 else "60+"] += 1
    oldest.append((a, k, p, f["issuetype"]["name"], (f.get("assignee") or {}).get("displayName", "UNASSIGNED")))
oldest.sort(reverse=True)

# ---- bugs ----
bugs = load_nodes("bugs-*.json")
bug_by, bug_pri, oldb = {}, {}, []
for k, f in bugs.items():
    p = f["project"]["key"]; pr = (f.get("priority") or {}).get("name", "none")
    bug_by[p] = bug_by.get(p, 0) + 1; bug_pri[pr] = bug_pri.get(pr, 0) + 1
    oldb.append(((TODAY - d(f["created"])).days, k, p, pr))
oldb.sort(reverse=True)

# ---- sprints (issue counts from raw if present; commitment from sprints.json) ----
sprints = json.load(open(os.path.join(HERE, "sprints.json")))
for s in sprints:
    sf = os.path.join(RAW, f"sprint-{s['key']}.json")
    if os.path.exists(sf):
        done = prog = todo = 0
        for n in json.load(open(sf)).get("issues", {}).get("nodes", []):
            cat = ((n["fields"].get("status") or {}).get("statusCategory") or {}).get("key", "")
            if cat == "done": done += 1
            elif cat == "indeterminate": prog += 1
            else: todo += 1
        s["done"], s["prog"], s["todo"] = done, prog, todo

data = {
    "generated": TODAY.isoformat(), "tz": "America/Chicago", "projects": PROJS, "weeks": WEEKS,
    "created_weekly": cre, "resolved_weekly": res,
    "lead": {"n": len(lead), "median": round(statistics.median(lead), 1) if lead else 0,
             "p85": pct(lead, .85) or 0, "max": max(lead) if lead else 0, "dist": dist},
    "lead_by_project": {p: ({"n": len(lead_p[p]), "median": round(statistics.median(lead_p[p]), 1),
                             "p85": pct(lead_p[p], .85)} if lead_p[p] else {"n": 0, "median": None, "p85": None})
                        for p in PROJS},
    "wip_total": len(wip), "wip_by_project": wip_by, "wip_age": age,
    "wip_oldest": [{"age": a, "key": k, "proj": p, "type": t, "who": w} for (a, k, p, t, w) in oldest[:8]],
    "bugs_total": len(bugs), "bugs_by_project": bug_by, "bugs_by_priority": bug_pri,
    "bugs_oldest": [{"age": a, "key": k, "proj": p, "pri": pr} for (a, k, p, pr) in oldb[:6]],
    "sprints": sprints,
}

json.dump(data, open(os.path.join(HERE, "report_data.json"), "w"), indent=1)
tpl = open(os.path.join(HERE, "template.html")).read()
out = tpl.replace("__DATA__", json.dumps(data))
open(os.path.join(HERE, "execution-health.html"), "w").write(out)
print(f"built execution-health.html  | today={TODAY} hist={len(hist)} wip={len(wip)} bugs={len(bugs)} "
      f"net8wk={sum(sum(cre[w].values()) for w in WEEKS)-sum(sum(res[w].values()) for w in WEEKS):+d}")
