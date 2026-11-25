"""
FastDM - برنامج تحميل سريع وسهل
شغّله بـ:  python FastDM.py
"""
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import threading

import ytdl
from bridge import Bridge, already_running
from engine import (Engine, human_size, human_time,
                    QUEUED, DOWNLOADING, PAUSED, DONE, ERROR)

STATUS_AR = {QUEUED: "في الانتظار", DOWNLOADING: "جاري التحميل", PAUSED: "متوقف",
             DONE: "اكتمل ✔", ERROR: "خطأ ✖"}
URL_RE = re.compile(r"^(https?|ftp)://\S+$", re.I)
FILE_EXT = re.compile(r"\.(zip|rar|7z|tar|gz|exe|msi|apk|iso|mp4|mkv|avi|mov|mp3|wav|flac|pdf|"
                      r"docx?|xlsx?|pptx?|dmg|bin|img|torrent|jpg|png|webm)(\?|$)", re.I)

BG, CARD, ACCENT, FG, MUTED = "#f5f7fb", "#ffffff", "#2563eb", "#111827", "#6b7280"
FONT = ("Segoe UI", 10)


def open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:  # noqa
        messagebox.showerror("FastDM", f"تعذر الفتح:\n{e}")


def bar(p, width=12):
    full = int(p * width)
    return "█" * full + "░" * (width - full) + f"  {p * 100:5.1f}%"


class AddDialog(tk.Toplevel):
    def __init__(self, app, url="", name="", headers=None):
        super().__init__(app.root)
        self.app = app
        self.headers = headers or {}
        self.title("إضافة تحميل جديد")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(app.root)

        ttk.Label(self, text="رابط التحميل:").grid(row=0, column=0, sticky="e", pady=4)
        self.url = tk.StringVar(value=url)
        e = ttk.Entry(self, textvariable=self.url, width=60)
        e.grid(row=0, column=1, columnspan=2, pady=4, sticky="we")

        ttk.Label(self, text="اسم الملف (اختياري):").grid(row=1, column=0, sticky="e", pady=4)
        self.name = tk.StringVar(value=name)
        ttk.Entry(self, textvariable=self.name, width=60).grid(row=1, column=1, columnspan=2,
                                                               pady=4, sticky="we")

        ttk.Label(self, text="حفظ في:").grid(row=2, column=0, sticky="e", pady=4)
        self.folder = tk.StringVar(value=app.engine.settings["folder"])
        ttk.Entry(self, textvariable=self.folder, width=48).grid(row=2, column=1, pady=4, sticky="we")
        ttk.Button(self, text="اختيار…", command=self.pick).grid(row=2, column=2, padx=(6, 0))

        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, columnspan=3, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="إلغاء", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="إضافة للقائمة", command=lambda: self.ok(False)).pack(side="right", padx=4)
        ttk.Button(btns, text="⬇ ابدأ التحميل", style="Accent.TButton",
                   command=lambda: self.ok(True)).pack(side="right", padx=4)

        self.bind("<Return>", lambda _: self.ok(True))
        self.bind("<Escape>", lambda _: self.destroy())
        e.focus_set()
        e.select_range(0, "end")
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def pick(self):
        d = filedialog.askdirectory(initialdir=self.folder.get(), parent=self)
        if d:
            self.folder.set(d)

    def ok(self, start):
        urls = [u.strip() for u in self.url.get().split() if u.strip()]
        bad = [u for u in urls if not URL_RE.match(u)]
        if not urls or bad:
            messagebox.showwarning("FastDM", "اكتب رابط صحيح يبدأ بـ http أو https", parent=self)
            return
        name = self.name.get().strip() if len(urls) == 1 else None
        pages = [u for u in urls if ytdl.PAGE_SITES.match(u)]
        urls = [u for u in urls if u not in pages]
        for u in pages:
            QualityDialog(self.app, u, self.folder.get())
        for u in urls:
            self.app.engine.add(u, self.folder.get(), name or None, start, self.headers)
        self.destroy()
        self.app.refresh()


