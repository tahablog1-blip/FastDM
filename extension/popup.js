const $ = (id) => document.getElementById(id);
const human = (n) => {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (n >= 1024 && i < 3) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + " " + u[i];
};

chrome.storage.local.get({ floating: true, intercept: true }, (s) => {
  $("floating").checked = s.floating;
  $("intercept").checked = s.intercept;
});
for (const k of ["floating", "intercept"])
  $(k).addEventListener("change", () => chrome.storage.local.set({ [k]: $(k).checked }));

chrome.runtime.sendMessage({ type: "ping" }, (r) => {
  const ok = r && r.ok;
  $("status").textContent = ok ? "متصل ✔" : "البرنامج مقفول";
  $("status").className = "st " + (ok ? "on" : "off");
  if (!ok) $("msg").textContent = "افتح برنامج FastDM على الكمبيوتر علشان التحميل يشتغل.";
});

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  if (/^https?:/.test(tab.url || "")) {
    $("pageSec").style.display = "block";
    $("pageBtn").onclick = () =>
      chrome.runtime.sendMessage({ type: "download", items: [{ url: tab.url, kind: "page" }], referer: tab.url }, (res) => {
        $("msg").textContent = res && res.ok ? "✔ اتبعت لبرنامج FastDM، اختار الجودة من البرنامج" : "افتح برنامج FastDM الأول.";
      });
  }
  chrome.runtime.sendMessage({ type: "getMedia", tabId: tab.id }, (r) => {
    const list = (r && r.list) || [];
    const box = $("list");
    if (!list.length) {
      box.innerHTML = '<div class="empty">مفيش فيديوهات اتلقطت لسه. شغّل الفيديو ثانيتين وافتح القائمة دي تاني.</div>';
      return;
    }
    for (const m of list) {
      const row = document.createElement("div");
      row.className = "item";
      row.innerHTML = '<span class="n"></span><span class="s"></span><button class="dl">تحميل</button>';
      row.querySelector(".n").textContent = m.name;
      row.querySelector(".n").title = m.url;
      row.querySelector(".s").textContent = human(m.size);
      row.querySelector("button").onclick = () =>
        chrome.runtime.sendMessage({ type: "download", items: [{ url: m.url, filename: m.name }], referer: tab.url }, (res) => {
          $("msg").textContent = res && res.ok ? "✔ اتبعت لبرنامج FastDM" : "افتح برنامج FastDM الأول.";
        });
      box.appendChild(row);
    }
  });
});
