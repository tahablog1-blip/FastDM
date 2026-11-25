"""
FastDM - تحميل فيديوهات يوتيوب وفيسبوك وتيك توك وإنستجرام وتويتر وغيرها (عن طريق yt-dlp)
"""
import os
import re
import shutil
import sys

PAGE_SITES = re.compile(
    r"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com|facebook\.com|fb\.watch|"
    r"instagram\.com|tiktok\.com|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|twitch\.tv|"
    r"reddit\.com|soundcloud\.com|ok\.ru|vk\.com|bilibili\.com|pinterest\.com|threads\.net)/", re.I)


class Stopped(Exception):
    pass


def available():
    try:
        import yt_dlp  # noqa
        return True
    except ImportError:
        return False


def ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa
        return shutil.which("ffmpeg")


def _js_runtimes():
    """يوتيوب محتاج محرك JavaScript (deno) علشان يطلع كل الجودات"""
    path = None
    try:
        import deno
        path = deno.find_deno_bin()
    except Exception:  # noqa
        path = shutil.which("deno")
    if not path and getattr(sys, "frozen", False):
        p = os.path.join(getattr(sys, "_MEIPASS", ""), "deno.exe")
        path = p if os.path.exists(p) else None
    return {"deno": {"path": path}} if path else None


def base_opts():
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
         "windowsfilenames": True, "retries": 10, "fragment_retries": 10}
    js = _js_runtimes()
    if js:
        o["js_runtimes"] = js
    ff = ffmpeg_path()
    if ff:
        o["ffmpeg_location"] = ff
    return o


def clean_error(e):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    msg = msg.replace("ERROR: ", "")
    if "Sign in to confirm" in msg:
        return "يوتيوب طالب تأكيد إنك مش روبوت. جرّب تاني بعد شوية."
    if "Unsupported URL" in msg:
        return "الموقع ده مش مدعوم لتحميل الفيديو."
    if "Private video" in msg or "login" in msg.lower():
        return "الفيديو خاص أو محتاج تسجيل دخول."
    return msg[:300]


def get_info(url):
    """يرجع عنوان الفيديو والجودات المتاحة مع الحجم التقريبي"""
    import yt_dlp
    with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True}) as y:
        info = y.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    fmts = info.get("formats") or []
    has_ff = bool(ffmpeg_path())

    def fsize(f):
        return f.get("filesize") or f.get("filesize_approx") or 0

    audio = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max((fsize(f) for f in audio), default=0)
    heights = {}
    for f in fmts:
        h = f.get("height")
        if not h or f.get("vcodec") in (None, "none"):
            continue
        if not has_ff and f.get("acodec") in (None, "none"):
            continue        # من غير ffmpeg مش هنقدر ندمج صوت وصورة
        s = fsize(f) + (best_audio if f.get("acodec") in (None, "none") else 0)
        heights[h] = max(heights.get(h, 0), s)
    options = [{"label": f"{h}p" + (" HD" if h >= 720 else ""), "height": h, "size": heights[h]}
               for h in sorted(heights, reverse=True)]
    if audio:
        options.append({"label": "صوت فقط MP3" if has_ff else "صوت فقط", "height": "audio",
                        "size": best_audio})
    return {"title": info.get("title") or "video", "duration": info.get("duration"),
            "uploader": info.get("uploader") or "", "options": options,
            "url": info.get("webpage_url") or url}


def format_for(height):
    has_ff = bool(ffmpeg_path())
    if height == "audio":
        return "ba[ext=m4a]/ba/b"
    if not height:
        return "bv*+ba/b" if has_ff else "b"
    h = int(height)
    if has_ff:
        return (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/"
                f"b[height<={h}]/bv*+ba/b")
    return f"b[height<={h}]/b"


def download(d, ev, connections=8):
    """بيحمّل الفيديو وبيحدّث تقدم الـ Download. بيرمي Stopped لو اتوقف."""
    import yt_dlp

    d.yt_part = 0

    def hook(h):
        if ev.is_set():
            raise Stopped()
        if h["status"] == "downloading":
            total = h.get("total_bytes") or h.get("total_bytes_estimate")
            if total:
                d.size = int(total)
            d.yt_done = int(h.get("downloaded_bytes") or 0)
            d.speed = float(h.get("speed") or 0)
            d.active_conns = 1
        elif h["status"] == "finished":
            d.yt_part += 1

    def post(path):
        d.filename = os.path.basename(path)

    opts = {**base_opts(),
            "format": format_for(d.yt_format),
            "outtmpl": os.path.join(d.folder, "%(title).150B.%(ext)s"),
            "merge_output_format": "mp4",
            "continuedl": True,
            "concurrent_fragment_downloads": max(1, min(16, connections)),
            "progress_hooks": [hook],
            "post_hooks": [post]}
    if d.yt_format == "audio" and opts.get("ffmpeg_location"):
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                   "preferredquality": "192"}]
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([d.url])
