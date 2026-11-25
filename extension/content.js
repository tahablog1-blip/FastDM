// FastDM - الأيقونة العائمة فوق الفيديوهات وروابط الملفات
(() => {
  // لو الإضافة اتحدّثت أو اتحطت تاني في نفس الصفحة: نشيل النسخة القديمة
  if (window.__fastdmCleanup) try { window.__fastdmCleanup(); } catch {}
  const ac = new AbortController();
  const on = (t, ev, fn, opt) => t.addEventListener(ev, fn, { ...(opt || {}), signal: ac.signal });
  // مواقع الفيديو اللي بتتحمّل من صفحتها (يوتيوب، فيسبوك، تيك توك…)
  const PAGE_SITE = /^https?:\/\/([a-z0-9-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com|facebook\.com|fb\.watch|instagram\.com|tiktok\.com|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|twitch\.tv|reddit\.com|soundcloud\.com|ok\.ru|vk\.com|bilibili\.com|pinterest\.com|threads\.net)\//i;

  const FILE_EXT = /\.(zip|rar|7z|tar|gz|bz2|xz|exe|msi|apk|xapk|iso|img|dmg|bin|pdf|docx?|xlsx?|pptx?|epub|torrent|mp4|m4v|webm|mkv|mov|avi|flv|wmv|mp3|m4a|aac|ogg|wav|flac)(\?|#|$)/i;
  let enabled = true;
  let mediaList = [];
  let currentVideo = null;
  let currentLink = null;
  let hideTimer = null;
  let overUi = false;

  // ---------- واجهة داخل Shadow DOM علشان ستايل الموقع ما يبوظهاش ----------
  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;inset:0 auto auto 0;width:0;height:0;z-index:2147483647;";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `
  <style>
    *{box-sizing:border-box;font-family:"Segoe UI",Tahoma,Arial,sans-serif}
    .btn{position:fixed;display:none;align-items:center;gap:6px;padding:7px 12px 7px 10px;
      background:#2563eb;color:#fff;border:0;border-radius:999px;font-size:13px;font-weight:600;
      cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35);direction:rtl;white-space:nowrap;
      transition:transform .12s ease, background .12s ease;pointer-events:auto}
    .btn:hover{background:#1d4ed8;transform:scale(1.05)}
    .btn svg{width:16px;height:16px;flex:none}
    .link{position:fixed;display:none;width:26px;height:26px;border-radius:50%;border:0;padding:0;
      background:#2563eb;color:#fff;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);
      align-items:center;justify-content:center;pointer-events:auto}
    .link:hover{background:#1d4ed8;transform:scale(1.1)}
    .link svg{width:15px;height:15px}
    .menu{position:fixed;display:none;min-width:280px;max-width:420px;max-height:320px;overflow:auto;
      background:#fff;color:#111827;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.35);
      direction:rtl;padding:6px;pointer-events:auto}
    .menu .h{font-size:12px;color:#6b7280;padding:6px 8px}
    .item{display:flex;justify-content:space-between;gap:10px;width:100%;padding:8px 10px;border:0;
      background:none;border-radius:6px;cursor:pointer;font-size:13px;color:#111827;text-align:right}
    .item:hover{background:#eff6ff}
    .item .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:ltr}
    .item .s{color:#6b7280;flex:none}
    .toast{position:fixed;display:none;bottom:24px;left:50%;transform:translateX(-50%);
      padding:10px 18px;border-radius:8px;color:#fff;font-size:14px;direction:rtl;
      box-shadow:0 6px 20px rgba(0,0,0,.3);pointer-events:none}
  </style>
  <button class="btn" title="تحميل بـ FastDM">${icon()}<span>تحميل الفيديو</span></button>
  <button class="link" title="تحميل بـ FastDM">${icon()}</button>
  <div class="menu"></div>
  <div class="toast"></div>`;
  const btn = root.querySelector(".btn");
  const linkBtn = root.querySelector(".link");
  const menu = root.querySelector(".menu");
  const toastEl = root.querySelector(".toast");

  function icon() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"
      stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m6 10 6 6 6-6"/><path d="M4 20h16"/></svg>`;
  }

  function mount() {
    const fs = document.fullscreenElement;
    const parent = fs && fs.tagName !== "VIDEO" ? fs : document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
  }
  mount();
  on(document, "fullscreenchange", mount);
  window.__fastdmCleanup = () => { ac.abort(); host.remove(); };

  for (const el of [btn, linkBtn, menu]) {
    el.addEventListener("mouseenter", () => { overUi = true; clearTimeout(hideTimer); });
    el.addEventListener("mouseleave", () => { overUi = false; scheduleHide(); });
  }

  // ---------- أدوات ----------
  const human = (n) => {
    if (!n) return "";
    const u = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return n.toFixed(i ? 1 : 0) + " " + u[i];
  };
  const send = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => res(r || {})); } catch { res({}); }
  });

  function toast(text, ok) {
    toastEl.textContent = text;
    toastEl.style.background = ok ? "#15803d" : "#b91c1c";
    toastEl.style.display = "block";
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => (toastEl.style.display = "none"), 3200);
  }

  function result(r) {
    if (r.ok) toast("✔ اتبعت لبرنامج FastDM", true);
    else if (r.error === "nomedia") toast("شغّل الفيديو ثانيتين الأول علشان ألقط الرابط", false);
    else toast("برنامج FastDM مش مفتوح: شغّل run.bat (أو FastDM.exe) وجرّب تاني", false);
  }

  async function download(items) {
    hideAll();
    result(await send({ type: "download", items, referer: location.href }));
  }

  async function downloadPage() {
    hideAll();
    result(await send({ type: "download", items: [{ url: location.href, kind: "page" }], referer: location.href }));
  }

  function hideAll() {
    btn.style.display = linkBtn.style.display = menu.style.display = "none";
    currentVideo = currentLink = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (!overUi) hideAll();
    }, 1500);
  }

  // ---------- الفيديوهات ----------
  function videoAt(x, y) {
    let best = null;
    for (const v of document.querySelectorAll("video, audio")) {
      // في يوتيوب ناخد مقاس المشغّل كله مش عنصر الفيديو بس
      const box = v.closest("#movie_player, .html5-video-player") || v;
      const r = box.getBoundingClientRect();
      if (r.width < 160 || r.height < 40) continue;
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
        if (!best || r.width * r.height > best.r.width * best.r.height) best = { v, r };
      }
    }
    return best;
  }

  function placeVideoBtn(r) {
    btn.style.display = "flex";
    const w = btn.offsetWidth || 130;
    const top = Math.max(6, r.top + 10);
    const left = Math.min(window.innerWidth - w - 8, Math.max(8, r.right - w - 10));
    btn.style.top = top + "px";
    btn.style.left = left + "px";
  }

  function candidates(v) {
    const out = [];
    const add = (url, name, size) => {
      if (url && /^https?:/.test(url) && !out.some((o) => o.url === url)) out.push({ url, name, size });
    };
    if (v) {
      add(v.currentSrc || v.src);
      v.querySelectorAll("source").forEach((s) => add(s.src));
    }
    mediaList.forEach((m) => add(m.url, m.name, m.size));
    return out;
  }

  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (PAGE_SITE.test(location.href)) return downloadPage();
    const r = await send({ type: "getMedia" });
    mediaList = r.list || mediaList;
    const list = candidates(currentVideo);
    if (!list.length) return downloadPage(); // فيديو blob: نخلّي البرنامج يجيبه من الصفحة
    if (list.length === 1) return download([{ url: list[0].url, filename: list[0].name }]);
    showMenu(list);
  });

  function showMenu(list) {
    menu.innerHTML = `<div class="h">اختار الملف اللي عايز تحمّله:</div>`;
    for (const m of list) {
      const b = document.createElement("button");
      b.className = "item";
      const name = m.name || decodeURIComponent(new URL(m.url).pathname.split("/").pop() || "video");
      b.innerHTML = `<span class="n"></span><span class="s"></span>`;
      b.querySelector(".n").textContent = name;
      b.querySelector(".s").textContent = human(m.size);
      b.title = m.url;
      b.onclick = (e) => { e.stopPropagation(); download([{ url: m.url, filename: m.name }]); };
      menu.appendChild(b);
    }
    const r = btn.getBoundingClientRect();
    menu.style.display = "block";
    menu.style.top = Math.min(window.innerHeight - menu.offsetHeight - 8, r.bottom + 6) + "px";
    menu.style.left = Math.max(8, Math.min(window.innerWidth - menu.offsetWidth - 8, r.right - menu.offsetWidth)) + "px";
  }

  // ---------- روابط الملفات ----------
  function fileLink(el) {
    const a = el && el.closest && el.closest("a[href]");
    if (!a || !/^https?:/.test(a.href)) return null;
    if (FILE_EXT.test(a.href) || a.hasAttribute("download")) return a;
    return null;
  }

  linkBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (currentLink) download([{ url: currentLink.href, filename: currentLink.getAttribute("download") || "" }]);
  });

  // ---------- تتبع الماوس ----------
  let raf = 0;
  on(window, "mousemove", (e) => {
    if (!enabled || raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (overUi) return;
      const hit = videoAt(e.clientX, e.clientY);
      if (hit) {
        clearTimeout(hideTimer);
        currentVideo = hit.v;
        placeVideoBtn(hit.r);
      } else if (btn.style.display !== "none") scheduleHide();

      const a = fileLink(e.target);
      if (a) {
        clearTimeout(hideTimer);
        currentLink = a;
        const r = a.getBoundingClientRect();
        linkBtn.style.display = "flex";
        linkBtn.style.top = Math.max(4, r.top + r.height / 2 - 13) + "px";
        linkBtn.style.left = Math.min(window.innerWidth - 32, r.right + 6) + "px";
      } else if (linkBtn.style.display !== "none" && !hit) scheduleHide();
    });
  }, { passive: true, capture: true });

  on(window, "scroll", () => { if (!overUi) hideAll(); }, { passive: true });
  on(document, "click", (e) => {
    if (!e.composedPath().includes(host)) menu.style.display = "none";
  });

  // ---------- رسائل من الخلفية ----------
  const onMsg = (msg) => {
    if (ac.signal.aborted) return;
    if (msg.type === "media") mediaList = msg.list || [];
    if (msg.type === "toast" && window === window.top) result(msg.result || {});
  };
  chrome.runtime.onMessage.addListener(onMsg);
  ac.signal.addEventListener("abort", () => { try { chrome.runtime.onMessage.removeListener(onMsg); } catch {} });
  send({ type: "getMedia" }).then((r) => {
    mediaList = r.list || [];
    if (r.settings) enabled = r.settings.floating !== false;
  });
  chrome.storage.onChanged.addListener((c) => {
    if (c.floating) { enabled = c.floating.newValue !== false; if (!enabled) hideAll(); }
  });
})();
