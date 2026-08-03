# LUF Onboarding / Offboarding adapters

Code that runs the LUF new-hire onboard across M365/Entra, RingCentral, and
Zoho, per the `luf-onboarding-offboarding` skill + runbook. Each system is an
adapter with a **Mock** and a **Live** path selected by `MODE` (default `mock`).
Secrets are read **only** from the environment at runtime — none are stored here.

- `common.py` — mode flag, secret loader, temp-password gen, result records
- `m365.py` — Graph app-only: create user, licenses (Business Premium + free
  Power Automate), ActivTrak group membership
- `ringcentral.py` — JWT-bearer: create user extension + assign number
- `zoho.py` — CRM users API (note: Zoho One orgs block CRM-API user creation —
  add via Zoho One instead)
- `orchestrate_onboard.py` — sequences M365 → ActivTrak → RingCentral → Zoho per
  person; idempotent; prints a per-step result table
- `remediate_licenses.py` — retries transient Graph license failures + verifies

Run a rehearsal: `MODE=mock python3 orchestrate_onboard.py`
Execute for real (after approval): `MODE=live python3 orchestrate_onboard.py`

Required env secrets: `MS_GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET`,
`RC_SERVER_URL/CLIENT_ID/CLIENT_SECRET/RC_JWT`,
`ZOHO_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN/ACCOUNTS_URL/API_DOMAIN`.
