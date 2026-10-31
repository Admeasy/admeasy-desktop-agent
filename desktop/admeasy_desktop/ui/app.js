const token = window.ADMEASY_TOKEN || "";
const $ = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const HUB_NAV = [
  { id: "employees", label: "AI employees", icon: "11-bot" },
  { id: "schedules", label: "Schedules", icon: "18-info" },
  { id: "documents", label: "Documents", icon: "15-panel" },
  { id: "vault", label: "Vault", icon: "17-vault" },
  { id: "connectors", label: "Connectors", icon: "02-app-grid" },
];
const QUICK_PROMPTS = [
  "Summarise my unread emails",
  "What's on my calendar today?",
  "Draft a follow-up email for me",
  "Remind me what I should focus on today",
];
const HELP_URL = "https://admeasy.ai";
const hubIcon = (name) => `/icons/hand/${name}.png`;
const WORKSPACE_SCREENS = new Set(HUB_NAV.map((h) => h.id));
let wsPick = { employees: "", schedules: "", documents: "", connectors: "" };
let wsFilter = { employees: "all", schedules: "all", documents: "all" };

function hubNavHtml(active) {
  return `<div class="hub-nav-scroll"><nav class="hub-nav" aria-label="workspace">${HUB_NAV.map((h) =>
    `<button type="button" class="hub-nav-link${active === h.id ? " active" : ""}" data-go="${esc(h.id)}">
      <img src="${hubIcon(h.icon)}" width="18" height="18" alt="">
      <span>${esc(h.label)}</span>
    </button>`).join("")}</nav></div>`;
}

function linkStatusLabel() {
  if (!state) return "link off";
  if (state.settings && state.settings.paused) return "paused";
  return state.online ? "link on" : "link off";
}

function linkStatusOn() {
  return state && state.online && !(state.settings && state.settings.paused);
}

function topBarHtml() {
  const on = linkStatusOn();
  return `<header class="top">
    <div class="brand"><span class="brand-name">admeasy</span></div>
    <div class="top-actions">
      <button type="button" class="icon-btn icon-btn-ghost" id="help" aria-label="help">
        <img src="${hubIcon("18-info")}" width="20" height="20" alt="">
      </button>
      <a class="icon-btn icon-btn-ghost" href="${HELP_URL}" target="_blank" rel="noreferrer" aria-label="admeasy on the web">
        <span class="pill-wa keep-case" style="font-size:11px;font-weight:800">wa</span>
      </a>
      <span class="status-pill${on ? " on" : ""}" title="phone link to this computer">
        <span class="dot ${on ? "on" : "off"}"></span>${esc(linkStatusLabel())}
      </span>
      <button type="button" class="icon-btn icon-btn-ghost" id="settings-go" aria-label="settings">
        <img src="${hubIcon("16-settings")}" width="20" height="20" alt="">
      </button>
    </div>
  </header>`;
}

function bindTopBar() {
  const help = document.getElementById("help");
  if (help) help.onclick = () => { window.open(HELP_URL, "_blank", "noopener,noreferrer"); };
  const settingsGo = document.getElementById("settings-go");
  if (settingsGo) settingsGo.onclick = () => { screen = "settings"; draw(); };
}

function schedulePhase(task) {
  const st = task.status;
  if (st === "cancelled" || st === "completed") return "past";
  if (task.next_run_at) return "upcoming";
  if (task.last_run_at) return "recent";
  return "scheduled";
}

function workspaceShell(active, title, body, errId = "") {
  shell(`
    <div class="hub-page">
      ${hubNavHtml(active)}
      <h2 class="screen-title">${esc(title)}</h2>
      ${body}
      ${errId ? `<p class="err" id="${errId}"></p>` : ""}
      <div class="sheet-footer">
        <button type="button" class="btn btn-light btn-block" id="workspace-close">close</button>
      </div>
    </div>`, { settings: false });
  document.getElementById("workspace-close").onclick = () => { screen = "chat"; draw(); };
}

async function api(path, body, method) {
  const opts = { headers: { "X-Admeasy-Token": token } };
  if (body !== undefined) {
    opts.method = method || "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else {
    opts.method = method || "GET";
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || res.statusText);
  return data;
}

let screen = "chat";
let state = null;
let bubbles = [];
let live = "";
const seenNotes = new Set();

function shell(inner, opts = {}) {
  const chatClass = opts.chat ? " screen is-chat" : "";
  const settingsClass = opts.settings ? " screen-settings" : "";
  const heroClass = opts.hero ? " chat-with-hero" : "";
  document.getElementById("app").replaceChildren($(`
    <div class="app">
      ${topBarHtml()}
      <div class="screen${chatClass}${settingsClass}${heroClass}">${inner}</div>
    </div>`));
  bindTopBar();
  document.querySelectorAll("[data-go]").forEach((b) => {
    b.onclick = () => { screen = b.dataset.go; draw(); };
  });
}

function invite() {
  shell(`
    <p class="kicker">invite</p>
    <h2 class="screen-title">get in</h2>
    <p class="muted">same google account as your phone. an invite code is required unless this account already has one.</p>
    <form id="invite" class="card">
      <label>invite code<input id="code" type="text" autocomplete="off" placeholder="#1111"></label>
      <button class="btn btn-dark" type="submit">check code</button>
    </form>
    ${state.pending_invite ? `<button class="btn btn-primary btn-block" id="login">${state.logging_in ? "waiting for the browser…" : "continue with google"}</button>` : ""}
    <button class="btn btn-light" id="existing">i already have an account</button>
    <p class="err">${esc(state.error || "")}</p>`);
  document.getElementById("invite").onsubmit = async (ev) => {
    ev.preventDefault();
    await api("/api/invite", { code: document.getElementById("code").value });
    await refresh();
  };
  const login = document.getElementById("login");
  if (login) login.onclick = () => { api("/api/login", {}); setTimeout(refresh, 400); };
  document.getElementById("existing").onclick = () => { api("/api/login", { existing: true }); setTimeout(refresh, 400); };
}