class QualityDialog(tk.Toplevel):
    """نافذة اختيار الجودة لفيديوهات يوتيوب وفيسبوك وتيك توك…"""

    def __init__(self, app, url, folder=None):
        super().__init__(app.root)
        self.app, self.url = app, url
        self.title("تحميل فيديو")
        self.configure(bg=BG, padx=18, pady=16)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.folder = tk.StringVar(value=folder or app.engine.settings["folder"])
        self.choice = tk.StringVar()
        self.info = None
        self.result = None

        self.head = ttk.Label(self, text="⏳ جاري جلب معلومات الفيديو…", font=("Segoe UI", 11, "bold"),
                              wraplength=460)
        self.head.pack(anchor="e")
        self.sub = ttk.Label(self, text=url, foreground=MUTED, wraplength=460)
        self.sub.pack(anchor="e", pady=(2, 10))
        self.box = ttk.Frame(self)
        self.box.pack(fill="x")
        self.pb = ttk.Progressbar(self.box, mode="indeterminate", length=460)
        self.pb.pack(pady=8)
        self.pb.start(12)

        f = ttk.Frame(self)
        f.pack(fill="x", pady=(10, 0))
        ttk.Button(f, text="…", width=3, command=self.pick).pack(side="left")
        ttk.Entry(f, textvariable=self.folder, width=46).pack(side="left", padx=6)
        ttk.Label(f, text="حفظ في:").pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="إلغاء", command=self.destroy).pack(side="left")
        self.go = ttk.Button(btns, text="⬇ ابدأ التحميل", style="Accent.TButton",
                             command=self.start, state="disabled")
        self.go.pack(side="right")
        self.bind("<Return>", lambda _: self.start())
        self.bind("<Escape>", lambda _: self.destroy())

        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry(f"+{x}+{y}")
        self.focus_force()

        if not ytdl.available():
            self.show_error("مكتبة yt-dlp مش متسطّبة. شغّل run.bat أو build_exe.bat تاني.")
            return
        threading.Thread(target=self._fetch, daemon=True).start()
        self.after(200, self._wait)

    def _fetch(self):
        try:
            self.result = ("ok", ytdl.get_info(self.url))
        except Exception as e:  # noqa
            self.result = ("err", ytdl.clean_error(e))

    def _wait(self):
        if not self.winfo_exists():
            return
        if self.result is None:
            self.after(200, self._wait)
            return
        kind, val = self.result
        self.pb.destroy()
        if kind == "err":
            self.show_error(val)
        else:
            self.show_options(val)

    def show_error(self, msg):
        self.pb.destroy() if self.pb.winfo_exists() else None
        self.head.configure(text="✖ تعذر تحميل الفيديو", foreground="#b91c1c")
        ttk.Label(self.box, text=msg, wraplength=460).pack(anchor="e", pady=6)

    def show_options(self, info):
        self.info = info
        self.head.configure(text=info["title"])
        extra = [info["uploader"]] if info["uploader"] else []
        if info.get("duration"):
            extra.append(human_time(info["duration"]))
        self.sub.configure(text="  •  ".join(extra))
        if not info["options"]:
            self.show_error("مفيش جودات متاحة للتحميل.")
            return
        ttk.Label(self.box, text="اختار الجودة:").pack(anchor="e", pady=(0, 4))
        for i, o in enumerate(info["options"]):
            size = human_size(o["size"]) if o["size"] else ""
            txt = f"{o['label']}    {('~' + size) if size else ''}"
            rb = ttk.Radiobutton(self.box, text=txt, value=str(o["height"]), variable=self.choice)
            rb.pack(anchor="e", pady=1)
            if i == 0:
                self.choice.set(str(o["height"]))
        # الافتراضي: 1080 لو موجودة بدل 4K علشان الحجم
        for o in info["options"]:
            if o["height"] != "audio" and o["height"] <= 1080:
                self.choice.set(str(o["height"]))
                break
        self.go.configure(state="normal")
        self.go.focus_set()

    def pick(self):
        d = filedialog.askdirectory(initialdir=self.folder.get(), parent=self)
        if d:
            self.folder.set(d)

    def start(self):
        if not self.info:
            return
        c = self.choice.get()
        fmt = "audio" if c == "audio" else int(c)
        title = ytdl.re.sub(r'[<>:"/\\|?*]', "_", self.info["title"])[:150]
        self.app.engine.add(self.info["url"], self.folder.get(), title, True, None, "page", fmt)
        self.destroy()
        self.app.refresh()


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        s = app.engine.settings
        self.title("الإعدادات")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(app.root)

        self.conns = tk.IntVar(value=s["connections"])
        self.active = tk.IntVar(value=s["max_active"])
        self.folder = tk.StringVar(value=s["folder"])
        self.clip = tk.BooleanVar(value=s.get("watch_clipboard", True))
        self.ask = tk.BooleanVar(value=s.get("ask_before", True))

        ttk.Label(self, text="عدد الاتصالات لكل ملف:").grid(row=0, column=0, sticky="e", pady=5)
        ttk.Spinbox(self, from_=1, to=32, textvariable=self.conns, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(self, text="أقصى عدد تحميلات في نفس الوقت:").grid(row=1, column=0, sticky="e", pady=5)
        ttk.Spinbox(self, from_=1, to=10, textvariable=self.active, width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(self, text="مجلد الحفظ الافتراضي:").grid(row=2, column=0, sticky="e", pady=5)
        f = ttk.Frame(self)
        f.grid(row=2, column=1, sticky="w")
        ttk.Entry(f, textvariable=self.folder, width=40).pack(side="left")
        ttk.Button(f, text="…", width=3, command=self.pick).pack(side="left", padx=4)
        ttk.Checkbutton(self, text="التقط روابط التحميل من الحافظة (Copy) تلقائياً",
                        variable=self.clip).grid(row=3, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Checkbutton(self, text="اعرض نافذة التأكيد قبل التحميل من المتصفح",
                        variable=self.ask).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Button(self, text="حفظ", style="Accent.TButton", command=self.save).grid(
            row=5, column=1, sticky="e", pady=(10, 0))
        self.grab_set()

    def pick(self):
        d = filedialog.askdirectory(initialdir=self.folder.get(), parent=self)
        if d:
            self.folder.set(d)

    def save(self):
        s = self.app.engine.settings
        try:
            s["connections"] = max(1, min(32, int(self.conns.get())))
            s["max_active"] = max(1, min(10, int(self.active.get())))
        except (tk.TclError, ValueError):
            pass
        s["folder"] = self.folder.get()
        s["watch_clipboard"] = self.clip.get()
        s["ask_before"] = self.ask.get()
        self.app.engine.save()
        self.destroy()


class App:
    COLS = ("name", "size", "progress", "speed", "eta", "conns", "status")
    HEAD = {"name": "اسم الملف", "size": "الحجم", "progress": "التقدم", "speed": "السرعة",
            "eta": "المتبقي", "conns": "الاتصالات", "status": "الحالة"}
    WIDTH = {"name": 300, "size": 100, "progress": 200, "speed": 100, "eta": 95, "conns": 95,
             "status": 110}

    def __init__(self):
        self.engine = Engine()
        self.bridge = Bridge()
        self.bridge_ok = self.bridge.start()
        self.root = tk.Tk()
        self.root.title("FastDM - مدير التحميل السريع")
        self.root.geometry("1150x600")
        self.root.minsize(760, 400)
        self.root.configure(bg=BG)
        self._style()
        self._build()
        self._last_clip = self._clipboard()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()
        self.watch_clipboard()

    def _style(self):
        st = ttk.Style(self.root)
        if "clam" in st.theme_names():
            st.theme_use("clam")
        st.configure(".", font=FONT, background=BG, foreground=FG)
        st.configure("TButton", padding=(10, 6), background=CARD, bordercolor="#d1d5db")
        st.map("TButton", background=[("active", "#e5e7eb")])
        st.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT)
        st.map("Accent.TButton", background=[("active", "#1d4ed8")])
        st.configure("Treeview", rowheight=30, background=CARD, fieldbackground=CARD,
                     bordercolor="#e5e7eb")
        st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#eef2f7",
                     padding=6)
        st.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", FG)])
        st.configure("Status.TLabel", foreground=MUTED, background=BG)

    def _build(self):
        tb = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        tb.pack(fill="x")
        ttk.Button(tb, text="＋ إضافة رابط", style="Accent.TButton",
                   command=self.add).pack(side="left", padx=3)
        for txt, cmd in (("▶ استكمال", self.resume), ("⏸ إيقاف", self.pause),
                         ("✖ حذف", self.remove), ("📂 فتح المجلد", self.open_folder),
                         ("⏯ تشغيل الكل", self.resume_all), ("⏹ إيقاف الكل", self.pause_all)):
            ttk.Button(tb, text=txt, command=cmd).pack(side="left", padx=3)
        ttk.Button(tb, text="⚙ الإعدادات", command=lambda: SettingsDialog(self)).pack(side="right")

        frame = ttk.Frame(self.root, padding=(10, 0, 10, 0))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=self.COLS, show="headings", selectmode="extended")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEAD[c])
            self.tree.column(c, width=self.WIDTH[c], anchor="w" if c == "name" else "center",
                             stretch=(c == "name"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure(DONE, foreground="#15803d")
        self.tree.tag_configure(ERROR, foreground="#b91c1c")
        self.tree.tag_configure(PAUSED, foreground=MUTED)

        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-3>", self.on_menu)
        self.tree.bind("<Delete>", lambda _: self.remove())
        self.root.bind("<Control-v>", lambda _: self.add(self._clipboard()))
        self.root.bind("<Control-n>", lambda _: self.add())

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="فتح الملف", command=self.open_file)
        self.menu.add_command(label="فتح المجلد", command=self.open_folder)
        self.menu.add_separator()
        self.menu.add_command(label="استكمال", command=self.resume)
        self.menu.add_command(label="إيقاف", command=self.pause)
        self.menu.add_command(label="نسخ الرابط", command=self.copy_link)
        self.menu.add_separator()
        self.menu.add_command(label="حذف من القائمة", command=self.remove)
        self.menu.add_command(label="حذف مع الملف", command=lambda: self.remove(True))

        self.status = ttk.Label(self.root, style="Status.TLabel", padding=(12, 6))
        self.status.pack(fill="x")

    # ---------- تحديث الواجهة ----------
    def refresh(self):
        eng = self.engine
        ids = set()
        for d in list(eng.downloads):
            ids.add(d.id)
            done = d.downloaded()
            st = STATUS_AR[d.status]
            if d.status == DOWNLOADING and not d.active_conns:
                st = "جاري الاتصال…"
            elif d.status == ERROR and d.error:
                st = "خطأ ✖"
            conns = str(d.active_conns) if d.status == DOWNLOADING and d.active_conns else ""
            if d.kind == "page" and d.status == DOWNLOADING:
                conns = "▶ فيديو" if d.yt_part == 0 else "♪ صوت"
            size = human_size(d.size) if d.size else (human_size(done) if done else "?")
            prog = bar(d.progress()) if d.size else (human_size(done) if done else "--")
            vals = (d.filename or d.url, size, prog,
                    f"{human_size(d.speed)}/s" if d.status == DOWNLOADING else "",
                    human_time(d.eta()) if d.status == DOWNLOADING else "", conns, st)
            if self.tree.exists(d.id):
                if self.tree.item(d.id, "values") != tuple(map(str, vals)):
                    self.tree.item(d.id, values=vals, tags=(d.status,))
            else:
                self.tree.insert("", "end", iid=d.id, values=vals, tags=(d.status,))
        for iid in self.tree.get_children():
            if iid not in ids:
                self.tree.delete(iid)

        act = [d for d in eng.downloads if d.status == DOWNLOADING]
        speed = sum(d.speed for d in act)
        sel = self.selected()
        if sel and sel[0].status == ERROR and sel[0].error:
            self.status.configure(text="سبب الخطأ: " + sel[0].error)
            return
        self.status.configure(text=f"التحميلات النشطة: {len(act)}    |    السرعة الكلية: "
                                   f"{human_size(speed)}/s    |    الإجمالي: {len(eng.downloads)}"
                                   "    |    Ctrl+V للصق رابط مباشرة")
        title = "FastDM - مدير التحميل السريع"
        if act:
            title = f"⬇ {human_size(speed)}/s - " + title
        self.root.title(title)

    def tick(self):
        self.poll_browser()
        self.refresh()
        self.root.after(500, self.tick)

    def poll_browser(self):
        """روابط جاية من إضافة المتصفح (الأيقونة العائمة)"""
        while True:
            try:
                item = self.bridge.inbox.get_nowait()
            except Exception:  # noqa
                return
            self._last_clip = item["url"]
            if item.get("kind") == "page" or ytdl.PAGE_SITES.match(item["url"]):
                self.root.deiconify()
                self.root.lift()
                QualityDialog(self, item["url"])
            elif self.engine.settings.get("ask_before", True):
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                dlg = AddDialog(self, item["url"], item["filename"], item["headers"])
                dlg.attributes("-topmost", True)
                dlg.focus_force()
                self.root.after(300, lambda: self.root.attributes("-topmost", False))
            else:
                self.engine.add(item["url"], None, item["filename"] or None, True, item["headers"])

    def _clipboard(self):
        try:
            return self.root.clipboard_get().strip()
        except tk.TclError:
            return ""

    def watch_clipboard(self):
        if self.engine.settings.get("watch_clipboard", True):
            c = self._clipboard()
            if c != self._last_clip:
                self._last_clip = c
                if URL_RE.match(c) and (FILE_EXT.search(c) or ytdl.PAGE_SITES.match(c)) and \
                        not any(d.url == c for d in self.engine.downloads):
                    self.root.deiconify()
                    self.root.lift()
                    self.add(c)
        self.root.after(1000, self.watch_clipboard)

    # ---------- أوامر ----------
    def selected(self):
        return [d for d in (self.engine.get(i) for i in self.tree.selection()) if d]

    def add(self, url=None):
        if url is None:
            c = self._clipboard()
            url = c if URL_RE.match(c) else ""
        AddDialog(self, url)

    def resume(self):
        for d in self.selected():
            self.engine.resume(d)
        self.refresh()

    def pause(self):
        for d in self.selected():
            self.engine.pause(d)
        self.refresh()

    def resume_all(self):
        for d in self.engine.downloads:
            self.engine.resume(d)

    def pause_all(self):
        for d in self.engine.downloads:
            self.engine.pause(d)

    def remove(self, delete_file=False):
        sel = self.selected()
        if not sel:
            return
        msg = f"حذف {len(sel)} عنصر من القائمة؟"
        if delete_file:
            msg += "\nسيتم حذف الملفات من الجهاز أيضاً."
        if messagebox.askyesno("FastDM", msg):
            for d in sel:
                self.engine.remove(d, delete_file)
            self.refresh()

    def open_folder(self):
        sel = self.selected()
        open_path(sel[0].folder if sel else self.engine.settings["folder"])

    def open_file(self):
        sel = self.selected()
        if sel and sel[0].status == DONE:
            open_path(sel[0].path)

    def copy_link(self):
        sel = self.selected()
        if sel:
            self.root.clipboard_clear()
            self.root.clipboard_append(sel[0].url)
            self._last_clip = sel[0].url

    def on_double(self, _):
        sel = self.selected()
        if not sel:
            return
        d = sel[0]
        if d.status == DONE:
            open_path(d.path)
        elif d.status == DOWNLOADING:
            self.engine.pause(d)
        else:
            self.engine.resume(d)
            if d.status == QUEUED and d.error:
                d.error = ""

    def on_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(e.x_root, e.y_root)

    def close(self):
        active = [d for d in self.engine.downloads if d.status == DOWNLOADING]
        if active and not messagebox.askyesno(
                "FastDM", "في تحميلات شغالة. هتتوقف وتقدر تكملها لما تفتح البرنامج تاني.\nخروج؟"):
            return
        self.engine.shutdown()
        self.bridge.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("FastDM", "البرنامج شغال بالفعل.")
        sys.exit(0)
    try:
        App().run()
    except Exception:  # noqa
        import traceback
        from engine import data_dir
        err = traceback.format_exc()
        try:
            with open(os.path.join(data_dir(), "crash.log"), "w", encoding="utf-8") as f:
                f.write(err)
        except OSError:
            pass
        print(err)
        try:
            messagebox.showerror("FastDM", "حصل خطأ والبرنامج قفل:\n\n" + err[-800:])
        except Exception:  # noqa
            pass
        sys.exit(1)
