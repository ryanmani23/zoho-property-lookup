"""Orchestrator for the LUF new-hire onboard.

Order per person: M365 (identity + licenses + temp password) -> ActivTrak group
-> RingCentral (user + number) -> Zoho CRM (LO/manager only). Runs Mock by
default; MODE=live executes for real. Idempotent and stop-within-person on a
hard failure (no destructive steps in an onboard). Prints a per-step result
table and a per-person summary (email / temp password / RC number) for the
confirmation to Tom.
"""
import json
import sys

import common
from common import log, banner, StepResult, email_for
import m365
import ringcentral
import zoho

# The four new-hire loan officers from Tom's "New Hire LOs" request.
# role "loan_officer" -> ActivTrak group YES, Zoho CRM YES.
PEOPLE = [
    {"first": "Auston", "last": "Nelles", "role": "loan_officer"},
    {"first": "Leslie", "last": "Horne", "role": "loan_officer"},
    {"first": "Matthew", "last": "Hess", "role": "loan_officer"},
    {"first": "Jason", "last": "Hill", "role": "loan_officer"},
]


def onboard_person(p, sku_map, bp_free_tracker):
    first, last = p["first"], p["last"]
    upn = email_for(first)
    rows = []
    summary = {"name": f"{first} {last}", "email": upn, "temp_password": None,
               "rc_number": None, "zoho": None, "status": "ok"}

    # --- Collision / directory check ---
    existing = m365.get_user(upn)
    if existing:
        r = StepResult(f"{first} {last}", "M365", "collision-check").failed(
            f"{upn} ALREADY EXISTS (id {existing.get('id')}) — possible name collision/rehire; "
            f"paused, confirm variant with Tom")
        rows.append(r)
        summary["status"] = "paused-collision"
        return rows, summary

    # --- 1. M365 create ---
    try:
        uid, upn, temp, note = m365.create_user(first, last)
        summary["temp_password"] = temp
        rows.append(StepResult(f"{first} {last}", "M365", f"create {upn}").ok(note))
    except Exception as e:
        rows.append(StepResult(f"{first} {last}", "M365", "create user").failed(str(e)))
        summary["status"] = "failed"
        return rows, summary

    # --- 1a. Business Premium (paid) ---
    try:
        if common.IS_LIVE and bp_free_tracker["free"] <= 0:
            rows.append(StepResult(f"{first} {last}", "M365", "assign Business Premium").failed(
                "NO FREE SEAT — purchase required (billing); user created but unlicensed"))
            summary["status"] = "needs-license-purchase"
        else:
            note = m365.assign_license(uid, sku_map, m365.BUSINESS_PREMIUM_SKU)
            if common.IS_LIVE:
                bp_free_tracker["free"] -= 1
            rows.append(StepResult(f"{first} {last}", "M365", "assign Business Premium").ok(note))
    except Exception as e:
        rows.append(StepResult(f"{first} {last}", "M365", "assign Business Premium").failed(str(e)))

    # --- 1b. Free Power Automate ---
    try:
        note = m365.assign_license(uid, sku_map, m365.POWER_AUTOMATE_FREE_SKU)
        rows.append(StepResult(f"{first} {last}", "M365", "assign Power Automate (free)").ok(note))
    except Exception as e:
        rows.append(StepResult(f"{first} {last}", "M365", "assign Power Automate (free)").failed(str(e)))

    # --- 2. ActivTrak group (LO -> included) ---
    try:
        note = m365.add_to_activtrak(uid)
        rows.append(StepResult(f"{first} {last}", "Entra group", "add Legions-ActivTrak-Devices").ok(note))
    except m365.DegradeManual as e:
        rows.append(StepResult(f"{first} {last}", "Entra group", "add Legions-ActivTrak-Devices").skipped(
            f"MANUAL: {e}"))
    except Exception as e:
        rows.append(StepResult(f"{first} {last}", "Entra group", "add Legions-ActivTrak-Devices").skipped(
            f"MANUAL: {e}"))

    # --- 3. RingCentral user + number ---
    try:
        ext_id, number, note = ringcentral.create_user(first, last)
        summary["rc_number"] = number
        rows.append(StepResult(f"{first} {last}", "RingCentral", "create user + number").ok(note))
    except Exception as e:
        rows.append(StepResult(f"{first} {last}", "RingCentral", "create user + number").failed(str(e)))
        summary["status"] = "partial"

    # --- 4. Zoho CRM (LO -> yes) ---
    if p["role"] in ("loan_officer", "manager"):
        try:
            zid, note = zoho.create_user(first, last)
            summary["zoho"] = "granted"
            rows.append(StepResult(f"{first} {last}", "Zoho CRM", "create user + CRM access").ok(note))
        except Exception as e:
            summary["zoho"] = "failed"
            rows.append(StepResult(f"{first} {last}", "Zoho CRM", "create user + CRM access").failed(str(e)))
            summary["status"] = "partial"
    else:
        rows.append(StepResult(f"{first} {last}", "Zoho CRM", "skip").skipped("role not LO/manager"))

    return rows, summary


def main():
    banner()
    all_rows = []
    summaries = []

    bp_free, sku_map = m365.seat_check()
    bp_tracker = {"free": bp_free if bp_free is not None else 9999}
    if common.IS_LIVE:
        log(f"Business Premium free seats before batch: {bp_tracker['free']} (need {len(PEOPLE)})")

    for p in PEOPLE:
        log(f"\n--- Onboarding {p['first']} {p['last']} ({p['role']}) ---")
        rows, summary = onboard_person(p, sku_map, bp_tracker)
        for r in rows:
            log(f"  [{r.result.upper():7}] {r.system:14} {r.action}  {('- ' + r.note) if r.note else ''}")
        all_rows.extend(rows)
        summaries.append(summary)

    # Machine-readable results for the confirmation draft + tracker.
    print("\n===RESULTS_JSON_START===")
    print(json.dumps({"mode": common.MODE,
                      "steps": [r.as_row() for r in all_rows],
                      "people": summaries}, indent=2))
    print("===RESULTS_JSON_END===")

    failed = [r for r in all_rows if r.result == "failed"]
    return 1 if (common.IS_LIVE and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
