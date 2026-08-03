"""Zoho One adapter — user provisioning via the Zoho One API (one.zoho.com).

A Zoho One org rejects CRM-API user creation ("Cannot add user for ZohoOne
account from CRM"), so new users are added through Zoho One, which grants the
org license (CRM included). Reuses the ZohoOne-scoped refresh token in
ZOHO_REFRESH_TOKEN. Org resolved at runtime via GET /orgs -> account_type
'zohoone'. Idempotent: match on primary_email before creating.
"""
import os
import requests

from common import IS_LIVE, require_env, email_for
import zoho  # reuse token minting (same refresh token, carries ZohoOne scope)

ONE = "https://one.zoho.com/api/v1"


def _h():
    return {"Authorization": f"Zoho-oauthtoken {zoho._token()}", "Content-Type": "application/json"}


def resolve_org_id():
    if os.environ.get("ZOHO_ONE_ORG_ID"):
        return os.environ["ZOHO_ONE_ORG_ID"]
    r = requests.get(f"{ONE}/orgs", headers=_h(), timeout=30)
    r.raise_for_status()
    for o in r.json().get("orgs", []):
        if o.get("account_type") == "zohoone":
            return str(o["org_id"])
    raise RuntimeError("no zohoone org found in GET /orgs")


def _existing_users(org_id):
    # NOTE: call bare — query params make this endpoint 500.
    r = requests.get(f"{ONE}/orgs/{org_id}/users", headers=_h(), timeout=30)
    r.raise_for_status()
    return r.json().get("users", [])


def find_user(org_id, email):
    for u in _existing_users(org_id):
        if (u.get("primary_email") or "").lower() == email.lower():
            return u
    return None


def create_user(org_id, first_name, last_name):
    """Add a user to the Zoho One org (grants org license incl. CRM). Sends an
    invite to the user. Returns (user_id, note)."""
    email = email_for(first_name)
    if not IS_LIVE:
        return f"mock-zohoone-{first_name.lower()}", "mock-created (Zoho One invite)"

    existing = find_user(org_id, email)
    if existing:
        return existing.get("user_id"), "already exists (idempotent skip)"

    # Zoho One wants the user as an OBJECT (not array) with emails[email_id].
    body = {"users": {
        "first_name": first_name,
        "last_name": last_name,
        "emails": [{"email_id": email, "is_primary": True}],
    }}
    r = requests.post(f"{ONE}/orgs/{org_id}/users", json=body, headers=_h(), timeout=30)
    j = {}
    try:
        j = r.json()
    except Exception:
        pass
    inner = j.get("status_code", r.status_code)
    if r.status_code >= 400 or inner >= 400:
        raise RuntimeError(f"Zoho One create {email} failed: http={r.status_code} inner={inner} {r.text[:300]}")
    # Re-read to capture the new user_id.
    created = find_user(org_id, email)
    return (created or {}).get("user_id"), f"created ({inner}: {j.get('message','ok')})"
