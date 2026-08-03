"""Retry the free Power Automate license assignment that hit transient Graph
Directory_ConcurrencyViolation / connection resets during the batch, then print
each user's final license state. Idempotent — assigning an already-assigned SKU
is a no-op we treat as success.
"""
import sys
import time

import requests
import m365
from common import IS_LIVE, email_for, log

RETRY_FIRST = ["Auston", "Leslie", "Matthew"]  # missing FLOW_FREE after the batch
ALL_FIRST = ["Auston", "Leslie", "Matthew", "Jason"]


def assign_with_retry(uid, sku_map, sku_part, attempts=6):
    last = None
    for i in range(attempts):
        try:
            return m365.assign_license(uid, sku_map, sku_part)
        except Exception as e:
            last = str(e)
            if "ConcurrencyViolation" in last or "Connection" in last or "reset" in last:
                time.sleep(2 * (i + 1))  # linear backoff, serialized
                continue
            raise
    raise RuntimeError(f"still failing after {attempts}: {last}")


def license_state(upn):
    r = requests.get(f"{m365.GRAPH}/users/{upn}/licenseDetails", headers=m365._h(), timeout=30)
    r.raise_for_status()
    return sorted(x.get("skuPartNumber") for x in r.json().get("value", []))


def main():
    if not IS_LIVE:
        log("Run with MODE=live")
        return 0
    _, sku_map = m365.seat_check()

    for first in RETRY_FIRST:
        upn = email_for(first)
        u = m365.get_user(upn)
        note = assign_with_retry(u["id"], sku_map, m365.POWER_AUTOMATE_FREE_SKU)
        log(f"[retry] {upn}: {note}")

    log("\n=== Final M365 license state ===")
    for first in ALL_FIRST:
        upn = email_for(first)
        log(f"  {upn:42} {license_state(upn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
