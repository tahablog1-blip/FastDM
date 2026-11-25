// FastDM extension - background service worker
const APP = "http://127.0.0.1:6801";
const MEDIA_EXT = /\.(mp4|m4v|webm|mkv|mov|avi|flv|wmv|3gp|mp3|m4a|aac|ogg|oga|opus|wav|flac)(\?|#|$)/i;
const FILE_EXT = /\.(zip|rar|7z|tar|gz|bz2|xz|exe|msi|apk|xapk|iso|img|dmg|bin|pdf|docx?|xlsx?|pptx?|epub|torrent|mp4|m4v|webm|mkv|mov|avi|flv|wmv|mp3|m4a|aac|ogg|wav|flac)(\?|#|$)/i;
// بث مقطّع (HLS/DASH) ويوتيوب بيبعت الفيديو حتت صغيرة: البرنامج ما بيدعمهاش
const SKIP = /\.(m3u8|mpd|ts|m4s)(\?|#|$)|googlevideo\.com|\/videoplayback\?|[?&](range|bytestart)=/i;
const MIN_SIZE = 200 * 1024;

const defaults = { floating: true, intercept: true };
let settings = { ...defaults };
chrome.storage.local.get(defaults, (s) => (settings = s));
chrome.storage.onChanged.addListener((c) => {
  for (const k in c) settings[k] = c[k].newValue;
});

// ---------- الفيديوهات اللي اتلقطت في كل تاب ----------
const media = {}; // tabId -> [{url, name, size, type}]

async function loadMedia(tabId) {
  if (media[tabId]) return media[tabId];
  const k = "m" + tabId;
  const s = await chrome.storage.session.get(k);
  media[tabId] = s[k] || [];
  return media[tabId];
}
function saveMedia(tabId) {
  chrome.storage.session.set({ ["m" + tabId]: media[tabId] || [] });
}

function header(headers, name) {
  const h = headers.find((x) => x.name.toLowerCase() === name);
  return h ? h.value : "";
}

function nameFromUrl(url) {
  try {
    const p = decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
    return p || "video";
  } catch {
    return "video";
  }
}

chrome.webRequest.onHeadersReceived.addListener(
  async (d) => {
    if (d.tabId < 0 || !/^https?:/.test(d.url) || SKIP.test(d.url)) return;
    const h = d.responseHeaders || [];
    const type = header(h, "content-type").toLowerCase();
    const isMedia = /^(video|audio)\//.test(type) || (MEDIA_EXT.test(d.url) && !/text|html|json/.test(type));
    if (!isMedia || /mpegurl|dash/.test(type)) return;
    let size = 0;
    const cr = header(h, "content-range").match(/\/(\d+)/);
    if (cr) size = +cr[1];
    else size = +header(h, "content-length") || 0;
    if (size && size < MIN_SIZE) return;

    let name = nameFromUrl(d.url);
    const cd = header(h, "content-disposition").match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i);
    if (cd) name = decodeURIComponent(cd[1]);

    const list = await loadMedia(d.tabId);
    // نفس الملف ممكن يتطلب كذا مرة بـ Range مختلفة
    const key = d.url.split("#")[0];
    if (list.some((m) => m.url === key)) return;
    list.unshift({ url: key, name, size, type: type.split(";")[0] });
    if (list.length > 30) list.length = 30;
    saveMedia(d.tabId);
    chrome.action.setBadgeText({ tabId: d.tabId, text: String(list.length) });
    chrome.action.setBadgeBackgroundColor({ tabId: d.tabId, color: "#2563eb" });
    chrome.tabs.sendMessage(d.tabId, { type: "media", list }).catch(() => {});
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "object", "other"] },
  ["responseHeaders"]
);

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === "loading" && info.url) {
    media[tabId] = [];
    saveMedia(tabId);
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});
chrome.tabs.onRemoved.addListener((tabId) => {
  delete media[tabId];
  chrome.storage.session.remove("m" + tabId);
});

// ---------- الإرسال للبرنامج ----------
async function ping() {
  try {
    const r = await fetch(APP + "/ping", { signal: AbortSignal.timeout(1500) });
    return (await r.json()).app === "FastDM";
  } catch {
    return false;
  }
}

async function cookiesFor(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    return list.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch {
    return "";
  }
}

async function sendToApp(items, referer) {
  const full = [];
  for (const it of items) {
    if (it.kind === "page") {
      full.push({ url: it.url, kind: "page" });
      continue;
    }
    full.push({
      url: it.url,
      filename: it.filename || "",
      referer: it.referer || referer || "",
      cookie: await cookiesFor(it.url),
      userAgent: navigator.userAgent,
    });
  }
  try {
    const r = await fetch(APP + "/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: full }),
      signal: AbortSignal.timeout(4000),
    });
    const j = await r.json();
    return { ok: !!j.ok };
  } catch {
    return { ok: false, error: "offline" };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const tabId = msg.tabId ?? sender.tab?.id;
    if (msg.type === "getMedia") reply({ list: await loadMedia(tabId), settings });
    else if (msg.type === "download") reply(await sendToApp(msg.items, msg.referer || sender.tab?.url));
    else if (msg.type === "ping") reply({ ok: await ping() });
    else if (msg.type === "clear") {
      media[tabId] = [];
      saveMedia(tabId);
      chrome.action.setBadgeText({ tabId, text: "" });
      reply({});
    }
  })();
  return true;
});

// ---------- قائمة كليك يمين ----------
chrome.runtime.onInstalled.addListener(async () => {
  // الصفحات اللي كانت مفتوحة قبل تسطيب الإضافة: نحط فيها الأيقونة من غير ما تحتاج Refresh
  for (const tab of await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] })) {
    chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["content.js"] }).catch(() => {});
  }
  chrome.contextMenus.create({
    id: "fastdm",
    title: "⬇ تحميل بـ FastDM",
    contexts: ["link", "video", "audio", "image"],
  });
});
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.srcUrl;
  if (!url) return;
  let r;
  if (/^https?:/.test(url)) r = await sendToApp([{ url }], tab?.url);
  else {
    // فيديو blob: ناخد أول فيديو اتلقط في التاب
    r = await sendToApp([{ url: info.frameUrl || tab.url, kind: "page" }], tab.url);
  }
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "toast", result: r }).catch(() => {});
});

// ---------- الاستيلاء على تحميلات المتصفح ----------
chrome.downloads.onCreated.addListener(async (item) => {
  if (!settings.intercept) return;
  const url = item.finalUrl || item.url;
  if (!/^https?:/.test(url)) return;
  if (item.byExtensionId === chrome.runtime.id) return;
  if (!(await ping())) return; // البرنامج مقفول: سيب المتصفح يحمّل عادي
  try {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
  } catch {}
  const filename = (item.filename || "").split(/[\\/]/).pop();
  const r = await sendToApp([{ url, filename, referer: item.referrer }], item.referrer);
  // لو البرنامج ما استلمش، نرجّع التحميل للمتصفح علشان ما يضيعش
  if (!r.ok) chrome.downloads.download({ url });
});