function permRow(ok, label, which) {
  return `<div class="row"><span><span class="dot ${ok ? "on" : "off"}"></span> ${esc(label)}</span>
    ${ok ? `<span class="muted">granted</span>` : `<button class="btn btn-light" data-grant="${esc(which)}">grant</button>`}</div>`;
}

function onboarding() {
  const p = state.permission_detail || {};
  shell(`
    <p class="kicker">permissions</p>
    <h2 class="screen-title">before i act</h2>
    <p class="muted">admeasy stays idle until screen, accessibility, keyboard and mouse, and the clipboard are allowed. the phone can reach this computer only after that too, on a new install.</p>
    <div class="card">
      ${permRow(p.screen, "screen recording", "screen")}
      ${permRow(p.accessibility, "accessibility", "accessibility")}
      ${permRow(p.input, "keyboard and mouse", "accessibility")}
      ${permRow(p.clipboard, "clipboard", "clipboard")}
    </div>
    ${p.clipboard ? "" : `<button class="btn btn-light" id="skip-clip">clipboard isn't available on this machine</button>`}
    <p class="muted">${esc(p.platform_note || "")}</p>
    <button class="btn btn-dark" id="done" ${state.perms_ready ? "" : "disabled"}>continue</button>
    <p class="err">${esc(state.error || "")}</p>`);
  document.querySelectorAll("[data-grant]").forEach((b) => {
    b.onclick = async () => { await api("/api/open_settings", { which: b.dataset.grant }); };
  });
  const skip = document.getElementById("skip-clip");
  if (skip) skip.onclick = async () => { await api("/api/onboarding", { skip_clipboard: true }); await refresh(); };
  document.getElementById("done").onclick = async () => {
    await api("/api/onboarding", { complete: true });
    screen = "chat";
    await refresh();
  };
}

function threadHtml() {
  const rows = bubbles.map((b) => {
    const open = b.command ? `<div><button class="btn btn-light" data-cmd="${esc(b.command)}">open in terminal</button></div>` : "";
    return `<div class="bubble ${esc(b.role)}">${esc(b.text)}${open}</div>`;
  }).join("");
  const pending = live ? `<div class="bubble assistant">${esc(live)}</div>` : "";
  return `<div class="thread" id="thread">${rows}${pending}</div>`;
}

function homeHeroHtml() {
  const blocked = !state.perms_ready;
  const device = (state.settings && state.settings.device_name) || "this computer";
  const on = linkStatusOn();
  return `
    <div class="home-hero">
      <p class="hero-kicker">say "admeasy" or tap talk</p>
      <p class="hero-try muted">try: "find wireless earbuds under ₹2000"</p>
      <div class="mascot-hero" aria-hidden="true">
        <img src="https://admeasy.ai/mascot.svg" width="120" height="120" alt="">
      </div>
      <div class="status-pill status-pill-center${on ? " on" : ""}">
        <span class="dot ${on ? "on" : "off"}"></span>${esc(linkStatusLabel())}
      </div>
      <button type="button" class="btn btn-brand btn-block" id="talk-cta" ${blocked ? "disabled" : ""}>talk to admeasy</button>
      <div class="device-status ${on ? "online" : "offline"}">
        <img src="${hubIcon("01-computer")}" width="18" height="18" alt="">
        <span class="device-status-name keep-case">${esc(device)}</span>
        <span class="device-status-state">${on ? "online" : "offline"}</span>
      </div>
      <div class="suggestions" role="list">
        ${QUICK_PROMPTS.map((p) =>
    `<button type="button" class="suggestion-chip" data-suggest="${esc(p)}">${esc(p)}</button>`).join("")}
      </div>
    </div>`;
}

function wireComposer(blocked) {
  const form = document.getElementById("say");
  if (!form) return;
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const text = document.getElementById("text").value.trim();
    if (!text) return;
    await sendChat(text);
  };
  const talk = document.getElementById("talk-cta");
  if (talk) {
    talk.onclick = () => {
      const area = document.getElementById("text");
      if (area && !blocked) {
        area.focus();
        area.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    };
  }
  document.querySelectorAll("[data-suggest]").forEach((b) => {
    b.onclick = async () => {
      if (blocked) return;
      await sendChat(b.dataset.suggest);
    };
  });
}

async function sendChat(text) {
  bubbles.push({ role: "user", text });
  const area = document.getElementById("text");
  if (area) area.value = "";
  draw();
  try {
    await api("/api/chat", { text });
  } catch (err) {
    bubbles.push({ role: "error", text: err.message });
    draw();
  }
}

function chat() {
  const blocked = !state.perms_ready;
  const showHero = bubbles.length === 0 && !live;
  shell(`
    ${showHero ? homeHeroHtml() : ""}
    ${!showHero || live ? threadHtml() : ""}
    <form class="composer" id="say">
      <textarea id="text" rows="1" placeholder="${blocked ? "grant permissions before i act" : "message admeasy…"}" ${blocked ? "disabled" : ""}></textarea>
      <button class="btn btn-brand" type="submit" ${blocked ? "disabled" : ""}>send</button>
    </form>`, { chat: true, hero: showHero });
  const box = document.getElementById("thread");
  if (box) box.scrollTop = box.scrollHeight;
  document.querySelectorAll("[data-cmd]").forEach((b) => {
    b.onclick = () => openTerminal(b.dataset.cmd);
  });
  wireComposer(blocked);
}

async function openTerminal(command) {
  try {
    const job = await api("/api/terminal-jobs", { command });
    if (job.url) window.location.href = job.url;
  } catch (err) {
    bubbles.push({ role: "error", text: err.message });
    draw();
  }
}

function settingsScreen() {
  const email = state.email || "";
  const initial = email ? email.trim()[0].toUpperCase() : "?";
  const ent = state.entitlements || {};
  const usage = ent.usage || {};
  const planName = ent.plan_name || ent.plan || "your plan";
  const usageLine = usage.remaining == null
    ? ""
    : `${usage.remaining}${usage.limit == null ? "" : ` of ${usage.limit}`} computer actions left`;
  shell(`
    <h2 class="screen-title">settings</h2>
    <p class="screen-lead muted">your account, assistant and connected apps</p>
    <span class="section-label">account</span>
    <div class="settings-card">
      <div class="account-head">
        <span class="avatar keep-case" aria-hidden="true">${esc(initial)}</span>
        <div>
          <div class="muted fine">signed in</div>
          <div class="account-email keep-case">${esc(email || "signed out")}</div>
        </div>
      </div>
      <div class="nav-chip-row">
        <button type="button" class="nav-chip" data-go="activity">activity &amp; history</button>
        <button type="button" class="nav-chip" data-go="employees">employees &amp; docs</button>
        <button type="button" class="nav-chip" data-go="connections">your computers</button>
      </div>
      <button type="button" class="sign-out-btn" id="settings-out">sign out</button>
    </div>
    <span class="section-label">assistant</span>
    <div class="settings-card">
      <div class="settings-row">
        <div>
          <div class="plan-price">default assistant</div>
          <p class="plan-blurb muted">this computer runs admeasy for your phone and whatsapp.</p>
        </div>
        <button type="button" class="btn btn-secondary" id="open-profile">manage</button>
      </div>
    </div>
    <span class="section-label">pro plan</span>
    <div class="settings-card">
      <div class="plan-price keep-case">${esc(planName)}</div>
      <p class="plan-blurb muted">${esc(usageLine || ent.tagline || "plan details sync when you are online.")}</p>
      <button type="button" class="btn btn-light btn-block" style="margin-top:12px" data-go="plan">view billing</button>
    </div>
    <div class="settings-footer">
      <button type="button" class="btn btn-brand btn-block" id="settings-done">done</button>
    </div>`, { settings: true });
  document.getElementById("settings-done").onclick = () => { screen = "chat"; draw(); };
  document.getElementById("open-profile").onclick = () => { screen = "profile"; draw(); };
  document.getElementById("settings-out").onclick = async () => {
    await api("/api/logout", {});
    screen = "chat";
    await refresh();
  };
  document.querySelectorAll(".settings-card [data-go]").forEach((b) => {
    b.onclick = () => { screen = b.dataset.go; draw(); };
  });
}

function profile() {
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">profile</h2>
    <div class="card">
      <div class="row"><span class="muted">account</span><span>${esc(state.email || "signed out")}</span></div>
      <div class="row"><span class="muted">this computer</span><span>${esc(state.settings.device_name || "")}</span></div>
      <div class="row"><span class="muted">phone link</span><span class="pill ${state.online ? "pill-wa" : ""}">${state.online ? "connected" : esc(state.detail || "offline")}</span></div>
    </div>
    <button class="btn btn-disconnect btn-block" id="out">sign out and remove this computer</button>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  document.getElementById("out").onclick = async () => { await api("/api/logout", {}); screen = "chat"; await refresh(); };
}

function toggle(name, on) {
  return `<div class="row"><span>${esc(name)}</span>
    <input type="checkbox" data-cap="${esc(name)}" ${on ? "checked" : ""}></div>`;
}

function connections() {
  const caps = state.capabilities || {};
  const folders = (state.folders || []).map((p) =>
    `<div class="row"><span class="mono">${esc(p)}</span><button class="btn btn-light" data-revoke="${esc(p)}">revoke</button></div>`).join("")
    || `<p class="muted">no folders yet. admeasy cannot see the rest of the disk.</p>`;
  const install = state.install || {};
  const audit = (state.audit || []).slice(-12).reverse().map((row) =>
    `<div class="muted">${esc(row.kind)} · ${esc(row.status)} · ${esc(row.summary || "")}</div>`).join("") || `<p class="muted">nothing recorded yet.</p>`;
  const devs = (state.devices || []).map((d) =>
    `<div class="row"><span>${esc(d.name)} <span class="muted">${esc(d.platform)}</span></span><span class="muted">${d.online ? "online" : "offline"}</span></div>`).join("");
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">connections</h2>
    <div class="card"><b>this computer</b>${devs || `<p class="muted">${state.online ? "connected" : "not enrolled yet"}</p>`}</div>
    <div class="card"><b>what this computer may do</b>
      ${toggle("shell", caps.shell)}
      ${toggle("files", caps.files)}
      ${toggle("screen", caps.screen)}
      ${toggle("input", caps.input)}
      ${toggle("browser", caps.browser)}
      ${toggle("notify", caps.notify)}
    </div>
    <div class="card"><b>folders</b>
      ${folders}
      <button class="btn btn-dark" id="pick">approve a folder</button>
      <form id="add-folder"><label>or type a path<input id="fpath" type="text" placeholder="/Users/me/Projects"></label>
        <button class="btn btn-light" type="submit">approve path</button></form>
    </div>
    <div class="card"><b>commands</b>
      <label>always allow, one per line<textarea id="allow" rows="3">${esc((state.settings.command_allowlist || []).join("\n"))}</textarea></label>
      <label>never allow (cannot be overridden)<textarea id="block" rows="3">${esc((state.settings.command_blocklist || []).join("\n"))}</textarea></label>
      <button class="btn btn-dark" id="save-cmds">save lists</button>
    </div>
    <div class="card"><b>install on another computer</b>
      <p class="muted">share the download link — do not ask friends to paste terminal commands.</p>
      <a class="btn btn-primary btn-block" href="${esc(install.releases_page || "https://github.com/Admeasy/admeasy-desktop-agent/releases")}" target="_blank" rel="noreferrer">download admeasy</a>
      ${install.download_macos ? `<a class="btn btn-light btn-block" href="${esc(install.download_macos)}" target="_blank" rel="noreferrer">macos .dmg (this version)</a>` : ""}
      <p class="muted small">first open on mac: if blocked, go to system settings → privacy &amp; security → open anyway.</p>
    </div>
    <div class="card"><b>advanced: terminal install</b>
      <p class="muted">${esc(install.note || "")}</p>
      ${install.code ? `<div class="row"><span class="pill pill-wa keep-case">pair ${esc(install.code)}</span>
        <button class="btn btn-light" type="button" id="refresh-pair">new code</button></div>` : ""}
      <div class="install mono" id="cmd-mac">${esc(install.macos || "")}</div>
      <button class="btn btn-light" id="copy-mac">copy macos / linux</button>
      <div class="install mono" id="cmd-win">${esc(install.windows || "")}</div>
      <button class="btn btn-light" id="copy-win">copy windows</button>
      <button class="btn btn-light" id="handler">register admeasy:// on this computer</button>
    </div>
    <div class="card"><b>audit</b>${audit}</div>
    <p class="err" id="cerr"></p>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  document.querySelectorAll("[data-cap]").forEach((box) => {
    box.onchange = async () => {
      const body = {};
      body[box.dataset.cap] = box.checked;
      await api("/api/capabilities", body);
    };
  });
  document.querySelectorAll("[data-revoke]").forEach((b) => {
    b.onclick = async () => { await api("/api/folders/revoke", { path: b.dataset.revoke }); await refresh(); };
  });
  document.getElementById("pick").onclick = async () => {
    try { await api("/api/folders/pick", {}); await refresh(); }
    catch (err) { document.getElementById("cerr").textContent = err.message; }
  };
  document.getElementById("add-folder").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/folders", { path: document.getElementById("fpath").value });
      await refresh();
    } catch (err) { document.getElementById("cerr").textContent = err.message; }
  };
  document.getElementById("save-cmds").onclick = async () => {
    const lines = (id) => document.getElementById(id).value.split("\n").map((s) => s.trim()).filter(Boolean);
    await api("/api/commands", { allowlist: lines("allow"), blocklist: lines("block") });
  };
  document.getElementById("copy-mac").onclick = () => navigator.clipboard.writeText(install.macos || "");
  document.getElementById("copy-win").onclick = () => navigator.clipboard.writeText(install.windows || "");
  document.getElementById("handler").onclick = () => api("/api/register-handler", {});
  const rp = document.getElementById("refresh-pair");
  if (rp) rp.onclick = async () => {
    try {
      await api("/api/backend/pair-code", {});
      await refresh();
    } catch (err) { document.getElementById("cerr").textContent = err.message; }
  };
}

function plan() {
  const ent = state.entitlements || {};
  const usage = ent.usage || {};
  const upgrade = ent.upgrade_url || "https://admeasy.ai";
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">plan</h2>
    <div class="card">
      <div class="row"><span class="muted">plan</span><span>${esc(ent.plan_name || ent.plan || "—")}</span></div>
      <div class="row"><span class="muted">computer actions</span><span>${usage.remaining == null ? "—" : esc(usage.remaining)}${usage.limit == null ? "" : ` of ${esc(usage.limit)}`}</span></div>
      <a class="btn btn-dark" href="${esc(upgrade)}" target="_blank" rel="noreferrer">upgrade</a>
    </div>
    <div class="card" id="billing-extra"><p class="muted">loading billing…</p></div>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  api("/api/backend/billing/status").then((b) => {
    const el = document.getElementById("billing-extra");
    if (!el) return;
    el.innerHTML = `<b>billing</b>
      <div class="row"><span class="muted">status</span><span>${esc(b.status || b.state || "—")}</span></div>
      ${b.plan_id ? `<div class="row"><span class="muted">plan id</span><span class="mono keep-case">${esc(b.plan_id)}</span></div>` : ""}`;
  }).catch((err) => {
    const el = document.getElementById("billing-extra");
    if (el) el.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  });
}

function reminders() {
  const rows = (state.reminders || []).map((r) =>
    `<div class="row"><span>${esc(r.text)} <span class="pill">${esc(r.status)} · ${esc(r.at)}</span></span>
      ${r.status === "scheduled" ? `<button class="btn btn-light" data-cancel="${esc(r.id)}">cancel</button>` : ""}</div>`).join("")
    || `<p class="muted">no reminders yet.</p>`;
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">notifications</h2>
    <p class="muted">reminders sync with the backend. this computer toasts when one is due (tunnel or web push).</p>
    <form class="card" id="rem">
      <label>remind me<textarea id="rtext" rows="2"></textarea></label>
      <label>when<input id="rat" type="datetime-local"></label>
      <button class="btn btn-dark" type="submit">save reminder</button>
    </form>
    <div class="card">${rows}</div>
    <button class="btn btn-secondary btn-block" id="enable-push">allow notifications in this window</button>
    <p class="err" id="rerr"></p>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  document.getElementById("rem").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/reminders", { text: document.getElementById("rtext").value, at: document.getElementById("rat").value });
      await refresh();
    } catch (err) { document.getElementById("rerr").textContent = err.message; }
  };
  document.querySelectorAll("[data-cancel]").forEach((b) => {
    b.onclick = async () => { await api("/api/reminders/cancel", { id: b.dataset.cancel }); await refresh(); };
  });
  document.getElementById("enable-push").onclick = () => registerPush().catch((err) => {
    document.getElementById("rerr").textContent = err.message;
  });
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

async function registerPush() {
  if (!("Notification" in window)) throw new Error("notifications are not supported here");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("notifications were blocked");
  if (!("serviceWorker" in navigator)) throw new Error("service worker unavailable");
  const reg = await navigator.serviceWorker.register("/sw.js");
  const vapid = await api("/api/backend/push/vapid-public-key");
  const key = vapid.public_key || vapid.key;
  if (!key) throw new Error("backend did not return a vapid key");
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });
  const json = sub.toJSON();
  await api("/api/backend/push/web", {
    endpoint: json.endpoint,
    keys: json.keys,
    client: "desktop",
  });
}

function employees() {
  const filt = wsFilter.employees;
  workspaceShell("employees", "AI employees", `
    <div class="hub-toolbar">
      <label>status
        <select id="emp-filter">
          <option value="all"${filt === "all" ? " selected" : ""}>all</option>
          <option value="active"${filt === "active" ? " selected" : ""}>active</option>
          <option value="paused"${filt === "paused" ? " selected" : ""}>paused</option>
        </select>
      </label>
    </div>
    <div class="hub-split">
      <div><ul class="hub-list" id="emp-list"><li class="muted">loading…</li></ul>
        <form class="card hub-upload" id="new-emp">
          <label>name<input id="ename" required></label>
          <label>role<input id="erole" placeholder="research, ops…"></label>
          <label>instructions<textarea id="einstr" rows="3"></textarea></label>
          <button class="btn btn-dark" type="submit">create employee</button>
        </form>
      </div>
      <div class="card hub-detail" id="emp-detail"><p class="muted hub-detail-placeholder">select an employee</p></div>
    </div>`, "eerr");

  const errEl = () => document.getElementById("eerr");
  const paintDetail = async (id) => {
    wsPick.employees = id;
    const box = document.getElementById("emp-detail");
    if (!box || !id) return;
    box.innerHTML = `<p class="muted">loading…</p>`;
    try {
      const [detail, runs] = await Promise.all([
        api(`/api/backend/employees/${encodeURIComponent(id)}`),
        api(`/api/backend/employees/${encodeURIComponent(id)}/runs`),
      ]);
      const skills = (detail.skills || []).map((s) => esc(typeof s === "string" ? s : s.name || s.slug || "")).join(", ");
      const runRows = (runs.runs || []).slice(0, 12).map((r) =>
        `<li><span>${esc(r.status || r.id)}</span><span class="hub-meta">${esc(r.created_at || r.started_at || "")}</span></li>`).join("")
        || `<li class="muted">no runs yet</li>`;
      box.innerHTML = `
        <h3>${esc(detail.name || id)}</h3>
        <p class="hub-meta">${esc(detail.role || "")} · ${esc(detail.status || "active")}</p>
        <p class="hub-pre">${esc(detail.instructions || detail.system_prompt || "")}</p>
        ${skills ? `<p><b>skills</b> ${skills}</p>` : ""}
        <b>recent runs</b>
        <ul class="hub-runs">${runRows}</ul>`;
    } catch (err) {
      box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  };

  const loadList = () => api("/api/backend/employees").then((data) => {
    let rows = data.employees || data.items || [];
    if (filt !== "all") rows = rows.filter((e) => (e.status || "active") === filt);
    const el = document.getElementById("emp-list");
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = `<li><div class="empty-state">
        <img src="${hubIcon("11-bot")}" width="40" height="40" alt="">
        <p>no ai employees yet. create one below to get started.</p>
      </div></li>`;
      return;
    }
    el.innerHTML = rows.map((e) =>
      `<li><button type="button" class="hub-list-btn${wsPick.employees === e.id ? " active" : ""}" data-pick="${esc(e.id)}">
        <img src="${hubIcon("11-bot")}" width="22" height="22" alt="">
        <span><strong>${esc(e.name || e.id)}</strong>
          <span class="hub-meta">${esc(e.role || "")} · ${esc(e.status || "active")}</span></span>
      </button></li>`).join("");
    document.querySelectorAll("[data-pick]").forEach((b) => {
      b.onclick = () => paintDetail(b.dataset.pick);
    });
    if (wsPick.employees && rows.some((r) => r.id === wsPick.employees)) paintDetail(wsPick.employees);
  }).catch((err) => { if (errEl()) errEl().textContent = err.message; });

  const ef = document.getElementById("emp-filter");
  if (ef) ef.onchange = () => { wsFilter.employees = ef.value; draw(); };
  loadList();
  const form = document.getElementById("new-emp");
  if (form) form.onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/backend/employees", {
        name: document.getElementById("ename").value,
        role: document.getElementById("erole").value,
        instructions: document.getElementById("einstr").value,
      });
      loadList();
    } catch (err) { if (errEl()) errEl().textContent = err.message; }
  };
}

function schedules() {
  const filt = wsFilter.schedules;
  workspaceShell("schedules", "scheduled work", `
    <div class="hub-toolbar">
      <label>phase
        <select id="sched-filter">
          <option value="all"${filt === "all" ? " selected" : ""}>all</option>
          <option value="upcoming"${filt === "upcoming" ? " selected" : ""}>upcoming</option>
          <option value="recent"${filt === "recent" ? " selected" : ""}>recent</option>
          <option value="past"${filt === "past" ? " selected" : ""}>completed</option>
        </select>
      </label>
    </div>
    <div class="hub-split">
      <ul class="hub-list" id="sched-list"><li class="muted">loading…</li></ul>
      <div class="card hub-detail" id="sched-detail"><p class="muted hub-detail-placeholder">select a schedule</p></div>
    </div>`, "serr");

  const errEl = () => document.getElementById("serr");
  const paintDetail = async (id) => {
    wsPick.schedules = id;
    const box = document.getElementById("sched-detail");
    if (!box || !id) return;
    box.innerHTML = `<p class="muted">loading…</p>`;
    try {
      const detail = await api(`/api/backend/schedules/${encodeURIComponent(id)}`);
      const runs = (detail.runs || []).map((r) => {
        const ok = (r.status || "").toLowerCase() === "ok" || r.success === true;
        const icon = ok ? "08-thumbs-up" : "07-thumbs-down";
        return `<li class="row">
          <span><img src="${hubIcon(icon)}" width="18" height="18" alt=""> ${esc(r.status || r.id)}</span>
          <span class="hub-meta">${esc(r.started_at || r.created_at || "")}</span>
        </li>`;
      }).join("") || `<li class="muted">no runs yet</li>`;
      box.innerHTML = `
        <h3>${esc(detail.name || detail.title || id)}</h3>
        <p class="hub-meta">cron: <span class="mono keep-case">${esc(detail.cron || detail.schedule || "—")}</span></p>
        <p class="hub-meta">next: ${esc(detail.next_run_at || "—")} · last: ${esc(detail.last_run_at || "—")}</p>
        <b>runs</b>
        <ul class="hub-runs">${runs}</ul>`;
    } catch (err) {
      box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  };

  api("/api/backend/schedules").then((data) => {
    let tasks = data.tasks || data.schedules || data.items || [];
    if (filt !== "all") tasks = tasks.filter((t) => schedulePhase(t) === filt || (filt === "past" && schedulePhase(t) === "past"));
    const el = document.getElementById("sched-list");
    if (!el) return;
    if (!tasks.length) {
      el.innerHTML = `<li class="muted">no schedules yet.</li>`;
      return;
    }
    el.innerHTML = tasks.map((t) =>
      `<li><button type="button" class="hub-list-btn" data-pick="${esc(t.id)}">
        <img src="${hubIcon("18-info")}" width="22" height="22" alt="">
        <span><strong>${esc(t.name || t.title || t.id)}</strong>
          <span class="hub-meta">${esc(schedulePhase(t))} · next ${esc(t.next_run_at || "—")}</span></span>
      </button></li>`).join("");
    document.querySelectorAll("#sched-list [data-pick]").forEach((b) => {
      b.onclick = () => paintDetail(b.dataset.pick);
    });
  }).catch((err) => { if (errEl()) errEl().textContent = err.message; });

  const sf = document.getElementById("sched-filter");
  if (sf) sf.onchange = () => { wsFilter.schedules = sf.value; draw(); };
}

function documents() {
  const filt = wsFilter.documents;
  workspaceShell("documents", "documents & playbooks", `
    <div class="hub-toolbar">
      <label>source
        <select id="doc-filter">
          <option value="all"${filt === "all" ? " selected" : ""}>all</option>
          <option value="ai"${filt === "ai" ? " selected" : ""}>AI generated</option>
          <option value="upload"${filt === "upload" ? " selected" : ""}>uploaded</option>
        </select>
      </label>
    </div>
    <div class="hub-split">
      <div><ul class="hub-list" id="doc-list"><li class="muted">loading…</li></ul>
        <form class="card hub-upload" id="doc-up">
          <label>title<input id="d-title" required></label>
          <label>text / markdown<textarea id="d-text" rows="4" required></textarea></label>
          <button class="btn btn-dark" type="submit">upload document</button>
        </form>
      </div>
      <div class="card hub-detail" id="doc-detail"><p class="muted hub-detail-placeholder">select a document</p></div>
    </div>`, "derr");

  const errEl = () => document.getElementById("derr");
  const paintDetail = async (id) => {
    wsPick.documents = id;
    const box = document.getElementById("doc-detail");
    if (!box || !id) return;
    box.innerHTML = `<p class="muted">loading…</p>`;
    try {
      const doc = await api(`/api/backend/kb/documents/${encodeURIComponent(id)}`);
      const chunks = (doc.chunks || []).slice(0, 8).map((c, i) => {
        const emb = c.embedding || c.embedding_preview || [];
        const preview = Array.isArray(emb) ? emb.slice(0, 8).map((x) => Number(x).toFixed(3)).join(", ") : "";
        const dim = c.embedding_dim || c.dimension || (Array.isArray(emb) ? emb.length : doc.embedding_dim);
        return `<li><p class="hub-pre">${esc((c.text || c.content || "").slice(0, 400))}</p>
          ${preview ? `<p class="hub-meta mono keep-case">emb[0:8]: ${preview}${dim ? ` · dim ${dim}` : ""}</p>` : ""}</li>`;
      }).join("") || `<li class="muted">no chunks</li>`;
      box.innerHTML = `
        <h3>${esc(doc.title || id)}</h3>
        <p class="hub-meta">${doc.ai_generated ? "AI playbook" : "upload"} · ${esc(doc.kind || "")}</p>
        <ul class="hub-runs">${chunks}</ul>`;
    } catch (err) {
      box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  };

  const loadList = () => api("/api/backend/kb/documents").then((data) => {
    let docs = data.documents || data.items || [];
    if (filt === "ai") docs = docs.filter((d) => d.ai_generated);
    if (filt === "upload") docs = docs.filter((d) => !d.ai_generated);
    const el = document.getElementById("doc-list");
    if (!el) return;
    if (!docs.length) {
      el.innerHTML = `<li class="muted">no documents yet.</li>`;
      return;
    }
    el.innerHTML = docs.map((d) =>
      `<li><button type="button" class="hub-list-btn" data-pick="${esc(d.id)}">
        <img src="${hubIcon("15-panel")}" width="22" height="22" alt="">
        <span><strong>${esc(d.title || d.id)}</strong>
          <span class="hub-meta">${d.ai_generated ? "AI" : "upload"} · ${esc((d.playbook || d.summary || "").slice(0, 80))}</span></span>
      </button></li>`).join("");
    document.querySelectorAll("#doc-list [data-pick]").forEach((b) => {
      b.onclick = () => paintDetail(b.dataset.pick);
    });
  }).catch((err) => { if (errEl()) errEl().textContent = err.message; });

  const df = document.getElementById("doc-filter");
  if (df) df.onchange = () => { wsFilter.documents = df.value; draw(); };
  loadList();
  const form = document.getElementById("doc-up");
  if (form) form.onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/backend/kb/documents/upload", {
        title: document.getElementById("d-title").value,
        text: document.getElementById("d-text").value,
        kind: "markdown",
        ai_generated: false,
      });
      loadList();
    } catch (err) { if (errEl()) errEl().textContent = err.message; }
  };
}

function vaultScreen() {
  workspaceShell("vault", "vault", `
    <div id="vault-grid" class="vault-grid"><p class="muted">loading…</p></div>
    <div class="card" id="vault-creds"><b>saved credentials</b><p class="muted">loading…</p></div>`, "verr");

  const errEl = () => document.getElementById("verr");
  api("/api/backend/vault/overview").then((data) => {
    const sites = data.sites || data.domains || [];
    const grid = document.getElementById("vault-grid");
    if (grid) {
      grid.innerHTML = sites.length ? sites.map((s) => {
        const host = s.host || s.domain || s.site || "";
        const icon = s.icon_url || s.favicon_url || "";
        const sess = s.session_active || s.session_present;
        return `<div class="vault-tile">
          ${icon ? `<img src="${esc(icon)}" width="32" height="32" alt="">` : `<img src="${hubIcon("17-vault")}" width="32" height="32" alt="">`}
          <div><strong class="keep-case">${esc(host)}</strong>
            <span class="hub-meta">${s.credentials_saved ? "credentials saved" : "no password saved"} · ${sess ? "session active" : "signed out"}</span></div>
        </div>`;
      }).join("") : `<p class="muted">no sites in vault yet.</p>`;
    }
    const creds = data.credentials || [];
    const cel = document.getElementById("vault-creds");
    if (cel) {
      cel.innerHTML = `<b>saved credentials</b>` + (creds.length ? creds.map((c) =>
        `<div class="row"><span>${esc(c.label || c.site || c.host || "credential")}</span>
          ${c.sign_in_url ? `<a class="btn btn-light keep-case" href="${esc(c.sign_in_url)}" target="_blank" rel="noreferrer">sign in</a>` : `<span class="muted">saved</span>`}
        </div>`).join("") : `<p class="muted">no labeled credentials yet.</p>`);
    }
  }).catch((err) => { if (errEl()) errEl().textContent = err.message; });
}

function connectors() {
  workspaceShell("connectors", "connectors", `
    <div class="card" id="conn-list"><p class="muted">loading catalog…</p></div>
    <div class="card hub-detail" id="conn-detail"></div>`, "coerr");

  const errEl = () => document.getElementById("coerr");
  const paintDetail = async (slug) => {
    wsPick.connectors = slug;
    const box = document.getElementById("conn-detail");
    if (!box || !slug) return;
    box.innerHTML = `<p class="muted">loading ${esc(slug)}…</p>`;
    try {
      const c = await api(`/api/backend/mcp/connectors/${encodeURIComponent(slug)}`);
      const tools = c.tools || c.cached_tools || [];
      const toolList = tools.length ? `<details open><summary>${tools.length} tools</summary><ul class="hub-runs">${tools.map((t) =>
        `<li><strong>${esc(t.name || t.slug)}</strong><span class="hub-meta">${esc(t.description || "")}</span></li>`).join("")}</ul></details>`
        : `<p class="muted">no tools cached</p>`;
      const health = c.health || c.health_status || (c.connected ? "connected" : "unknown");
      const url = c.server_url || c.mcp_server_url || "";
      box.innerHTML = `
        <h3>${esc(c.name || slug)}</h3>
        <p class="hub-meta">health: ${esc(health)} · tools: ${esc(c.tool_count ?? tools.length)}</p>
        ${url ? `<p><a class="keep-case" href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a></p>` : ""}
        ${toolList}
        ${c.needs_reauth ? `<button class="btn btn-dark" id="reauth">reconnect</button>` : ""}`;
      const ra = document.getElementById("reauth");
      if (ra) ra.onclick = async () => {
        try {
          const r = await api(`/api/backend/mcp/connect/${encodeURIComponent(slug)}`, {});
          if (r.url) window.open(r.url, "_blank");
          else if (r.auth_url) window.open(r.auth_url, "_blank");
        } catch (err) { if (errEl()) errEl().textContent = err.message; }
      };
    } catch (err) {
      box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  };

  Promise.all([
    api("/api/backend/mcp/catalog"),
    api("/api/backend/mcp/installed").catch(() => ({ installed: [] })),
  ]).then(([catalog, installed]) => {
    const slugs = new Set((installed.installed || installed.connectors || []).map((x) => x.slug || x.id));
    const items = catalog.catalog || catalog.items || catalog.servers || catalog || [];
    const list = Array.isArray(items) ? items : [];
    const el = document.getElementById("conn-list");
    if (!el) return;
    el.innerHTML = list.map((c) => {
      const slug = c.slug || c.id || c.name;
      const on = slugs.has(slug) || c.installed || c.connected;
      return `<button type="button" class="hub-list-btn" data-slug="${esc(slug)}" style="width:100%;margin-bottom:8px">
        <img src="${hubIcon("02-app-grid")}" width="22" height="22" alt="">
        <span><strong>${esc(c.name || slug)}</strong>
          <span class="hub-meta">${on ? "connected" : "not connected"} · ${esc(c.description || "").slice(0, 60)}</span></span>
      </button>`;
    }).join("") || `<p class="muted">no connectors in catalog.</p>`;
    document.querySelectorAll("[data-slug]").forEach((b) => {
      b.onclick = () => paintDetail(b.dataset.slug);
    });
  }).catch((err) => { if (errEl()) errEl().textContent = err.message; });
}

function automations() {
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">automations</h2>
    <p class="muted">schedule or run triggers tied to an employee (same as the phone app).</p>
    <form class="card" id="new-tr">
      <label>employee id<input id="t-emp" placeholder="from employees screen"></label>
      <label>name<input id="t-name" placeholder="daily standup"></label>
      <button class="btn btn-dark" type="submit">create trigger</button>
    </form>
    <div class="card" id="tr-list"><p class="muted">load an employee to see triggers…</p></div>
    <p class="err" id="terr"></p>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  const paintTriggers = (employee) => {
    const triggers = employee.triggers || [];
    const el = document.getElementById("tr-list");
    if (!el) return;
    el.innerHTML = triggers.map((t) =>
      `<div class="row"><span>${esc(t.name || t.id)}</span>
        <button class="btn btn-light" data-fire="${esc(t.id)}">run now</button></div>`).join("")
      || `<p class="muted">no triggers on this employee.</p>`;
    document.querySelectorAll("[data-fire]").forEach((b) => {
      b.onclick = async () => {
        try { await api(`/api/backend/triggers/${b.dataset.fire}/run`, {}); }
        catch (err) { document.getElementById("terr").textContent = err.message; }
      };
    });
  };
  api("/api/backend/employees").then((data) => {
    const first = (data.employees || [])[0];
    if (first && first.id) {
      document.getElementById("t-emp").value = first.id;
      return api(`/api/backend/employees/${first.id}`).then(paintTriggers);
    }
    return null;
  }).catch(() => {});
  document.getElementById("new-tr").onsubmit = async (ev) => {
    ev.preventDefault();
    const employee_id = document.getElementById("t-emp").value.trim();
    try {
      await api("/api/backend/triggers", { employee_id, name: document.getElementById("t-name").value });
      if (employee_id) {
        const detail = await api(`/api/backend/employees/${employee_id}`);
        paintTriggers(detail);
      }
    } catch (err) { document.getElementById("terr").textContent = err.message; }
  };
}

function activity() {
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">activity</h2>
    <div class="card" id="act-list"><p class="muted">loading…</p></div>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  api("/api/backend/activity").then((data) => {
    const rows = (data.items || data.activity || data.events || data || []);
    const list = Array.isArray(rows) ? rows : [];
    const el = document.getElementById("act-list");
    if (!el) return;
    el.innerHTML = list.slice(0, 30).map((row) =>
      `<div class="muted">${esc(row.created_at || row.at || "")} · ${esc(row.kind || row.type || "event")} · ${esc(row.summary || row.text || "")}</div>`).join("")
      || `<p class="muted">nothing logged yet.</p>`;
  }).catch((err) => {
    const el = document.getElementById("act-list");
    if (el) el.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  });
}

let paintKey = "";
function draw() {
  if (!state) return;
  const key = JSON.stringify({
    screen, bubbles, live,
    needs: state.needs_invite, onb: state.onboarding_complete,
    online: state.online, email: state.email,
    folders: state.folders, caps: state.capabilities,
    rems: state.reminders, ready: state.perms_ready,
    perms: state.permission_detail, err: state.error,
    audit: (state.audit || []).length,
    ws: wsPick, wsf: wsFilter,
    paused: state.settings && state.settings.paused,
  });
  if (key === paintKey && document.querySelector(".app")) return;
  paintKey = key;
  if (state.needs_invite) return invite();
  if (!state.onboarding_complete) return onboarding();
  if (screen === "settings") return settingsScreen();
  if (screen === "profile") return profile();
  if (screen === "connections") return connections();
  if (screen === "plan") return plan();
  if (screen === "reminders") return reminders();
  if (screen === "employees") return employees();
  if (screen === "schedules") return schedules();
  if (screen === "documents") return documents();
  if (screen === "vault") return vaultScreen();
  if (screen === "automations") return automations();
  if (screen === "connectors") return connectors();
  if (screen === "activity") return activity();
  return chat();
}

async function refresh() {
  state = await api("/api/state");
  if (state.needs_invite) screen = "chat";
  draw();
}

async function pollLive() {
  try {
    const liveData = await api("/api/live");
    (liveData.events || []).forEach((ev) => {
      if (ev.type === "live") live = ev.text || "";
      else if (ev.type === "final") {
        live = "";
        (ev.bubbles || []).forEach((text) => bubbles.push({ role: "assistant", text }));
      } else if (ev.type === "error") {
        bubbles.push({ role: "error", text: ev.text || "error" });
      } else if (ev.type === "note") {
        const key = ev.text + (ev.command || "");
        if (!seenNotes.has(key)) {
          seenNotes.add(key);
          bubbles.push({ role: "note", text: ev.text, command: ev.command || "" });
        }
      }
    });
    (liveData.feed || []).forEach((row) => {
      const key = "feed:" + (row.text || "");
      if (row.text && !seenNotes.has(key)) {
        seenNotes.add(key);
        bubbles.push({ role: "note", text: row.text });
      }
    });
    (liveData.notices || []).forEach((row) => {
      const body = row.text || "reminder";
      if (seenNotes.has("n:" + row.id)) return;
      seenNotes.add("n:" + row.id);
      bubbles.push({ role: "assistant", text: body });
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("admeasy", { body });
      }
    });
    if (screen === "chat" || screen === "reminders" || screen === "connections") draw();
  } catch (err) { /* keep the last screen */ }
}

async function loadHistory() {
  try {
    const hist = await api("/api/chat/history");
    if (hist.messages && hist.messages.length && bubbles.length === 0) {
      bubbles = hist.messages.map((m) => ({ role: m.role === "user" ? "user" : "assistant", text: m.text }));
    }
    if (hist.error && bubbles.every((b) => b.role !== "error")) {
      bubbles.push({ role: "error", text: hist.error });
    }
    draw();
  } catch (err) {
    bubbles.push({ role: "error", text: err.message });
  }
}

refresh().then(loadHistory);
setInterval(refresh, 8000);
setInterval(pollLive, 1200);
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
