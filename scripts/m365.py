"""Microsoft 365 / Entra adapter — Graph app-only (client credentials).

Onboard: create user (firstname@domain), assign Business Premium (paid) + free
Power Automate, generate temp password, add to the Legions-ActivTrak-Devices
group. Idempotent: check-before-create, "already a member" == success.
"""
import os
import requests

from common import IS_LIVE, log, require_env, gen_temp_password, email_for

GRAPH = "https://graph.microsoft.com/v1.0"
# License part numbers.
BUSINESS_PREMIUM_SKU = "SPB"          # Microsoft 365 Business Premium
POWER_AUTOMATE_FREE_SKU = "FLOW_FREE"  # free Power Automate
ACTIVTRAK_GROUP = "Legions-ActivTrak-Devices"
USAGE_LOCATION = "US"

_token_cache = {}


def _token():
    if _token_cache.get("t"):
        return _token_cache["t"]
    s = require_env("MS_GRAPH_TENANT_ID", "MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET")
    url = f"https://login.microsoftonline.com/{s['MS_GRAPH_TENANT_ID']}/oauth2/v2.0/token"
    r = requests.post(url, data={
        "client_id": s["MS_GRAPH_CLIENT_ID"],
        "client_secret": s["MS_GRAPH_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }, timeout=30)
    r.raise_for_status()
    _token_cache["t"] = r.json()["access_token"]
    return _token_cache["t"]


def _h():
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def get_user(upn):
    """Return user dict or None (404). Selects accountEnabled explicitly."""
    if not IS_LIVE:
        return None  # mock: assume fresh account
    r = requests.get(f"{GRAPH}/users/{upn}",
                     params={"$select": "id,userPrincipalName,accountEnabled,displayName"},
                     headers=_h(), timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _sku_map():
    r = requests.get(f"{GRAPH}/subscribedSkus", headers=_h(), timeout=30)
    r.raise_for_status()
    out = {}
    for s in r.json().get("value", []):
        enabled = s.get("prepaidUnits", {}).get("enabled", 0)
        consumed = s.get("consumedUnits", 0)
        out[s.get("skuPartNumber")] = {
            "skuId": s.get("skuId"), "enabled": enabled, "consumed": consumed,
            "free": enabled - consumed,
        }
    return out


def seat_check():
    """Return (business_premium_free_seats, sku_map) — call once before a batch."""
    if not IS_LIVE:
        return None, {}
    m = _sku_map()
    bp = m.get(BUSINESS_PREMIUM_SKU)
    return (bp["free"] if bp else 0), m


def create_user(first_name, last_name):
    """Create the M365 user. Returns (user_id, upn, temp_password, note)."""
    upn = email_for(first_name)
    display = f"{first_name} {last_name}"
    temp = gen_temp_password()
    if not IS_LIVE:
        return f"mock-{first_name.lower()}-id", upn, temp, "mock-created"
    body = {
        "accountEnabled": True,
        "displayName": display,
        "mailNickname": first_name.strip().lower(),
        "userPrincipalName": upn,
        "usageLocation": USAGE_LOCATION,
        "passwordProfile": {
            "password": temp,
            "forceChangePasswordNextSignIn": True,
        },
    }
    r = requests.post(f"{GRAPH}/users", json=body, headers=_h(), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"create_user {upn} failed: {r.status_code} {r.text}")
    return r.json()["id"], upn, temp, "created"


def assign_license(user_id, sku_map, sku_part):
    """Assign a license by part number. Returns note string."""
    if not IS_LIVE:
        return f"mock-assigned {sku_part}"
    sku = sku_map.get(sku_part)
    if not sku:
        raise RuntimeError(f"SKU {sku_part} not present in tenant")
    r = requests.post(f"{GRAPH}/users/{user_id}/assignLicense",
                      json={"addLicenses": [{"skuId": sku["skuId"]}], "removeLicenses": []},
                      headers=_h(), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"assignLicense {sku_part} failed: {r.status_code} {r.text}")
    return f"assigned {sku_part}"


def _group_id():
    if os.environ.get("ACTIVTRAK_GROUP_ID"):
        return os.environ["ACTIVTRAK_GROUP_ID"]
    r = requests.get(f"{GRAPH}/groups",
                     params={"$filter": f"displayName eq '{ACTIVTRAK_GROUP}'", "$select": "id"},
                     headers=_h(), timeout=30)
    r.raise_for_status()
    vals = r.json().get("value", [])
    if not vals:
        raise RuntimeError(f"group {ACTIVTRAK_GROUP} not found")
    return vals[0]["id"]


def add_to_activtrak(user_id):
    """Add user to Legions-ActivTrak-Devices. Idempotent. Returns note.
    Degrades to a manual reminder on failure (raises DegradeManual)."""
    if not IS_LIVE:
        return "mock-added to Legions-ActivTrak-Devices"
    gid = _group_id()
    r = requests.post(f"{GRAPH}/groups/{gid}/members/$ref",
                      json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"},
                      headers=_h(), timeout=30)
    if r.status_code in (204, 201):
        return "added to Legions-ActivTrak-Devices"
    # "already exists" -> treat as success (idempotent)
    if r.status_code == 400 and "already exist" in r.text.lower():
        return "already a member"
    raise DegradeManual(f"ActivTrak group add failed ({r.status_code}); add manually in Entra/Intune")


class DegradeManual(Exception):
    """Non-fatal: step should degrade to a flagged manual action, not fail the onboard."""
