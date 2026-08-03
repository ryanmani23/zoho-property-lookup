"""Zoho CRM adapter — Users API, server-based OAuth (refresh-token grant).

Onboard (loan officers / managers only): add the CRM user with their M365
email, an active status, and a profile/role suitable to the role. Idempotent:
if the email already exists as a CRM user, skip.
"""
import os
import requests

from common import IS_LIVE, require_env, email_for

_token_cache = {}


def _accounts():
    return os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/")


def _api():
    return os.environ.get("ZOHO_API_DOMAIN", "https://www.zohoapis.com").rstrip("/")


def _ver():
    return os.environ.get("ZOHO_API_VERSION", "v7")


def _token():
    if _token_cache.get("t"):
        return _token_cache["t"]
    s = require_env("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")
    r = requests.post(f"{_accounts()}/oauth/v2/token", data={
        "refresh_token": s["ZOHO_REFRESH_TOKEN"],
        "client_id": s["ZOHO_CLIENT_ID"],
        "client_secret": s["ZOHO_CLIENT_SECRET"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    body = r.json()
    if "access_token" not in body:
        # invalid_oauthscope etc. surface here
        raise RuntimeError(f"Zoho token error: {body}")
    _token_cache["t"] = body["access_token"]
    return _token_cache["t"]


def _h():
    return {"Authorization": f"Zoho-oauthtoken {_token()}", "Content-Type": "application/json"}


def _profile_role_ids():
    """Resolve a Standard/Users profile + a role id for a loan-officer seat."""
    pr = requests.get(f"{_api()}/crm/{_ver()}/settings/profiles", headers=_h(), timeout=30)
    pr.raise_for_status()
    profiles = pr.json().get("profiles", [])
    # Prefer "Standard" (full CRM user); fall back to first non-Administrator.
    profile = next((p for p in profiles if p.get("name", "").lower() == "standard"),
                   next((p for p in profiles if p.get("name") != "Administrator"), profiles[0]))
    rr = requests.get(f"{_api()}/crm/{_ver()}/settings/roles", headers=_h(), timeout=30)
    rr.raise_for_status()
    roles = rr.json().get("roles", [])
    # Prefer a non-CEO role; fall back to first.
    role = next((r for r in roles if "ceo" not in r.get("name", "").lower()), roles[0])
    return profile["id"], role["id"]


def find_user_by_email(email):
    if not IS_LIVE:
        return None
    r = requests.get(f"{_api()}/crm/{_ver()}/users",
                     params={"type": "AllUsers"}, headers=_h(), timeout=30)
    r.raise_for_status()
    for u in r.json().get("users", []):
        if (u.get("email") or "").lower() == email.lower():
            return u
    return None


def create_user(first_name, last_name):
    """Create the CRM user. Returns (user_id, note)."""
    email = email_for(first_name)
    if not IS_LIVE:
        return f"mock-zoho-{first_name.lower()}", "mock-created (CRM access granted)"

    existing = find_user_by_email(email)
    if existing:
        return existing.get("id"), "already exists (idempotent skip)"

    profile_id, role_id = _profile_role_ids()
    body = {"users": [{
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "profile": {"id": profile_id},
        "role": {"id": role_id},
    }]}
    r = requests.post(f"{_api()}/crm/{_ver()}/users", json=body, headers=_h(), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Zoho create user {email} failed: {r.status_code} {r.text}")
    payload = r.json()
    rec = (payload.get("users") or [{}])[0]
    if rec.get("status") == "error":
        raise RuntimeError(f"Zoho create user {email} error: {rec}")
    return rec.get("details", {}).get("id"), "created (CRM access granted)"
