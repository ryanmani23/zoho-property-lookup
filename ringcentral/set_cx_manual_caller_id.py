#!/usr/bin/env python3
"""Set RingCX "Manual outbound default caller ID" per agent.

Fixes LOs' RingCentral app keypad defaulting to "RingCX Default" on outbound:
with manualOutboundDefaultCallerId blank (and no default queue / queue manual
caller ID), RingCX falls back to an account-level ANI instead of the LO's DID.

Input: a plan CSV with columns agentId, agentGroupId, name, proposed
(10-digit number). Rows with an empty `proposed` are skipped.

Dry run by default. Writes only with --apply, optionally limited with --only.

Env: RC_SERVER_URL, RC_CLIENT_ID, RC_CLIENT_SECRET, RC_JWT
     RCX_ACCOUNT_ID (default 51060001, SUB-Legions United Funding)

  python3 set_cx_manual_caller_id.py plan.csv
  python3 set_cx_manual_caller_id.py plan.csv --apply --only 34447
  python3 set_cx_manual_caller_id.py plan.csv --apply
"""
import argparse
import base64
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

ENGAGE = "https://engage.ringcentral.com"


def http(method, url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def cx_token():
    basic = base64.b64encode(f"{os.environ['RC_CLIENT_ID']}:{os.environ['RC_CLIENT_SECRET']}".encode()).decode()
    rc = http(
        "POST",
        f"{os.environ['RC_SERVER_URL']}/restapi/oauth/token",
        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": os.environ["RC_JWT"],
        }).encode(),
    )
    cx = http(
        "POST",
        f"{ENGAGE}/api/auth/login/rc/accesstoken?includeRefresh=false",
        {"Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({"rcAccessToken": rc["access_token"], "rcTokenType": "Bearer"}).encode(),
    )
    return cx["accessToken"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--only", nargs="*", help="limit to these agentIds")
    args = ap.parse_args()

    account = os.environ.get("RCX_ACCOUNT_ID", "51060001")
    token = cx_token()
    auth = {"Authorization": f"Bearer {token}"}

    rows = list(csv.DictReader(open(args.plan)))
    if args.only:
        rows = [r for r in rows if r["agentId"] in args.only]

    failed = 0
    for r in rows:
        want = r["proposed"].strip()
        if not want:
            print(f"SKIP   {r['agentId']:>6} {r['name']}: no proposed number")
            continue
        url = f"{ENGAGE}/voice/api/v1/admin/accounts/{account}/agentGroups/{r['agentGroupId']}/agents/{r['agentId']}"
        agent = http("GET", url, auth)
        have = agent.get("manualOutboundDefaultCallerId") or ""
        if have == want:
            print(f"OK     {r['agentId']:>6} {r['name']}: already {want}")
            continue
        print(f"{'SET' if args.apply else 'WOULD'}  {r['agentId']:>6} {r['name']}: '{have}' -> {want}")
        if not args.apply:
            continue
        agent["manualOutboundDefaultCallerId"] = want
        http("PUT", url, {**auth, "Content-Type": "application/json"}, json.dumps(agent).encode())
        check = http("GET", url, auth).get("manualOutboundDefaultCallerId")
        if check != want:
            failed += 1
            print(f"  !! verify failed: reads back '{check}'")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
