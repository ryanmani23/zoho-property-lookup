/**
 * RingCX SUSPECT-state auto-logout monitor (Legions United Funding).
 *
 * Runs on a 1-minute Apps Script time trigger. Each run:
 *   1. Pulls live agent states from the RingCX Real-Time Supervisor View API.
 *   2. Finds agents stuck in SUSPECT longer than the threshold.
 *   3. Logs them out (same as "Logout" in the Analytics real-time dashboard).
 *   4. Emails the notify list about what it did.
 *
 * Setup: see README.md. All credentials live in Script Properties, never in code.
 */

var CONFIG_DEFAULTS = {
  RC_SERVER_URL: 'https://platform.ringcentral.com',
  RINGCX_BASE: 'https://ringcx.ringcentral.com',
  RINGCX_ACCOUNT_ID: '51060001',
  // Seconds an agent must sit in SUSPECT before we act (filters brief network blips).
  SUSPECT_SECONDS: '60',
  // If RingCX still shows a call attached, wait this long before forcing logout.
  SUSPECT_WITH_CALL_SECONDS: '300',
  // Don't log out the same agent again within this window.
  COOLDOWN_SECONDS: '300',
  // 'true' = only report what would happen. Flip to 'false' to go live.
  DRY_RUN: 'true',
  // Comma-separated emails to notify. Empty = no email.
  NOTIFY_EMAILS: '',
  // Comma-separated agentIds to never touch.
  EXCLUDE_AGENT_IDS: ''
};

function cfg_(key) {
  var v = PropertiesService.getScriptProperties().getProperty(key);
  return v === null || v === '' ? CONFIG_DEFAULTS[key] : v;
}

/** Entry point for the time trigger. */
function checkSuspectAgents() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return; // previous run still going
  try {
    var agents = getRealTimeAgents_();
    var actions = decideActions_(agents, {
      now: Date.now(),
      suspectSeconds: Number(cfg_('SUSPECT_SECONDS')),
      suspectWithCallSeconds: Number(cfg_('SUSPECT_WITH_CALL_SECONDS')),
      cooldownSeconds: Number(cfg_('COOLDOWN_SECONDS')),
      excludeIds: splitList_(cfg_('EXCLUDE_AGENT_IDS')),
      lastLogout: loadLastLogout_()
    });
    if (!actions.length) return;

    var dryRun = cfg_('DRY_RUN') !== 'false';
    var results = actions.map(function (a) {
      var r = { agent: a.agent, reason: a.reason, dryRun: dryRun, ok: true, error: null };
      if (!dryRun) {
        try {
          logoutAgent_(a.agent.agentGroupId, a.agent.agentId);
          recordLogout_(a.agent.agentId);
        } catch (e) {
          r.ok = false;
          r.error = String(e);
        }
      }
      console.log(JSON.stringify({ agentId: a.agent.agentId, name: fullName_(a.agent), reason: a.reason, dryRun: dryRun, ok: r.ok, error: r.error }));
      return r;
    });
    notify_(results);
  } finally {
    lock.releaseLock();
  }
}

/**
 * Pure decision logic: which agents to log out and why.
 * agents: AgentStats[] from /realTimeData/agent.
 */
function decideActions_(agents, opts) {
  var out = [];
  (agents || []).forEach(function (a) {
    if (String(a.agentState || '').toUpperCase() !== 'SUSPECT') return;
    if (opts.excludeIds.indexOf(String(a.agentId)) !== -1) return;
    var last = opts.lastLogout[String(a.agentId)];
    if (last && opts.now - last < opts.cooldownSeconds * 1000) return;

    var secs = Number(a.stateTime) || 0;
    var hasCall = !!a.callUii;
    var needed = hasCall ? opts.suspectWithCallSeconds : opts.suspectSeconds;
    if (secs < needed) return;

    out.push({
      agent: a,
      reason: 'SUSPECT for ' + secs + 's' + (hasCall ? ' (call ' + a.callUii + ' still attached)' : '')
    });
  });
  return out;
}

// ---------- RingCX API ----------

function getRealTimeAgents_() {
  return ringcxFetch_('get', '/voice/api/v1/admin/accounts/' + cfg_('RINGCX_ACCOUNT_ID') + '/realTimeData/agent');
}

function logoutAgent_(agentGroupId, agentId) {
  return ringcxFetch_('post', '/voice/api/v1/admin/accounts/' + cfg_('RINGCX_ACCOUNT_ID') +
    '/agentGroups/' + agentGroupId + '/agents/' + agentId + '/logout');
}

