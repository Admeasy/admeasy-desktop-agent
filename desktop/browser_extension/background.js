const HOST = "com.admeasy.desktop";
let nativePort = null;

function connectNative() {
  try {
    nativePort = chrome.runtime.connectNative(HOST);
    nativePort.onMessage.addListener(async (msg) => {
      if (!msg || msg.type !== "request") return;
      try {
        const result = await handleBridge(msg);
        nativePort.postMessage({ id: msg.id, status: "ok", ...result });
      } catch (e) {
        nativePort.postMessage({ id: msg.id, status: "error", reason: String(e) });
      }
    });
    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      setTimeout(connectNative, 1500);
    });
  } catch (e) {
    setTimeout(connectNative, 3000);
  }
}

chrome.runtime.onStartup.addListener(connectNative);
chrome.runtime.onInstalled.addListener(connectNative);
connectNative();

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.admeasy_ping) {
    sendResponse({ ok: true, native_connected: !!nativePort });
    return true;
  }
});

async function handleBridge(msg) {
  const op = msg.op;
  const params = msg.params || {};
  if (op === "list_tabs") {
    const tabs = await chrome.tabs.query({});
    return { tabs: tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, active: t.active })) };
  }
  if (op === "open_tab") {
    const t = await chrome.tabs.create({ url: params.url || "about:blank", active: false });
    return { tab_id: t.id, url: t.url };
  }
  const tabId = params.tab_id;
  if (op === "navigate") {
    await chrome.tabs.update(tabId, { url: params.url });
    return { tab_id: tabId };
  }
  if (op === "scroll") {
    const dy = Number(params.dy || 600);
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (y) => window.scrollBy(0, y),
      args: [dy],
    });
    return { scrolled: dy };
  }
  if (op === "wait_for") {
    const ms = Math.min(Number(params.timeout_ms || 3000), 30000);
    await new Promise((r) => setTimeout(r, ms));
    return { waited_ms: ms };
  }
  if (op === "read_page" || op === "extract" || op === "query_elements") {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const links = [...document.querySelectorAll("a[href]")].slice(0, 200).map((a) => ({
          href: a.href,
          text: (a.innerText || "").slice(0, 200),
        }));
        const text = (document.body && document.body.innerText) || "";
        const nodes = [...document.querySelectorAll("button,a,input,textarea,[role=button]")].slice(0, 80);
        const elements = nodes.map((el, i) => {
          const r = el.getBoundingClientRect();
          return {
            id: i + 1,
            role: el.tagName.toLowerCase(),
            name: (el.getAttribute("aria-label") || el.innerText || "").slice(0, 120),
            bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
          };
        });
        return { text: text.slice(0, 12000), links, elements, title: document.title, url: location.href };
      },
    });
    if (op === "extract") return { chunks: [{ text: result.text }], schema: params.schema || {} };
    if (op === "query_elements") return { elements: result.elements };
    return result;
  }
  if (op === "click_element") {
    const id = params.element_id;
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      args: [id],
      func: (mark) => {
        const nodes = [...document.querySelectorAll("button,a,input,textarea,[role=button]")];
        const el = nodes[mark - 1];
        if (!el) return { ok: false };
        el.click();
        return { ok: true };
      },
    });
    return result;
  }
  if (op === "type_element") {
    const id = params.element_id;
    const text = params.text || "";
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      args: [id, text],
      func: (mark, value) => {
        const nodes = [...document.querySelectorAll("input,textarea")];
        const el = nodes[mark - 1];
        if (!el) return { ok: false };
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return { ok: true };
      },
    });
    return result;
  }
  if (op === "screenshot_tab") {
    const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: "jpeg", quality: 55 });
    return { screenshot_b64: dataUrl.split(",")[1] || "" };
  }
  if (op === "close_tab") {
    await chrome.tabs.remove(tabId);
    return { closed: tabId };
  }
  return { error: "unknown_op" };
}
