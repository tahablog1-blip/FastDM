"""
FastDM engine - محرك التحميل
تحميل متعدد الاتصالات مع تقسيم ديناميكي للأجزاء، إيقاف واستكمال، وطابور تحميلات.
لا يعتمد على أي مكتبات خارجية.
"""
import json
import os
import re
import threading
import time
import uuid
import urllib.parse
import urllib.request

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CHUNK = 256 * 1024
MIN_SPLIT = 1024 * 1024          # لا نقسم جزءا متبقيا أصغر من 1 ميجا
RETRIES = 8
TIMEOUT = 30

QUEUED, DOWNLOADING, PAUSED, DONE, ERROR = "queued", "downloading", "paused", "done", "error"


def default_download_dir():
    d = os.path.join(os.path.expanduser("~"), "Downloads", "FastDM")
    os.makedirs(d, exist_ok=True)
    return d


def data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "FastDM")
    os.makedirs(d, exist_ok=True)
    return d


def safe_filename(name):
    name = urllib.parse.unquote(name or "").strip().strip(".")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:200] or "download"


def unique_path(path):
    if not os.path.exists(path) and not os.path.exists(path + ".fdm"):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        p = f"{root} ({i}){ext}"
        if not os.path.exists(p) and not os.path.exists(p + ".fdm"):
            return p
        i += 1


def human_size(n):
    if n is None or n < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def human_time(sec):
    if sec is None or sec < 0 or sec == float("inf"):
        return "--"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _open(url, start=None, end=None, extra=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
    for k, v in (extra or {}).items():
        if k.lower() in ("cookie", "referer", "user-agent") and v:
            headers[k.title()] = v
    if start is not None:
        headers["Range"] = f"bytes={start}-" + ("" if end is None or end < 0 else str(end))
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)


def _filename_from_headers(resp, url):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.I)
    if m:
        return safe_filename(m.group(1).strip('" '))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if m:
        return safe_filename(m.group(1))
    path = urllib.parse.urlparse(url).path
    return safe_filename(os.path.basename(path))


def probe(url, extra=None):
    """يرجع: (الرابط النهائي، اسم الملف، الحجم أو None، هل يدعم التقسيم)"""
    resp = _open(url, 0, 0, extra)
    try:
        final = resp.geturl()
        name = _filename_from_headers(resp, final)
        if resp.status == 206:
            cr = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)", cr)
            size = int(m.group(1)) if m else None
            return final, name, size, size is not None
        cl = resp.headers.get("Content-Length")
        return final, name, (int(cl) if cl and cl.isdigit() else None), False
    finally:
        resp.close()


class Download:
    def __init__(self, url, folder, filename=None, did=None):
        self.id = did or uuid.uuid4().hex[:10]
        self.url = url
        self.final_url = None
        self.folder = folder
        self.filename = filename
        self.size = None
        self.resumable = False
        self.segments = []          # [start, end, pos]  (end شامل، -1 = غير معروف)
        self.status = QUEUED
        self.error = ""
        self.added = time.time()
        self.finished = None
        self.headers = {}           # Cookie / Referer / User-Agent من المتصفح
        self.kind = "direct"        # direct = رابط ملف مباشر، page = صفحة فيديو (يوتيوب…)
        self.yt_format = None       # الجودة المطلوبة: رقم (720) أو "audio"
        self.yt_done = 0
        self.yt_part = 0
        # runtime
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.threads = []
        self.speed = 0.0
        self._last_bytes = 0
        self._last_time = time.time()
        self.active_conns = 0

    @property
    def path(self):
        return os.path.join(self.folder, self.filename or "download")

    @property
    def temp_path(self):
        return self.path + ".fdm"

    def downloaded(self):
        with self.lock:
            if self.status == DONE and self.size:
                return self.size
            if self.kind == "page":
                return self.yt_done
            return sum(max(0, s[2] - s[0]) for s in self.segments)

    def progress(self):
        if self.status == DONE:
            return 1.0
        if not self.size:
            return 0.0
        return min(1.0, self.downloaded() / self.size)

    def eta(self):
        if not self.size or self.speed <= 0:
            return None
        return (self.size - self.downloaded()) / self.speed

    def to_dict(self):
        with self.lock:
            return {k: getattr(self, k) for k in (
                "id", "url", "final_url", "folder", "filename", "size", "resumable",
                "segments", "status", "error", "added", "finished", "headers", "kind", "yt_format")}

    @classmethod
    def from_dict(cls, d):
        dl = cls(d["url"], d["folder"], d.get("filename"), d["id"])
        for k in ("final_url", "size", "resumable", "segments", "status", "error", "added", "finished",
                  "headers", "kind", "yt_format"):
            if k in d:
                setattr(dl, k, d[k])
        if dl.status == DOWNLOADING:
            dl.status = QUEUED      # كان شغال لما البرنامج اتقفل
        return dl


