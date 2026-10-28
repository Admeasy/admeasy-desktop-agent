const token = window.ADMEASY_TOKEN || "";
const $ = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

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
let menuOpen = false;
let state = null;
let bubbles = [];
let live = "";
const seenNotes = new Set();

function shell(inner, opts = {}) {
  const online = state && state.online;
  const chatClass = opts.chat ? " screen is-chat" : "";
  document.getElementById("app").replaceChildren($(`
    <div class="app">
      <header class="top">
        <div class="brand">
          <span class="mascot"><img src="https://admeasy.ai/mascot.svg" width="30" height="30" alt=""></span>
          <span class="brand-name">admeasy</span>
          <span class="dot ${online ? "on" : "off"}" title="${online ? "computer connected" : "computer offline"}"></span>
        </div>
        <button class="icon-btn" id="more" aria-label="menu">⋯</button>
      </header>
      ${menuOpen ? `<nav class="menu" id="menu">
        <button data-go="profile">profile</button>
        <button data-go="connections">connections</button>
        <button data-go="employees">employees</button>
        <button data-go="automations">automations</button>
        <button data-go="connectors">connectors</button>
        <button data-go="plan">plan</button>
        <button data-go="activity">activity</button>
        <button data-go="reminders">notifications</button>
      </nav>` : ""}
      <div class="screen${chatClass}">${inner}</div>
    </div>`));
  document.getElementById("more").onclick = () => { menuOpen = !menuOpen; draw(); };
  document.querySelectorAll("[data-go]").forEach((b) => {
    b.onclick = () => { screen = b.dataset.go; menuOpen = false; draw(); };
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

function chat() {
  const blocked = !state.perms_ready;
  shell(`
    ${threadHtml()}
    <form class="composer" id="say">
      <textarea id="text" rows="1" placeholder="${blocked ? "grant permissions before i act" : "message"}" ${blocked ? "disabled" : ""}></textarea>
      <button class="btn btn-primary" type="submit" ${blocked ? "disabled" : ""}>send</button>
    </form>`, { chat: true });
  const box = document.getElementById("thread");
  if (box) box.scrollTop = box.scrollHeight;
  document.querySelectorAll("[data-cmd]").forEach((b) => {
    b.onclick = () => openTerminal(b.dataset.cmd);
  });
  const form = document.getElementById("say");
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const text = document.getElementById("text").value.trim();
    if (!text) return;
    bubbles.push({ role: "user", text });
    document.getElementById("text").value = "";
    draw();
    try { await api("/api/chat", { text }); } catch (err) {
      bubbles.push({ role: "error", text: err.message });
      draw();
    }
  };
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
    <div class="card"><b>connect a computer</b>
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
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">employees</h2>
    <form class="card" id="new-emp">
      <label>name<input id="ename" required></label>
      <label>role<input id="erole" placeholder="research, ops…"></label>
      <label>instructions<textarea id="einstr" rows="3"></textarea></label>
      <button class="btn btn-dark" type="submit">create employee</button>
    </form>
    <div class="card" id="emp-list"><p class="muted">loading…</p></div>
    <p class="err" id="eerr"></p>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  const load = () => api("/api/backend/employees").then((data) => {
    const rows = (data.employees || data.items || []).map((e) =>
      `<div class="row"><span><b>${esc(e.name || e.id)}</b> <span class="muted">${esc(e.role || "")}</span></span>
        <button class="btn btn-light" data-runs="${esc(e.id)}">runs</button></div>`).join("")
      || `<p class="muted">no employees yet.</p>`;
    const el = document.getElementById("emp-list");
    if (el) el.innerHTML = rows;
    document.querySelectorAll("[data-runs]").forEach((b) => {
      b.onclick = async () => {
        try {
          const runs = await api(`/api/backend/employees/${b.dataset.runs}/runs`);
          const list = (runs.runs || []).slice(0, 5).map((r) => esc(r.status || r.id)).join(", ");
          document.getElementById("eerr").textContent = list ? `recent: ${list}` : "no runs yet — use automations to invoke a trigger.";
        } catch (err) { document.getElementById("eerr").textContent = err.message; }
      };
    });
  }).catch((err) => { document.getElementById("eerr").textContent = err.message; });
  load();
  document.getElementById("new-emp").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/backend/employees", {
        name: document.getElementById("ename").value,
        role: document.getElementById("erole").value,
        instructions: document.getElementById("einstr").value,
      });
      load();
    } catch (err) { document.getElementById("eerr").textContent = err.message; }
  };
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

function connectors() {
  shell(`
    <button class="back" id="back">← chat</button>
    <h2 class="screen-title">connectors</h2>
    <div class="card" id="conn-list"><p class="muted">loading…</p></div>
    <p class="err" id="coerr"></p>`);
  document.getElementById("back").onclick = () => { screen = "chat"; draw(); };
  api("/api/backend/connectors").then((data) => {
    const rows = (data.connections || data.items || data || []);
    const list = Array.isArray(rows) ? rows : [];
    const el = document.getElementById("conn-list");
    if (!el) return;
    el.innerHTML = list.map((c) =>
      `<div class="row"><span>${esc(c.name || c.provider || c.id)}</span>
        <span class="pill ${c.connected ? "pill-wa" : ""}">${c.connected ? "on" : "off"}</span></div>`).join("")
      || `<p class="muted">no oauth connections yet. connect accounts from the phone or web app.</p>`;
  }).catch((err) => { document.getElementById("coerr").textContent = err.message; });
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
    screen, menuOpen, bubbles, live,
    needs: state.needs_invite, onb: state.onboarding_complete,
    online: state.online, email: state.email,
    folders: state.folders, caps: state.capabilities,
    rems: state.reminders, ready: state.perms_ready,
    perms: state.permission_detail, err: state.error,
    audit: (state.audit || []).length,
  });
  if (key === paintKey && document.querySelector(".app")) return;
  paintKey = key;
  if (state.needs_invite) return invite();
  if (!state.onboarding_complete) return onboarding();
  if (screen === "profile") return profile();
  if (screen === "connections") return connections();
  if (screen === "plan") return plan();
  if (screen === "reminders") return reminders();
  if (screen === "employees") return employees();
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
