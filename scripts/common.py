"""Shared helpers for the LUF onboarding/offboarding adapters.

Every adapter has a Mock and a Live path selected by the MODE env var
(default "mock"). Mock mutates nothing and returns synthetic success so the
whole flow can be rehearsed before any real credential is used. Live calls the
real vendor API with secrets read *only* from the environment.
"""
import os
import secrets
import string
import sys

MODE = os.environ.get("MODE", "mock").lower()
IS_LIVE = MODE == "live"

DOMAIN = "legionsunitedfunding.com"


def log(msg):
    print(msg, flush=True)


def banner():
    log(f"=== LUF provisioning — MODE={MODE.upper()} "
        f"({'LIVE — real mutations' if IS_LIVE else 'DRY-RUN — nothing changes'}) ===")


def require_env(*names):
    """Return the listed env vars; raise if any are missing (live only)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing and IS_LIVE:
        raise RuntimeError(f"Missing required secrets: {', '.join(missing)}")
    return {n: os.environ.get(n, "") for n in names}


def gen_temp_password(nbytes=8):
    """Strong temporary password; user resets on first sign-in."""
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(nbytes))
    # Guarantee complexity requirements.
    return f"Luf-{core}-{secrets.choice('!@#$%')}{secrets.randbelow(90)+10}"


def email_for(first_name):
    return f"{first_name.strip().lower()}@{DOMAIN}"


class StepResult:
    def __init__(self, person, system, action):
        self.person = person
        self.system = system
        self.action = action
        self.result = "pending"   # ok | skipped | failed
        self.note = ""

    def ok(self, note=""):
        self.result, self.note = "ok", note
        return self

    def skipped(self, note=""):
        self.result, self.note = "skipped", note
        return self

    def failed(self, note=""):
        self.result, self.note = "failed", note
        return self

    def as_row(self):
        return {"person": self.person, "system": self.system,
                "action": self.action, "result": self.result, "note": self.note}