class Engine:
    def __init__(self):
        self.settings = {"max_active": 3, "connections": 8, "folder": default_download_dir(),
                         "watch_clipboard": True}
        self.downloads = []
        self.lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._state_file = os.path.join(data_dir(), "downloads.json")
        self._load()
        self._closing = False
        threading.Thread(target=self._scheduler, daemon=True).start()

    # ---------- حفظ واسترجاع ----------
    def _load(self):
        try:
            with open(self._state_file, encoding="utf-8") as f:
                data = json.load(f)
            self.settings.update(data.get("settings", {}))
            self.downloads = [Download.from_dict(d) for d in data.get("downloads", [])]
        except (OSError, ValueError, KeyError):
            pass

    def save(self):
        with self.lock:
            data = {"settings": self.settings, "downloads": [d.to_dict() for d in self.downloads]}
        with self._save_lock:
            tmp = self._state_file + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._state_file)
            except OSError:
                pass

    # ---------- أوامر ----------
    def add(self, url, folder=None, filename=None, start=True, headers=None, kind="direct",
            yt_format=None):
        folder = folder or self.settings["folder"]
        os.makedirs(folder, exist_ok=True)
        d = Download(url.strip(), folder, safe_filename(filename) if filename else None)
        d.status = QUEUED if start else PAUSED
        d.headers = dict(headers or {})
        d.kind, d.yt_format = kind, yt_format
        with self.lock:
            self.downloads.append(d)
        self.save()
        return d

    def get(self, did):
        with self.lock:
            return next((d for d in self.downloads if d.id == did), None)

    def pause(self, d):
        if d.status in (DOWNLOADING, QUEUED):
            d.stop_event.set()
            d.status = PAUSED
            d.speed = 0
            self.save()

    def resume(self, d):
        if d.status in (PAUSED, ERROR):
            d.error = ""
            d.status = QUEUED
            self.save()

    def remove(self, d, delete_file=False):
        self.pause(d)
        with self.lock:
            if d in self.downloads:
                self.downloads.remove(d)
        for p in ([d.temp_path] + ([d.path] if delete_file and d.status == DONE else [])):
            try:
                if d.filename and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        self.save()

    def shutdown(self):
        self._closing = True
        for d in list(self.downloads):
            if d.status == DOWNLOADING:
                d.stop_event.set()
        for d in list(self.downloads):
            for t in list(d.threads):
                t.join(timeout=3)
            if d.status == DOWNLOADING:
                d.status = QUEUED
        self.save()

    # ---------- الجدولة ----------
    def _scheduler(self):
        last_save = time.time()
        while not self._closing:
            with self.lock:
                active = [d for d in self.downloads if d.status == DOWNLOADING]
                waiting = [d for d in self.downloads if d.status == QUEUED]
            for d in waiting[: max(0, self.settings["max_active"] - len(active))]:
                d.status = DOWNLOADING
                d.stop_event = threading.Event()
                threading.Thread(target=self._run, args=(d,), daemon=True).start()
            now = time.time()
            for d in active:   # حساب السرعة
                if d.kind == "page":
                    continue
                b = d.downloaded()
                dt = now - d._last_time
                if dt >= 1:
                    inst = (b - d._last_bytes) / dt
                    d.speed = inst if d.speed == 0 else d.speed * 0.6 + inst * 0.4
                    d._last_bytes, d._last_time = b, now
            if now - last_save > 5 and active:
                self.save()
                last_save = now
            time.sleep(0.3)

    def _run(self, d):
        ev = d.stop_event
        if d.kind == "page":
            return self._run_page(d, ev)
        try:
            d.speed = 0
            d._last_bytes, d._last_time = d.downloaded(), time.time()
            if not d.segments or not os.path.exists(d.temp_path):
                self._prepare(d)
            elif not d.resumable:      # السيرفر لا يدعم الاستكمال: نبدأ من الأول
                d.segments = [[0, -1, 0]]
                open(d.temp_path, "wb").close()
            d.threads = []
            for seg in list(d.segments):
                if seg[1] < 0 or seg[2] <= seg[1]:
                    self._spawn(d, seg, ev)
            for t in list(d.threads):
                t.join()
            # ممكن تكون اتولدت threads جديدة أثناء الانتظار
            while any(t.is_alive() for t in d.threads):
                for t in list(d.threads):
                    t.join()
            if ev.is_set():
                return
            if d.error:
                d.status = ERROR
            elif all(s[1] < 0 or s[2] > s[1] for s in d.segments):
                if d.size is None:
                    d.size = d.downloaded()
                final = unique_path(d.path) if os.path.exists(d.path) else d.path
                os.replace(d.temp_path, final)
                d.filename = os.path.basename(final)
                d.status, d.finished, d.speed = DONE, time.time(), 0
            else:
                d.status = ERROR
                d.error = "التحميل لم يكتمل"
        except Exception as e:  # noqa
            if not ev.is_set():
                d.status, d.error = ERROR, str(e)
        finally:
            d.speed = 0
            self.save()

    def _run_page(self, d, ev):
        import ytdl
        try:
            d.speed = 0
            ytdl.download(d, ev, self.settings["connections"])
            if ev.is_set():
                return
            p = d.path
            if os.path.exists(p):
                d.size = d.yt_done = os.path.getsize(p)
            d.status, d.finished = DONE, time.time()
        except Exception as e:  # noqa
            if not ev.is_set():
                d.status, d.error = ERROR, ytdl.clean_error(e)
        finally:
            d.speed = 0
            d.active_conns = 0
            self.save()

    def _prepare(self, d):
        final, name, size, ranges = probe(d.url, d.headers)
        d.final_url = final
        if not d.filename:
            d.filename = name
            d.filename = os.path.basename(unique_path(d.path))
        d.size, d.resumable = size, ranges
        with open(d.temp_path, "wb") as f:
            if size:
                f.truncate(size)
        if ranges and size:
            n = max(1, min(self.settings["connections"], size // MIN_SPLIT))
            part = size // n
            d.segments = [[i * part, (size - 1) if i == n - 1 else (i + 1) * part - 1, i * part]
                          for i in range(n)]
        else:
            d.segments = [[0, -1, 0]]
        self.save()

    def _spawn(self, d, seg, ev):
        t = threading.Thread(target=self._worker, args=(d, seg, ev), daemon=True)
        d.threads.append(t)
        t.start()

    def _steal(self, d, ev):
        """تقسيم ديناميكي: أول ما اتصال يخلص، ياخد نص أكبر جزء متبقي"""
        if not d.resumable or ev.is_set():
            return None
        with d.lock:
            best = max(d.segments, key=lambda s: s[1] - s[2], default=None)
            if not best or best[1] - best[2] + 1 < 2 * MIN_SPLIT:
                return None
            mid = best[2] + (best[1] - best[2] + 1) // 2
            new = [mid, best[1], mid]
            best[1] = mid - 1
            d.segments.append(new)
            return new

    def _worker(self, d, seg, ev):
        d.active_conns += 1
        try:
            while True:
                self._download_segment(d, seg, ev)
                if ev.is_set() or d.error:
                    return
                seg = self._steal(d, ev)
                if seg is None:
                    return
        finally:
            d.active_conns -= 1

    def _download_segment(self, d, seg, ev):
        url = d.final_url or d.url
        attempt = 0
        with open(d.temp_path, "r+b") as f:
            while not ev.is_set():
                if seg[1] >= 0 and seg[2] > seg[1]:
                    return
                try:
                    if d.resumable:
                        resp = _open(url, seg[2], seg[1], d.headers)
                        if resp.status != 206:
                            raise IOError("السيرفر رفض طلب الجزء")
                    else:
                        resp = _open(url, extra=d.headers)
                        f.seek(0)
                        f.truncate()
                        seg[2] = 0
                    with resp:
                        while not ev.is_set():
                            data = resp.read(CHUNK)
                            if not data:
                                break
                            with d.lock:
                                if ev.is_set():
                                    return
                                if seg[1] >= 0:
                                    data = data[: max(0, seg[1] - seg[2] + 1)]
                                if data:
                                    f.seek(seg[2])
                                    f.write(data)
                                    seg[2] += len(data)
                                done = seg[1] >= 0 and seg[2] > seg[1]
                            if done:
                                return
                            attempt = 0
                    if seg[1] < 0:      # حجم غير معروف وخلص الاستريم
                        seg[1] = seg[2] - 1
                        seg[2] = seg[1] + 1
                        return
                    if not d.resumable:
                        return
                except Exception as e:  # noqa
                    attempt += 1
                    if attempt > RETRIES or not d.resumable:
                        if not ev.is_set():
                            d.error = f"خطأ في الاتصال: {e}"
                        return
                    ev.wait(min(2 ** attempt, 20))
