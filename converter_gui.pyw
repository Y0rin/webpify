"""Window version of convert.py. Double-click "Open WebPify.bat" to open it."""

import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from convert import BACKGROUND_TARGET, OBJECT_TARGET, clean_name, convert_files, list_pngs

try:
    import sv_ttk  # modern Windows 11 style theme (pip install sv-ttk)
except ImportError:
    sv_ttk = None

SETTINGS = Path(__file__).with_name("settings.json")
ASSETS = Path(__file__).with_name("assets")
TEXT_MIN, TEXT_MAX, TEXT_STEP = 80, 200, 10


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(changes: dict) -> None:
    """Merge changes into settings.json."""
    try:
        data = {**load_settings(), **changes}
        SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def enable_sharp_text() -> None:
    """Stop Windows from blurring the window on high-DPI screens."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:  # show our own icon in the taskbar instead of Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WebPify.App")
    except Exception:
        pass


def set_dark_titlebar(win: tk.Tk, dark: bool) -> None:
    """Match the Windows title bar to the theme (Windows 10 20H1+ / 11)."""
    try:
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16)
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        # nudge Windows into repainting the title bar
        win.attributes("-alpha", 0.99)
        win.attributes("-alpha", 1.0)
    except Exception:
        pass


def format_eta(seconds: float) -> str:
    if seconds < 1:
        return "almost done"
    seconds = round(seconds)
    if seconds < 60:
        return f"about {seconds} s left"
    return f"about {seconds // 60} min {seconds % 60} s left"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WebPify")
        self.dpi_scale = self.winfo_fpixels("1i") / 96
        try:
            self.iconbitmap(default=str(ASSETS / "logo.ico"))
        except tk.TclError:
            pass

        s = load_settings()
        if s.get("geometry"):
            self.geometry(s["geometry"])
        else:
            self.geometry(f"{int(1180 * self.dpi_scale)}x{int(760 * self.dpi_scale)}")
        self.minsize(int(900 * self.dpi_scale), int(560 * self.dpi_scale))
        if s.get("zoomed"):
            self.state("zoomed")

        self.source_mode = tk.StringVar(value=s.get("source_mode", "folder"))
        self.folder = tk.StringVar(value=s.get("source", ""))
        self.files: list[Path] = []
        self.files_text = tk.StringVar()
        self.output = tk.StringVar(value=s.get("output", ""))
        self.mode = tk.StringVar(value="width" if s.get("mode") == "width" else "auto")
        self.width = tk.StringVar(value=str(s.get("width", 560)))
        self.prefix = tk.StringVar(value=s.get("prefix", ""))
        self.trim = tk.BooleanVar(value=s.get("trim", True))
        self.force = tk.BooleanVar(value=False)
        self.dark = tk.BooleanVar(value=s.get("dark", True))
        self.text_size = tk.IntVar(value=s.get("text_size", 100))
        self.results = queue.Queue()
        self.running = False

        self._apply_theme()
        self._setup_fonts()
        self._build()
        self._build_settings()
        self._apply_text_size()

        for var in (self.folder, self.prefix):
            var.trace_add("write", lambda *_: self._refresh_preview())
        self.mode.trace_add("write", lambda *_: self._refresh_mode())
        self.source_mode.trace_add("write", lambda *_: self._refresh_source_mode())
        self._refresh_mode()
        self._refresh_source_mode()

        self.bind_all("<Control-plus>", lambda e: self._bump_text(+TEXT_STEP))
        self.bind_all("<Control-equal>", lambda e: self._bump_text(+TEXT_STEP))
        self.bind_all("<Control-KP_Add>", lambda e: self._bump_text(+TEXT_STEP))
        self.bind_all("<Control-minus>", lambda e: self._bump_text(-TEXT_STEP))
        self.bind_all("<Control-KP_Subtract>", lambda e: self._bump_text(-TEXT_STEP))
        self.bind_all("<Control-0>", lambda e: self._set_text(100))
        self.bind_all("<Escape>", lambda e: self._close_settings())
        self.bind_all("<Button-1>", self._click_outside_settings, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- theme & text size ----------
    def _apply_theme(self):
        dark = self.dark.get()
        if sv_ttk:
            sv_ttk.set_theme("dark" if dark else "light")
        self.colors = {
            "muted": "#9a9a9a" if dark else "#6b6b6b",
            "error": "#ff6b6b" if dark else "#c42b1c",
        }
        self.after(10, lambda: set_dark_titlebar(self, dark))
        if hasattr(self, "tree"):
            self._style_widgets()

    def _toggle_theme(self):
        self._apply_theme()
        save_settings({"dark": self.dark.get()})

    def _setup_fonts(self):
        """Remember every named font's original size so text size can scale from it."""
        body = tkfont.nametofont("SunValleyBodyFont" if sv_ttk else "TkDefaultFont")
        family = body.cget("family")
        strong = tkfont.nametofont("SunValleyBodyStrongFont").cget("family") if sv_ttk else family
        title = tkfont.nametofont("SunValleyTitleFont").cget("family") if sv_ttk else family
        # keep references: Tk deletes a named font when its Python object is garbage-collected
        self.app_fonts = [
            tkfont.Font(name="AppTitle", family=title, size=-28, weight="normal" if sv_ttk else "bold"),
            tkfont.Font(name="AppSection", family=strong, size=-17, weight="normal" if sv_ttk else "bold"),
        ]
        self.base_fonts = {n: tkfont.nametofont(n).cget("size") for n in tkfont.names()}

    def _apply_text_size(self):
        self.applied_text_size = self.text_size.get()
        factor = self.applied_text_size / 100
        for name, size in self.base_fonts.items():
            if size < 0:   # pixel size: also follow the Windows display scaling
                new = -max(6, round(-size * self.dpi_scale * factor))
            else:          # point size: Tk already applies display scaling
                new = max(5, round(size * factor))
            tkfont.nametofont(name).configure(size=new)
        for col, width in self.column_widths.items():
            self.tree.column(col, width=int(width * self.dpi_scale * factor))
        self.text_label.configure(text=f"{self.applied_text_size}%")
        self._style_widgets()

    def _set_text(self, value: float):
        value = max(TEXT_MIN, min(TEXT_MAX, int(round(value / TEXT_STEP) * TEXT_STEP)))
        self.text_size.set(value)  # snaps the slider to steps of 10
        if value != self.applied_text_size:
            self._apply_text_size()
            save_settings({"text_size": value})

    def _bump_text(self, delta: int):
        self._set_text(self.text_size.get() + delta)

    def _style_widgets(self):
        c = self.colors
        style = ttk.Style(self)
        style.configure("Muted.TLabel", foreground=c["muted"])
        style.configure("Error.TLabel", foreground=c["error"])
        style.configure("Title.TLabel", font="AppTitle")
        style.configure("Section.TLabel", font="AppSection")
        body = tkfont.nametofont("SunValleyBodyFont" if sv_ttk else "TkDefaultFont")
        style.configure("Treeview", rowheight=body.metrics("linespace") + int(14 * self.dpi_scale))
        self.tree.tag_configure("skip", foreground=c["muted"])
        self.tree.tag_configure("fail", foreground=c["error"])

    # ---------- layout ----------
    def _card(self, parent, title: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame" if sv_ttk else "TFrame", padding=16)
        ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        return card

    def _build(self):
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)

        # header
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 16))
        try:
            from PIL import Image, ImageTk
            size = int(56 * self.dpi_scale)
            logo = Image.open(ASSETS / "logo.png").resize((size, size), Image.LANCZOS)
            self.logo_image = ImageTk.PhotoImage(logo)  # keep a reference or Tk drops it
            ttk.Label(header, image=self.logo_image).pack(side="left", padx=(0, 14))
        except Exception:
            pass
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="WebPify", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Trim, scale and convert PNG images to WebP",
                  style="Muted.TLabel").pack(anchor="w")
        self.gear_btn = ttk.Button(header, text="⚙  Settings", command=self._toggle_settings)
        self.gear_btn.pack(side="right", anchor="n")

        # top: two columns of cards
        top = ttk.Frame(root)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1, uniform="col")
        top.columnconfigure(1, weight=1, uniform="col")

        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = self._card(top, "Options")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # --- source card
        src = self._card(left, "Convert")
        src.pack(fill="x")
        toggle = ttk.Frame(src)
        toggle.pack(anchor="w", pady=(0, 10))
        for text, value in (("Folder", "folder"), ("Image(s)", "files")):
            ttk.Radiobutton(toggle, text=text, value=value, variable=self.source_mode,
                            style="Toggle.TButton" if sv_ttk else "TRadiobutton",
                            width=10).pack(side="left", padx=(0, 4))
        row = ttk.Frame(src)
        row.pack(fill="x")
        self.source_entry = ttk.Entry(row)
        self.source_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse_source).pack(side="left", padx=(8, 0))
        self.found_label = ttk.Label(src, style="Muted.TLabel")
        self.found_label.pack(anchor="w", pady=(6, 0))

        # --- output card
        out = self._card(left, "Save to")
        out.pack(fill="x", pady=(20, 0))
        row = ttk.Frame(out)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse_output).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Open", command=self._open_output).pack(side="left", padx=(8, 0))

        # --- options card
        ttk.Radiobutton(right, text="Auto size", variable=self.mode, value="auto").pack(anchor="w")
        ttk.Label(right, style="Muted.TLabel",
                  text=f"600 canvas → object ×{OBJECT_TARGET / 600:g}    "
                       f"1200 canvas → background ×{BACKGROUND_TARGET / 1200:g}"
                  ).pack(anchor="w", padx=(28, 0), pady=(0, 6))
        row = ttk.Frame(right)
        row.pack(anchor="w")
        ttk.Radiobutton(row, text="Exact width", variable=self.mode, value="width").pack(side="left")
        self.width_entry = ttk.Spinbox(row, from_=1, to=10000, width=6, textvariable=self.width)
        self.width_entry.pack(side="left", padx=(10, 6))
        ttk.Label(row, text="px  (560 for covers)", style="Muted.TLabel").pack(side="left")

        ttk.Separator(right).pack(fill="x", pady=12)
        row = ttk.Frame(right)
        row.pack(fill="x")
        ttk.Label(row, text="Name prefix").pack(side="left")
        ttk.Entry(row, textvariable=self.prefix, width=12).pack(side="left", padx=10)
        self.preview_label = ttk.Label(row, style="Muted.TLabel")
        self.preview_label.pack(side="left")

        ttk.Separator(right).pack(fill="x", pady=12)
        switch = "Switch.TCheckbutton" if sv_ttk else "TCheckbutton"
        ttk.Checkbutton(right, text="Trim transparent edges", variable=self.trim,
                        style=switch).pack(anchor="w")
        ttk.Checkbutton(right, text="Overwrite files that already exist", variable=self.force,
                        style=switch).pack(anchor="w", pady=(6, 0))

        # action bar
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=20)
        self.convert_btn = ttk.Button(bar, text="Convert", command=self._start, width=14,
                                      style="Accent.TButton" if sv_ttk else "TButton")
        self.convert_btn.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=16)
        self.summary = ttk.Label(bar, style="Muted.TLabel", text="Ready")
        self.summary.pack(side="left")

        # results table
        table = ttk.Frame(root)
        table.pack(fill="both", expand=True)
        cols = ("file", "new", "original", "type", "factor", "trimmed", "size",
                "before", "after", "status")
        self.tree = ttk.Treeview(table, columns=cols, show="headings")
        self.column_widths = {}
        for col, text, w, anchor in [
            ("file", "File", 150, "w"), ("new", "New name", 170, "w"),
            ("original", "Original", 85, "center"), ("type", "Type", 90, "center"),
            ("factor", "Scale", 60, "center"), ("trimmed", "Trimmed", 85, "center"),
            ("size", "Final", 85, "center"), ("before", "Before", 70, "e"),
            ("after", "After", 70, "e"), ("status", "Status", 120, "w"),
        ]:
            self.column_widths[col] = w
            self.tree.heading(col, text=text)
            self.tree.column(col, width=int(w * self.dpi_scale), anchor=anchor,
                             stretch=col in ("file", "new", "status"))
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

    # ---------- settings overlay ----------
    def _build_settings(self):
        panel = ttk.Frame(self, style="Card.TFrame" if sv_ttk else "TFrame", padding=24)
        self.settings_panel = panel

        head = ttk.Frame(panel)
        head.pack(fill="x", pady=(0, 16))
        ttk.Label(head, text="Settings", style="Title.TLabel").pack(side="left")
        ttk.Button(head, text="✕", width=3, command=self._close_settings).pack(side="right", anchor="n")

        ttk.Label(panel, text="Appearance", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(panel, text="Night mode", variable=self.dark, command=self._toggle_theme,
                        style="Switch.TCheckbutton" if sv_ttk else "TCheckbutton").pack(anchor="w")

        ttk.Separator(panel).pack(fill="x", pady=20)
        ttk.Label(panel, text="Text size", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(panel)
        row.pack(fill="x")
        ttk.Button(row, text="A−", width=3, command=lambda: self._bump_text(-TEXT_STEP)).pack(side="left")
        self.text_scale = ttk.Scale(row, from_=TEXT_MIN, to=TEXT_MAX, variable=self.text_size,
                                    command=lambda v: self._set_text(float(v)))
        self.text_scale.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(row, text="A+", width=3, command=lambda: self._bump_text(+TEXT_STEP)).pack(side="left")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(10, 0))
        self.text_label = ttk.Label(row, style="Section.TLabel")
        self.text_label.pack(side="left")
        ttk.Button(row, text="Reset", command=lambda: self._set_text(100)).pack(side="right")
        ttk.Label(panel, style="Muted.TLabel", justify="left", wraplength=int(300 * self.dpi_scale),
                  text="Text keeps this size when you resize or maximise the window.\n\n"
                       "Shortcuts: Ctrl + to enlarge, Ctrl − to shrink, Ctrl 0 to reset."
                  ).pack(anchor="w", pady=(14, 0))

    def _toggle_settings(self):
        if self.settings_panel.winfo_ismapped():
            self._close_settings()
        else:
            self.settings_panel.place(relx=1, rely=0, relheight=1, anchor="ne")
            self.settings_panel.lift()

    def _close_settings(self):
        self.settings_panel.place_forget()

    def _click_outside_settings(self, event):
        if not self.settings_panel.winfo_ismapped():
            return
        w = str(event.widget)
        if not (w.startswith(str(self.settings_panel)) or w == str(self.gear_btn)):
            self._close_settings()

    def _on_close(self):
        zoomed = self.state() == "zoomed"
        changes = {"zoomed": zoomed}
        if not zoomed:
            changes["geometry"] = self.wm_geometry()
        save_settings(changes)
        self.destroy()

    # ---------- source / output ----------
    def _sources(self) -> list[Path]:
        if self.source_mode.get() == "files":
            return self.files
        folder = Path(self.folder.get().strip())
        return list_pngs(folder) if self.folder.get().strip() and folder.is_dir() else []

    def _browse_source(self):
        if self.source_mode.get() == "files":
            start = self.files[0].parent if self.files else (self.folder.get() or None)
            picked = filedialog.askopenfilenames(
                initialdir=start, title="Choose PNG images",
                filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
            if picked:
                self.files = [Path(p) for p in picked]
                self._show_files()
        else:
            folder = filedialog.askdirectory(initialdir=self.folder.get() or None)
            if folder:
                self.folder.set(os.path.normpath(folder))

    def _browse_output(self):
        folder = filedialog.askdirectory(initialdir=self.output.get() or None)
        if folder:
            self.output.set(os.path.normpath(folder))

    def _show_files(self):
        self.files_text.set(", ".join(f.name for f in self.files))
        self._refresh_preview()

    def _open_output(self):
        out = self.output.get().strip()
        if out and Path(out).is_dir():
            os.startfile(out)
        else:
            messagebox.showinfo("Output folder", "The output folder doesn't exist yet.")

    def _refresh_source_mode(self):
        if self.source_mode.get() == "files":
            self.source_entry.configure(textvariable=self.files_text, state="readonly")
            self._show_files()
        else:
            self.source_entry.configure(textvariable=self.folder, state="normal")
            self._refresh_preview()

    def _refresh_mode(self):
        self.width_entry.configure(state="normal" if self.mode.get() == "width" else "disabled")

    def _refresh_preview(self):
        pngs = self._sources()
        if self.source_mode.get() == "files":
            text = f"{len(pngs)} image(s) selected" if pngs else "Click Browse to pick one or more PNGs"
            self.found_label.configure(text=text, style="Muted.TLabel")
        elif not self.folder.get().strip():
            self.found_label.configure(text="Pick a folder of PNG files", style="Muted.TLabel")
        elif not Path(self.folder.get().strip()).is_dir():
            self.found_label.configure(text="Folder not found", style="Error.TLabel")
        else:
            self.found_label.configure(text=f"{len(pngs)} PNG file(s) found", style="Muted.TLabel")
        sample = pngs[0].stem if pngs else "Left Ear-2"
        self.preview_label.configure(text=f"→ {clean_name(sample, self.prefix.get())}")

    # ---------- conversion ----------
    def _start(self):
        files = list(self._sources())
        out_text = self.output.get().strip()
        if not files:
            what = "one or more PNG images" if self.source_mode.get() == "files" else "a folder that contains PNG files"
            messagebox.showerror("Nothing to convert", f"Please choose {what}.")
            return
        if not out_text:
            messagebox.showerror("Save to", "Please choose where to save the WebP files.")
            return
        width = None
        if self.mode.get() == "width":
            try:
                width = int(self.width.get())
                if width <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Width", "Width must be a whole number above 0.")
                return

        save_settings({
            "source_mode": self.source_mode.get(), "source": self.folder.get().strip(),
            "output": out_text, "mode": self.mode.get(), "width": self.width.get(),
            "prefix": self.prefix.get(), "trim": self.trim.get(),
        })
        self.tree.delete(*self.tree.get_children())
        self.convert_btn.configure(state="disabled")
        self.counts = {"ok": 0, "skip": 0, "fail": 0}
        self.kb = [0.0, 0.0]

        # Time estimate: work is measured in bytes of PNGs that will really be
        # converted (skipped files take no time), so big backgrounds count more.
        output, prefix, force = Path(out_text), self.prefix.get(), self.force.get()
        self.job_sizes = []
        for f in files:
            will_skip = not force and (output / clean_name(f.stem, prefix)).exists()
            try:
                size = 0 if will_skip else f.stat().st_size
            except OSError:
                size = 0
            self.job_sizes.append(size)
        self.job_total = sum(self.job_sizes)
        self.job_done_bytes = 0
        self.job_index = 0
        self.job_started = time.monotonic()
        self.job_finish_at = None
        self.progress.configure(value=0)
        self.running = True
        self._update_progress_text()

        args = (files, output, width, prefix, force, self.trim.get())
        threading.Thread(target=self._worker, args=args, daemon=True).start()
        self.after(50, self._poll)

    def _worker(self, *args):
        try:
            for r in convert_files(*args):
                self.results.put(r)
        except Exception as e:
            self.results.put({"status": "error", "error": str(e)})
        self.results.put(None)

    def _poll(self):
        while True:
            try:
                r = self.results.get_nowait()
            except queue.Empty:
                self._update_progress_text()
                self.after(100, self._poll)
                return
            if r is None:
                self._finish()
                return
            self._add_row(r)

    def _update_progress_text(self):
        n = len(self.job_sizes)
        if self.job_finish_at is None:
            eta = "estimating…"
        else:
            eta = format_eta(self.job_finish_at - time.monotonic())
        self.summary.configure(text=f"{self.job_index} / {n}  ·  {eta}")

    def _add_row(self, r: dict):
        if r["status"] == "error":
            messagebox.showerror("Error", r["error"])
            return
        # progress + estimate
        if self.job_index < len(self.job_sizes):
            self.job_done_bytes += self.job_sizes[self.job_index]
        self.job_index += 1
        now = time.monotonic()
        if self.job_total:
            self.progress.configure(value=100 * self.job_done_bytes / self.job_total)
            if self.job_done_bytes:
                elapsed = now - self.job_started
                left = elapsed * (self.job_total - self.job_done_bytes) / self.job_done_bytes
                self.job_finish_at = now + left
        else:
            self.progress.configure(value=100 * self.job_index / len(self.job_sizes))

        # table row
        self.counts[r["status"]] += 1
        blank = ("",) * 7
        if r["status"] == "ok":
            self.kb[0] += r["kb_before"]
            self.kb[1] += r["kb_after"]
            px = lambda s: f"{s[0]}×{s[1]}"
            values = (r["src"], r["out"], px(r["original"]), r["type"], f"×{r['factor']:.2f}",
                      px(r["trimmed"]), px(r["size"]), f"{r['kb_before']:.1f} KB",
                      f"{r['kb_after']:.1f} KB", "✓ Converted")
        elif r["status"] == "skip":
            values = (r["src"], r["out"], *blank, "Skipped (exists)")
        else:
            values = (r["src"], r["out"], *blank, f"Failed: {r['error']}")
        item = self.tree.insert("", "end", values=values, tags=(r["status"],))
        self.tree.see(item)

    def _finish(self):
        self.running = False
        self.convert_btn.configure(state="normal")
        self.progress.configure(value=100)
        c = self.counts
        took = time.monotonic() - self.job_started
        text = f"{c['ok']} converted · {c['skip']} skipped · {c['fail']} failed  ·  {took:.1f} s"
        if c["ok"]:
            text += f"   |   {self.kb[0]:.0f} KB → {self.kb[1]:.0f} KB"
        if c["skip"]:
            text += "   (turn on Overwrite to redo skipped)"
        self.summary.configure(text=text)


if __name__ == "__main__":
    enable_sharp_text()
    App().mainloop()
