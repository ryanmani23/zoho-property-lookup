"""RingCentral adapter — Platform API, OAuth2 JWT-bearer.

Onboard: create the user extension with their M365 email and assign a number
from the account's available inventory. No queue membership at creation (that
is a separate follow-up once Tom sends the queue list).
"""
import os
import requests

from common import IS_LIVE, log, require_env, email_for

_token_cache = {}


def _base():
    return os.environ.get("RC_SERVER_URL", "https://platform.ringcentral.com").rstrip("/")


def _token():
    if _token_cache.get("t"):
        return _token_cache["t"]
    s = require_env("RC_CLIENT_ID", "RC_CLIENT_SECRET", "RC_JWT")
    r = requests.post(f"{_base()}/restapi/oauth/token",
                      auth=(s["RC_CLIENT_ID"], s["RC_CLIENT_SECRET"]),
                      data={
                          "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                          "assertion": s["RC_JWT"],
                      }, timeout=30)
    r.raise_for_status()
    _token_cache["t"] = r.json()["access_token"]
    return _token_cache["t"]


def _h():
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def find_extension_by_email(email):
    """Return extension dict if a user with this email already exists, else None."""
    if not IS_LIVE:
        return None
    r = requests.get(f"{_base()}/restapi/v1.0/account/~/extension",
                     params={"type": "User", "perPage": 1000}, headers=_h(), timeout=30)
    r.raise_for_status()
    for ext in r.json().get("records", []):
        if (ext.get("contact", {}) or {}).get("email", "").lower() == email.lower():
            return ext
    return None


def _pick_available_number():
    """Find an unassigned DID in the account inventory (usageType NumberPool)."""
    r = requests.get(f"{_base()}/restapi/v1.0/account/~/phone-number",
                     params={"usageType": "NumberPool", "perPage": 1000},
                     headers=_h(), timeout=30)
    r.raise_for_status()
    for n in r.json().get("records", []):
        if not n.get("extension"):
            return n
    return None


def create_user(first_name, last_name):
    """Create a User extension with the M365 email, assign a number.
    Returns (extension_id, phone_number, note)."""
    email = email_for(first_name)
    if not IS_LIVE:
        return f"mock-ext-{first_name.lower()}", "mock-number", "mock-created + number assigned"

    existing = find_extension_by_email(email)
    if existing:
        num = _extension_number(existing["id"])
        return existing["id"], num, "already exists (idempotent skip)"

    body = {
        "contact": {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
        },
        "type": "User",
        "status": "Enabled",
    }
    r = requests.post(f"{_base()}/restapi/v1.0/account/~/extension",
                      json=body, headers=_h(), timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"RC create extension {email} failed: {r.status_code} {r.text}")
    ext_id = r.json()["id"]

    # Assign a number from inventory.
    number = _pick_available_number()
    if not number:
        return ext_id, None, "extension created; NO free number in inventory — assign manually"
    upd = requests.put(f"{_base()}/restapi/v1.0/account/~/phone-number/{number['id']}",
                       json={"extension": {"id": ext_id}}, headers=_h(), timeout=30)
    if upd.status_code >= 400:
        return ext_id, None, f"extension created; number assign failed ({upd.status_code}) — assign manually"
    return ext_id, number.get("phoneNumber"), "created + number assigned"


def _extension_number(ext_id):
    if not IS_LIVE:
        return "mock-number"
    r = requests.get(f"{_base()}/restapi/v1.0/account/~/extension/{ext_id}/phone-number",
                     headers=_h(), timeout=30)
    if r.status_code >= 400:
        return None
    recs = r.json().get("records", [])
    return recs[0].get("phoneNumber") if recs else None
