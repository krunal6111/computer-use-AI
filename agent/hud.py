"""A small always-on-top window showing the agent's current step live.

Tkinter must run its mainloop on the main thread, so the actual agent loop
(run_task / the CLI's task loop) runs on a background thread instead, and
pushes updates here through a thread-safe queue. Call Hud.run_in_background()
with the work function, then Hud.start() on the main thread.
"""

import contextlib
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass

WIDTH, HEIGHT = 380, 300
MAX_ROWS = 8
BG = "#111318"
PANEL = "#1b1e26"
ACCENT = "#5b8cff"
OK = "#4caf6d"
ERR = "#e5534b"
MUTED = "#767d8c"
TEXT = "#e8eaf0"


@dataclass
class _Row:
    text: str
    kind: str  # "step" | "action" | "done" | "error" | "info"
    done: bool = False


class Hud:
    """Owns the Tk window. Thread-safe: other threads call .post()/.close()."""

    def __init__(self, title="Agent"):
        self._queue: queue.Queue = queue.Queue()
        self._title = title
        self._root = None
        self._rows: list[_Row] = []
        self._spin_idx = 0
        self._closing = False

    # -- public, thread-safe API (call these from the worker thread) --------

    def post(self, text: str, kind: str = "step"):
        self._queue.put(("row", text, kind))

    def finish_last(self, kind: str = "done"):
        self._queue.put(("finish", None, kind))

    def close(self):
        self._queue.put(("close", None, None))

    @contextlib.contextmanager
    def hide_for_capture(self):
        """Hide the window for a screenshot, then restore it. Blocks the
        calling (worker) thread until Tk confirms each state change, so the
        caller never captures a frame with the HUD still on screen."""
        if not self._root or self._closing:
            yield
            return
        hidden = threading.Event()
        self._queue.put(("hide", hidden, None))
        hidden.wait(timeout=1.0)
        try:
            yield
        finally:
            shown = threading.Event()
            self._queue.put(("show", shown, None))
            shown.wait(timeout=1.0)

    # -- main-thread API ------------------------------------------------

    def run(self, work, *work_args):
        """Start `work(self, *work_args)` on a background thread, then block
        this (main) thread running the Tk event loop until the HUD closes."""
        t = threading.Thread(target=self._run_worker, args=(work, work_args), daemon=True)
        t.start()
        self._build_window()
        self._root.after(80, self._drain_queue)
        self._root.mainloop()

    def _run_worker(self, work, work_args):
        try:
            work(self, *work_args)
        finally:
            self.close()

    # -- window construction ----------------------------------------------

    def _build_window(self):
        root = tk.Tk()
        root.title(self._title)
        root.configure(bg=BG)
        root.geometry(f"{WIDTH}x{HEIGHT}+40+40")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        try:
            root.attributes("-alpha", 0.96)
        except tk.TclError:
            pass

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 6))
        self._dot = tk.Canvas(header, width=10, height=10, bg=BG, highlightthickness=0)
        self._dot.pack(side="left", padx=(0, 8))
        self._dot_id = self._dot.create_oval(1, 1, 9, 9, fill=ACCENT, outline="")
        tk.Label(header, text=self._title, bg=BG, fg=TEXT,
                 font=("Sans", 11, "bold")).pack(side="left")

        self._canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._list = tk.Frame(self._canvas, bg=BG)
        self._list_window = self._canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._list_window, width=e.width))

        self._row_widgets: list[tuple[tk.Frame, tk.Canvas, tk.Label]] = []
        self._root = root
        root.protocol("WM_DELETE_WINDOW", self._on_user_close)
        self._pulse()

    def _on_user_close(self):
        self._closing = True
        self._root.destroy()

    # -- animation ----------------------------------------------------------

    def _pulse(self):
        if self._closing or not self._root:
            return
        self._spin_idx = (self._spin_idx + 1) % 20
        glow = 0.5 + 0.5 * abs(10 - self._spin_idx) / 10
        color = _blend(ACCENT, BG, glow)
        try:
            self._dot.itemconfig(self._dot_id, fill=color)
        except tk.TclError:
            return
        if self._rows and not self._rows[-1].done:
            self._animate_last_row()
        self._root.after(90, self._pulse)

    def _animate_last_row(self):
        if not self._row_widgets:
            return
        _, spinner_canvas, _ = self._row_widgets[-1]
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        frame = frames[self._spin_idx % len(frames)]
        try:
            spinner_canvas.itemconfig(spinner_canvas.find_all()[0], text=frame)
        except (tk.TclError, IndexError):
            pass

    # -- queue processing (main thread) --------------------------------------

    def _drain_queue(self):
        if self._closing or not self._root:
            return
        try:
            while True:
                kind, text, extra = self._queue.get_nowait()
                if kind == "row":
                    self._add_row(text, extra)
                elif kind == "finish":
                    self._finish_last(extra)
                elif kind == "hide":
                    self._root.withdraw()
                    self._root.update_idletasks()
                    text.set()  # `text` holds the threading.Event here
                elif kind == "show":
                    self._root.deiconify()
                    self._root.attributes("-topmost", True)
                    self._root.update_idletasks()
                    text.set()
                elif kind == "close":
                    self._closing = True
                    self._root.after(900, self._root.destroy)
                    return
        except queue.Empty:
            pass
        self._root.after(80, self._drain_queue)

    def _add_row(self, text, kind):
        self._rows.append(_Row(text, kind))
        if len(self._rows) > MAX_ROWS:
            self._rows.pop(0)
            if self._row_widgets:
                old_frame, _, _ = self._row_widgets.pop(0)
                old_frame.destroy()

        row = tk.Frame(self._list, bg=BG)
        row.pack(fill="x", pady=2)
        marker = tk.Canvas(row, width=18, height=18, bg=BG, highlightthickness=0)
        marker.pack(side="left")
        marker.create_text(9, 9, text="⠋", fill=ACCENT, font=("Sans", 10))
        label = tk.Label(row, text=text, bg=BG, fg=TEXT, font=("Sans", 9),
                         justify="left", anchor="w", wraplength=WIDTH - 60)
        label.pack(side="left", fill="x", expand=True)
        self._row_widgets.append((row, marker, label))
        self._canvas.after(10, lambda: self._canvas.yview_moveto(1.0))

    def _finish_last(self, kind):
        if not self._rows or not self._row_widgets:
            return
        self._rows[-1].done = True
        self._rows[-1].kind = kind
        _, marker, label = self._row_widgets[-1]
        glyph, color = {
            "done": ("✓", OK),
            "error": ("✗", ERR),
        }.get(kind, ("•", MUTED))
        try:
            marker.itemconfig(marker.find_all()[0], text=glyph, fill=color)
            label.configure(fg=color if kind == "error" else TEXT)
        except tk.TclError:
            pass


def _blend(hex_a, hex_b, t):
    a = tuple(int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(a[i] * t + b[i] * (1 - t)) for i in range(3))
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"