function ringcxFetch_(method, path, retried) {
  var resp = UrlFetchApp.fetch(cfg_('RINGCX_BASE') + path, {
    method: method,
    headers: { Authorization: 'Bearer ' + getRingcxToken_(!!retried), Accept: 'application/json' },
    muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  if (code === 401 && !retried) return ringcxFetch_(method, path, true);
  if (code < 200 || code >= 300) {
    throw new Error(method.toUpperCase() + ' ' + path + ' -> HTTP ' + code + ': ' + resp.getContentText().slice(0, 300));
  }
  var text = resp.getContentText();
  return text ? JSON.parse(text) : null;
}

/** RingCentral JWT -> RC access token -> RingCX access token, cached ~30 min. */
function getRingcxToken_(forceRefresh) {
  var cache = CacheService.getScriptCache();
  if (!forceRefresh) {
    var cached = cache.get('ringcx_token');
    if (cached) return cached;
  }
  var props = PropertiesService.getScriptProperties();
  var rcResp = UrlFetchApp.fetch(cfg_('RC_SERVER_URL') + '/restapi/oauth/token', {
    method: 'post',
    headers: {
      Authorization: 'Basic ' + Utilities.base64Encode(props.getProperty('RC_CLIENT_ID') + ':' + props.getProperty('RC_CLIENT_SECRET'))
    },
    payload: { grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion: props.getProperty('RC_JWT') },
    muteHttpExceptions: true
  });
  if (rcResp.getResponseCode() !== 200) throw new Error('RingCentral auth failed: HTTP ' + rcResp.getResponseCode() + ' ' + rcResp.getContentText().slice(0, 300));
  var rcToken = JSON.parse(rcResp.getContentText()).access_token;

  var cxResp = UrlFetchApp.fetch('https://engage.ringcentral.com/api/auth/login/rc/accesstoken?includeRefresh=true', {
    method: 'post',
    payload: { rcAccessToken: rcToken, rcTokenType: 'Bearer' },
    muteHttpExceptions: true
  });
  if (cxResp.getResponseCode() !== 200) throw new Error('RingCX token exchange failed: HTTP ' + cxResp.getResponseCode() + ' ' + cxResp.getContentText().slice(0, 300));
  var cxToken = JSON.parse(cxResp.getContentText()).accessToken;
  cache.put('ringcx_token', cxToken, 1800);
  return cxToken;
}

// ---------- State, notifications, helpers ----------

function loadLastLogout_() {
  var raw = PropertiesService.getScriptProperties().getProperty('STATE_LAST_LOGOUT');
  return raw ? JSON.parse(raw) : {};
}

function recordLogout_(agentId) {
  var state = loadLastLogout_();
  var now = Date.now();
  state[String(agentId)] = now;
  // Prune entries older than a day so the property stays small.
  Object.keys(state).forEach(function (k) { if (now - state[k] > 86400000) delete state[k]; });
  PropertiesService.getScriptProperties().setProperty('STATE_LAST_LOGOUT', JSON.stringify(state));
}

function notify_(results) {
  var to = cfg_('NOTIFY_EMAILS');
  if (!to) return;
  var dry = results[0].dryRun;
  var names = results.map(function (r) { return fullName_(r.agent); }).join(', ');
  var lines = results.map(function (r) {
    var status = r.dryRun ? 'WOULD log out (dry run)' : (r.ok ? 'Logged out' : 'FAILED to log out: ' + r.error);
    return '- ' + fullName_(r.agent) + ' (agent ' + r.agent.agentId + ', ' + (r.agent.agentGroupName || 'group ' + r.agent.agentGroupId) + '): ' +
      status + ' - ' + r.reason;
  });
  MailApp.sendEmail({
    to: to,
    subject: (dry ? '[DRY RUN] ' : '') + 'RingCX: auto-logout of SUSPECT agent(s): ' + names,
    body: 'The RingCX monitor found agent(s) stuck in SUSPECT state:\n\n' + lines.join('\n') +
      '\n\n' + (dry ? 'Dry-run mode is on, so nothing was changed.' :
      'They can now log back into RingCX normally. If an agent goes SUSPECT repeatedly, check their network / VPN / browser.')
  });
}

function fullName_(a) {
  return ((a.firstName || '') + ' ' + (a.lastName || '')).trim() || ('agent ' + a.agentId);
}

function splitList_(s) {
  return String(s || '').split(',').map(function (x) { return x.trim(); }).filter(String);
}

// ---------- One-time setup helpers (run manually from the editor) ----------

/** Creates the every-minute trigger. Run once. */
function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkSuspectAgents') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkSuspectAgents').timeBased().everyMinutes(1).create();
}

/** Read-only connectivity check: logs every logged-in agent and their state. */
function testConnection() {
  getRealTimeAgents_().forEach(function (a) {
    console.log(fullName_(a) + ' [' + a.agentId + '] ' + a.agentState + ' for ' + a.stateTime + 's');
  });
}
