# RingCX SUSPECT auto-logout monitor

Legions United Funding agents sometimes get stuck in the **SUSPECT** state in RingCX.
SUSPECT means RingCX lost contact with the agent's session: the softphone/WebRTC
connection dropped (Wi-Fi blip, VPN reconnect, laptop sleep, browser tab killed).
The fix has been for an admin to open Analytics → Real-time dashboard and click **Logout**.

This Google Apps Script does the same thing automatically, every minute:

1. `GET /voice/api/v1/admin/accounts/51060001/realTimeData/agent`: live state of every logged-in agent
2. Any agent with `agentState = SUSPECT` for ≥ `SUSPECT_SECONDS` →
   `POST /voice/api/v1/admin/accounts/51060001/agentGroups/{groupId}/agents/{agentId}/logout`
3. Emails `NOTIFY_EMAILS` with who was logged out and why

Safeguards:
- **Dry run by default.** It only emails what it *would* do until `DRY_RUN=false`.
- **Threshold.** A brief SUSPECT blip that recovers on its own is ignored (default 60s).
- **Call attached.** If RingCX still shows a `callUii`, it waits longer (default 300s).
- **Cooldown.** It won't log out the same agent more than once per 5 minutes.
- **Exclusions.** List agent IDs in `EXCLUDE_AGENT_IDS` to skip them.
- **Script lock.** Overlapping runs can't double-fire.

## Setup (≈10 minutes)

1. Go to <https://script.google.com> → **New project** → name it `RingCX Suspect Monitor`.
   Use a Workspace account that will stay around (e.g. support@makanalytics.org).
2. Replace the contents of `Code.gs` with [`Code.gs`](./Code.gs) from this folder and save.
3. **Project Settings → Script Properties**, add:

   | Property | Value |
   |---|---|
   | `RC_CLIENT_ID` | RingCentral app client ID (same JWT app used for LUF automation) |
   | `RC_CLIENT_SECRET` | RingCentral app client secret |
   | `RC_JWT` | JWT credential for a RingCentral admin with RingCX admin rights (currently itsupport@legionsunitedfunding.com) |
   | `NOTIFY_EMAILS` | comma-separated, e.g. Tom's address plus `ryanmani@makanalytics.org` |
   | `DRY_RUN` | `true` (switch to `false` once you trust it) |

   Optional overrides: `SUSPECT_SECONDS` (60), `SUSPECT_WITH_CALL_SECONDS` (300),
   `COOLDOWN_SECONDS` (300), `EXCLUDE_AGENT_IDS`, `RINGCX_ACCOUNT_ID` (51060001).
4. In the editor, select `testConnection` → **Run**. Approve the permissions prompt
   (external requests, email, triggers). The execution log should list every logged-in agent and their state.
5. Select `installTrigger` → **Run**. This creates the every-minute trigger.
6. Leave it in dry run for a few days. When a `[DRY RUN]` email shows up for a real
   SUSPECT case, check that it matches what Tom reports, then set `DRY_RUN` to `false`.

Logs: **Executions** in the left sidebar shows each run and any errors.
Apps Script also emails the owner if the trigger keeps failing.

## Reducing how often SUSPECT happens

Auto-logout removes the wait, but repeat offenders point to the agent's setup:
- Agents on the NordLayer VPN: RingCX media should bypass the VPN (split tunnel), or the
  agent should test without it.
- Chrome "Memory Saver" / tab sleeping can kill the RingCX tab. Add the RingCX domain to
  *Always keep these sites active*.
- Laptop sleep / power-saving on Wi-Fi adapters; prefer wired when possible.

The notification emails show which agents go SUSPECT most, so you know where to look first.
