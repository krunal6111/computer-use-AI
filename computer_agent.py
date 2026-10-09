#!/usr/bin/env python3
"""
computer_agent.py - real computer use on Ubuntu (X11).

A plain agent loop:  screenshot -> model picks an action -> run it with
pyautogui -> new screenshot -> ... until the model says it's done.

Backends
  gemini  Google AI Studio (GEMINI_API_KEY). Uses Gemini's *native* Computer
          Use tool with ENVIRONMENT_DESKTOP, i.e. the action set the model was
          trained on (click, type, hotkey, scroll, ... in 0-999 coordinates).
  nim     NVIDIA NIM, OpenAI-compatible (NVIDIA_API_KEY). Declares a standard
          `computer` function tool. Works with vision models that do GUI
          grounding in 0-1000 normalized coordinates, e.g. google/gemma-4-31b-it.

Usage
  ./computer_agent.py "Open the Files app and create a folder named test"
  ./computer_agent.py --backend nim "Open Firefox and search for Ubuntu 26.04"
  ./computer_agent.py                  # asks you for tasks one at a time

Safety
  Actions run on your REAL desktop, without asking, unless you pass --confirm.
  To abort: press Ctrl+C in this terminal, or shove the mouse into the
  top-left corner of the screen (pyautogui fail-safe).
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash-lite",
    "nim": "google/gemma-4-31b-it",
}
# Tried in order when the current Gemini model is overloaded (503) or times out.
GEMINI_FALLBACKS = ["gemini-3.5-flash", "gemini-3.8-flash"]
# Less thinking = faster answers. flash-lite at "minimal" still clicked
# accurately in testing (5s vs 11s at the default); 3.8-flash rejects "minimal".
GEMINI_THINKING = {"gemini-3.5-flash-lite": "minimal"}
GEMINI_DEFAULT_THINKING = "low"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SCREENSHOT_WIDTH = 1280  # width sent to the model (JPEG): ~100KB vs ~320KB PNG at 1440
KEEP_SCREENSHOTS = 2     # older screenshots are dropped from history to save tokens
SETTLE_SECONDS = 0.5     # wait after an action so the UI can update...
SLOW_SETTLE_SECONDS = 2.0  # ...longer after actions that load a page or app
REQUEST_TIMEOUT = 90     # seconds per model call
MAX_RETRIES = 8
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You are operating a real Ubuntu Linux desktop (GNOME on X11), \
{width}x{height} pixels, through mouse and keyboard actions. After every action \
you receive a fresh screenshot.

Guidelines:
- Use as few steps as possible.
- To open a website, call `open_url` with the full URL. It opens in the default \
browser (Google Chrome), so never launch the browser by hand first.
- To search a site, open its search URL directly instead of typing into its \
search box, e.g. https://www.youtube.com/results?search_query=lofi+music or \
https://www.google.com/search?q=weather+today
- To launch an app, press the Super key, type the app name, then press Enter.
- Prefer reliable keyboard shortcuts (ctrl+l for a browser address bar, etc).
- When you don't need to see the screen in between, return several actions \
at once (e.g. click a text field, then type into it).
- Check each new screenshot to confirm the last action worked; if it didn't, \
try a different approach instead of repeating it.
- The terminal window running you may be visible. Do not type into it or close it.
- When the task is complete, reply with a one or two sentence summary and no \
further actions. If you truly cannot proceed, explain why and stop."""

NIM_EXTRA_PROMPT = """
Use the `computer` tool for every action. Coordinates are normalized to \
0-1000 on each axis: [0, 0] is the top-left of the screenshot and \
[1000, 1000] the bottom-right."""


# --------------------------------------------------------------------------
# Desktop: screenshots + mouse/keyboard
# --------------------------------------------------------------------------

_KEY_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "control_l": "ctrl", "control_r": "ctrlright",
    "super": "win", "super_l": "win", "super_r": "winright", "meta": "win",
    "cmd": "win", "windows": "win", "return": "enter", "kp_enter": "enter",
    "esc": "escape", "del": "delete", "bksp": "backspace", "spacebar": "space",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "page_up": "pageup", "page_down": "pagedown", "pgup": "pageup", "pgdn": "pagedown",
    "alt_l": "alt", "alt_r": "altright", "shift_l": "shift", "shift_r": "shiftright",
    "print": "printscreen",
}


class ActionError(Exception):
    """An action the model asked for could not be carried out."""


class Desktop:
    """The real X11 desktop, driven by pyautogui."""

    def __init__(self):
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self.gui = pyautogui
        self.width, self.height = pyautogui.size()

    # -- observation ------------------------------------------------------

    def screenshot(self) -> bytes:
        return encode_screenshot(self.gui.screenshot())

    # -- helpers ----------------------------------------------------------

    def _to_px(self, x, y):
        """Model coordinates (0-1000 on each axis) -> screen pixels."""
        px = int(round(float(x) / 1000 * self.width))
        py = int(round(float(y) / 1000 * self.height))
        return min(max(px, 0), self.width - 1), min(max(py, 0), self.height - 1)

    def _xy(self, a, xk="x", yk="y", ck="coordinate", required=True):
        if a.get(ck):
            return self._to_px(*a[ck][:2])
        if a.get(xk) is not None and a.get(yk) is not None:
            return self._to_px(a[xk], a[yk])
        if required:
            raise ActionError(f"missing coordinates ({xk}/{yk} or {ck})")
        return None

    def _key(self, k):
        k = str(k).strip()
        name = _KEY_ALIASES.get(k.lower(), k.lower())
        if len(k) == 1:
            return k  # keep case for single characters
        if name not in self.gui.KEYBOARD_KEYS:
            raise ActionError(f"unknown key {k!r}")
        return name

    def _keys(self, a):
        keys = a.get("keys") or a.get("key") or a.get("text") or ""
        if isinstance(keys, str):
            keys = keys.split("+") if len(keys) > 1 and "+" in keys else [keys]
        keys = [self._key(k) for k in keys if str(k).strip()]
        # In a combo, "T" means the T key (ctrl+shift+T), not a shifted character.
        return [k.lower() for k in keys] if len(keys) > 1 else keys

    def _type(self, text):
        if text.isascii():
            self.gui.write(text, interval=0.02)
            return
        # pyautogui can only type ASCII; paste anything else via the clipboard.
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        self.gui.hotkey("ctrl", "v")

    # -- actions ----------------------------------------------------------

    def execute(self, name, a) -> str:
        """Run one action. Returns a short text result for the model."""
        g = self.gui
        name = {
            "left_click": "click", "mouse_move": "move", "hover": "move",
            "left_click_drag": "drag_and_drop", "key": "press_key",
            "screenshot": "take_screenshot", "open_url": "navigate",
        }.get(name, name)

        if name in ("click", "double_click", "triple_click", "right_click", "middle_click"):
            x, y = self._xy(a)
            button = {"right_click": "right", "middle_click": "middle"}.get(name, "left")
            clicks = {"double_click": 2, "triple_click": 3}.get(name, 1)
            g.click(x, y, clicks=clicks, interval=0.08, button=button)
            return f"{name} at ({x}, {y})"

        if name == "move":
            x, y = self._xy(a)
            g.moveTo(x, y, duration=0.2)
            return f"moved to ({x}, {y})"

        if name in ("mouse_down", "mouse_up"):
            xy = self._xy(a, required=False)
            if xy:
                g.moveTo(*xy)
            (g.mouseDown if name == "mouse_down" else g.mouseUp)()
            return name

        if name == "drag_and_drop":
            if a.get("coordinate") and a.get("end_coordinate"):
                start, end = self._to_px(*a["coordinate"][:2]), self._to_px(*a["end_coordinate"][:2])
            else:
                start = self._xy(a, "start_x", "start_y", "start_coordinate")
                end = self._xy(a, "end_x", "end_y", "end_coordinate")
            g.moveTo(*start)
            g.dragTo(*end, duration=0.6, button="left")
            return f"dragged {start} -> {end}"

        if name == "type":
            text = str(a.get("text", ""))
            xy = self._xy(a, required=False)
            if xy:
                g.click(*xy)
            if a.get("clear_before_typing"):
                g.hotkey("ctrl", "a")
                g.press("backspace")
            self._type(text)
            if a.get("press_enter"):
                g.press("enter")
            return f"typed {len(text)} characters"

        if name in ("press_key", "hotkey"):
            keys = self._keys(a)
            if not keys:
                raise ActionError("no key given")
            g.hotkey(*keys) if len(keys) > 1 else g.press(keys[0])
            return f"pressed {'+'.join(keys)}"

        if name in ("key_down", "key_up"):
            key = self._keys(a)[0]
            (g.keyDown if name == "key_down" else g.keyUp)(key)
            return f"{name} {key}"

        if name == "scroll":
            xy = self._xy(a, required=False)
            if xy:
                g.moveTo(*xy)
            direction = str(a.get("direction", "down")).lower()
            amount = int(a.get("magnitude_in_wheel_clicks") or a.get("amount") or 5)
            if direction in ("up", "down"):
                g.scroll(amount if direction == "up" else -amount)
            elif direction in ("left", "right"):
                g.hscroll(amount if direction == "right" else -amount)
            else:
                raise ActionError(f"bad scroll direction {direction!r}")
            return f"scrolled {direction} {amount}"

        if name == "wait":
            seconds = min(float(a.get("seconds") or a.get("duration") or 2), 30)
            time.sleep(seconds)
            return f"waited {seconds:g}s"

        if name == "take_screenshot":
            return "screenshot taken"

        if name == "navigate":
            webbrowser.open(str(a["url"]))
            return f"opened {a['url']} in the default browser"

        if name in ("go_back", "go_forward"):
            g.hotkey("alt", "left" if name == "go_back" else "right")
            return name

        raise ActionError(f"unsupported action {name!r}")


def encode_screenshot(img: Image.Image, width=SCREENSHOT_WIDTH) -> bytes:
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Model backends
# --------------------------------------------------------------------------


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    intent: str = ""
    needs_confirmation: str = ""  # explanation, when the model asks for it
    raw: object = field(default=None, repr=False)


@dataclass
class ToolResult:
    call: ToolCall
    output: str
    screenshot: bytes
    acknowledged: bool = False
    error: bool = False


OPEN_URL_SCHEMA = {"type": "object", "properties": {"url": {"type": "string"}},
                   "required": ["url"]}


class GeminiBackend:
    """Gemini with the built-in Computer Use tool (desktop environment)."""

    def __init__(self, model, screen_w, screen_h, fallbacks=(), thinking=None):
        from google import genai
        from google.genai import types

        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            sys.exit("Set GEMINI_API_KEY in .env first.")
        self.t = types
        self.models = [model] + [m for m in fallbacks if m != model]
        self.current = 0
        self.thinking = thinking
        # The SDK otherwise retries 5x with up to 60s waits on its own, on top of
        # with_retries(); one retry layer that can switch models is much faster.
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,
            retry_options=types.HttpRetryOptions(attempts=1)))
        self.system = SYSTEM_PROMPT.format(width=screen_w, height=screen_h)
        self.contents = []

    @property
    def model(self):
        return self.models[self.current]

    def _config(self, model):
        t = self.t
        level = self.thinking or GEMINI_THINKING.get(model, GEMINI_DEFAULT_THINKING)
        return t.GenerateContentConfig(
            system_instruction=self.system,
            tools=[
                t.Tool(computer_use=t.ComputerUse(
                    environment=t.Environment.ENVIRONMENT_DESKTOP)),
                # Desktop mode has no `navigate` action (only browser mode does),
                # so without this the model launches Chrome by hand: 4+ slow steps.
                t.Tool(function_declarations=[t.FunctionDeclaration(
                    name="open_url",
                    description="Open a URL in the default web browser (Google Chrome). "
                                "Fastest way to open any website or search results page.",
                    parameters_json_schema=OPEN_URL_SCHEMA,
                )]),
            ],
            thinking_config=t.ThinkingConfig(thinking_level=level.upper()),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )

    def begin(self, task, screenshot):
        t = self.t
        self.contents = [t.Content(role="user", parts=[
            t.Part(text=task),
            t.Part.from_bytes(data=screenshot, mime_type="image/jpeg"),
        ])]

    def _generate(self):
        model = self.model
        try:
            return self.client.models.generate_content(
                model=model, contents=self.contents, config=self._config(model))
        except Exception as e:
            status = _status(e)
            if status == 400 and self.current != 0:
                # A fallback model that can't take over this conversation (or this
                # config). Drop it and go back to the main model.
                print(f"   ... {model} can't continue this task, going back to {self.models[0]}")
                self.models.pop(self.current)
                self.current = 0
                raise RetryNow(str(e)) from e
            if len(self.models) > 1 and (status in RETRYABLE_STATUS or _is_network_error(e)):
                self.current = (self.current + 1) % len(self.models)
                print(f"   ... {model} is busy ({status or type(e).__name__}), "
                      f"switching to {self.model}")
                if self.current != 0:
                    raise RetryNow(str(e)) from e  # a different model: no need to wait
            raise  # every model tried: back off before starting over

    def next_actions(self):
        resp = self._generate()
        if not resp.candidates or not resp.candidates[0].content:
            return "(the model returned an empty response)", []
        content = resp.candidates[0].content
        self.contents.append(content)  # keep as-is: carries thought signatures

        text = " ".join(p.text for p in content.parts or [] if p.text).strip()
        calls = []
        for p in content.parts or []:
            fc = p.function_call
            if not fc:
                continue
            args = dict(fc.args or {})
            safety = args.pop("safety_decision", None) or {}
            calls.append(ToolCall(
                id=fc.id, name=fc.name, args=args,
                intent=args.pop("intent", ""),
                needs_confirmation=(safety.get("explanation") or "yes")
                if safety.get("decision") == "require_confirmation" else "",
            ))
        return text, calls

    def add_results(self, results):
        t = self.t
        parts = []
        for r in results:
            response = {"error": r.output} if r.error else {"output": r.output}
            if r.acknowledged:
                response["safety_acknowledgement"] = "true"
            parts.append(t.Part(function_response=t.FunctionResponse(
                id=r.call.id, name=r.call.name, response=response,
                parts=[t.FunctionResponsePart(inline_data=t.FunctionResponseBlob(
                    mime_type="image/jpeg", data=r.screenshot))],
            )))
        self.contents.append(t.Content(role="user", parts=parts))
        self._trim()

    def _trim(self):
        """Drop all but the newest KEEP_SCREENSHOTS images from history."""
        seen = 0
        for content in reversed(self.contents):
            if content.role != "user":
                continue
            for p in content.parts:
                fr = p.function_response
                if fr and fr.parts:
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        fr.parts = None
                elif p.inline_data:
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        p.inline_data = None
                        p.text = "[older screenshot removed]"


NIM_COMPUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "computer",
        "description": "Control the mouse and keyboard of the Ubuntu desktop. "
                       "Coordinates are [x, y] normalized to 0-1000 on each axis.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["left_click", "double_click", "triple_click", "right_click",
                             "middle_click", "mouse_move", "left_click_drag", "type",
                             "key", "scroll", "wait", "open_url"],
                    "description": "left_click/double_click/triple_click/right_click/"
                                   "middle_click/mouse_move need `coordinate`. "
                                   "left_click_drag needs `coordinate` (start) and "
                                   "`end_coordinate`. type needs `text`. key needs "
                                   "`text`, e.g. 'Return', 'ctrl+s', 'super'. scroll "
                                   "needs `direction` and optional `coordinate`, `amount`. "
                                   "open_url needs `url` (opens it in the default browser).",
                },
                "url": {"type": "string"},
                "coordinate": {"type": "array", "items": {"type": "number"},
                               "description": "[x, y], each 0-1000"},
                "end_coordinate": {"type": "array", "items": {"type": "number"}},
                "text": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "description": "scroll wheel clicks, default 5"},
                "press_enter": {"type": "boolean"},
                "seconds": {"type": "number"},
            },
            "required": ["action"],
        },
    },
}


class NimBackend:
    """Any OpenAI-compatible vision model on NVIDIA NIM, via a `computer` tool."""

    def __init__(self, model, screen_w, screen_h, **_):
        self.key = os.environ.get("NVIDIA_API_KEY")
        if not self.key:
            sys.exit("Set NVIDIA_API_KEY in .env first.")
        self.model = model
        self.system = SYSTEM_PROMPT.format(width=screen_w, height=screen_h) + NIM_EXTRA_PROMPT
        self.messages = []

    @staticmethod
    def _image(jpeg):
        return {"type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}

    def begin(self, task, screenshot):
        self.messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": [{"type": "text", "text": task}, self._image(screenshot)]},
        ]

    def next_actions(self):
        r = requests.post(NIM_URL, timeout=REQUEST_TIMEOUT,
                          headers={"Authorization": f"Bearer {self.key}"},
                          json={"model": self.model, "messages": self.messages,
                                "tools": [NIM_COMPUTER_TOOL], "tool_choice": "auto",
                                "temperature": 0.2, "max_tokens": 2048})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        self.messages.append({"role": "assistant", "content": msg.get("content") or "",
                              **({"tool_calls": tool_calls} if tool_calls else {})})
        calls = []
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc["id"], name=args.pop("action", "?"), args=args))
        return (msg.get("content") or "").strip(), calls

    def add_results(self, results):
        for r in results:
            self.messages.append({"role": "tool", "tool_call_id": r.call.id,
                                  "content": ("ERROR: " if r.error else "") + r.output})
        # Most OpenAI-compatible servers only accept images in user messages.
        self.messages.append({"role": "user", "content": [
            {"type": "text", "text": "Screenshot after your action(s):"},
            self._image(results[-1].screenshot)]})
        self._trim()

    def _trim(self):
        seen = 0
        for m in reversed(self.messages):
            if m["role"] == "user" and isinstance(m["content"], list):
                for i, part in enumerate(m["content"]):
                    if part.get("type") == "image_url":
                        seen += 1
                        if seen > KEEP_SCREENSHOTS:
                            m["content"][i] = {"type": "text", "text": "[older screenshot removed]"}


BACKENDS = {"gemini": GeminiBackend, "nim": NimBackend}


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


class RetryNow(Exception):
    """Raised by a backend to ask for an immediate retry (e.g. after switching model)."""


def _status(e):
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code
    return getattr(getattr(e, "response", None), "status_code", None)


def _is_network_error(e):
    import httpx  # used by google-genai

    return isinstance(e, (requests.Timeout, requests.ConnectionError,
                          httpx.TimeoutException, httpx.NetworkError))


def with_retries(fn):
    """Call fn(), retrying overloads / rate limits / network blips with backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except RetryNow:
            continue
        except Exception as e:
            status = _status(e)
            daily_quota = status == 429 and "PerDay" in str(e)
            retryable = status in RETRYABLE_STATUS or _is_network_error(e)
            if attempt == MAX_RETRIES or daily_quota or not retryable:
                raise
            reason = {429: "Rate limited", 503: "Model overloaded"}.get(
                status, "Timed out" if _is_network_error(e) else "Temporary error")
            delay = min(2 ** (attempt - 1), 15)
            print(f"   ... {reason} ({status or type(e).__name__}), retrying in {delay}s "
                  f"[{attempt}/{MAX_RETRIES - 1}]")
            time.sleep(delay)


def ask_yes_no(question, default=False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"   ?? {question} {hint} ").strip().lower()
    except EOFError:
        return False
    return default if not answer else answer in ("y", "yes")


def settle_time(call):
    """How long to wait after an action before taking the next screenshot."""
    a = call.args
    loads_something = (
        call.name in ("navigate", "open_url")
        or a.get("press_enter")
        or str(a.get("key") or a.get("text") or "").lower() in ("enter", "return", "super", "win")
    )
    return SLOW_SETTLE_SECONDS if loads_something else SETTLE_SECONDS


def describe(call):
    args = {k: v for k, v in call.args.items() if k != "text"}
    if "text" in call.args:
        args["text"] = (call.args["text"][:60] + "...") if len(call.args["text"]) > 60 else call.args["text"]
    return f"{call.name} {json.dumps(args)}" + (f"  - {call.intent}" if call.intent else "")


def run_task(backend, desktop, task, max_steps, confirm_each):
    print(f"\n>> Task: {task}")
    backend.begin(task, desktop.screenshot())

    started = time.time()
    for step in range(1, max_steps + 1):
        print(f"\n[step {step}] thinking ({backend.model})...")
        t0 = time.time()
        text, calls = with_retries(backend.next_actions)
        print(f"   ({time.time() - t0:.1f}s)")
        if text:
            print(f"   model: {text}")
        if not calls:
            print(f"\n>> Done in {step} step(s), {time.time() - started:.0f}s.")
            return

        results = []
        for call in calls:
            print(f"   action: {describe(call)}")
            acknowledged = False
            if call.needs_confirmation:
                print(f"   !! The model wants confirmation: {call.needs_confirmation}")
                if not ask_yes_no("Allow this action?"):
                    print(">> Stopped: you declined the action.")
                    return
                acknowledged = True
            elif confirm_each and not ask_yes_no("Run it?", default=True):
                print(">> Stopped by you.")
                return

            try:
                output, error = desktop.execute(call.name, call.args), False
            except ActionError as e:
                output, error = str(e), True
                print(f"   error: {e}")
            time.sleep(settle_time(call))
            results.append(ToolResult(call, output, desktop.screenshot(), acknowledged, error))

        backend.add_results(results)

    print(f"\n>> Stopped: reached the {max_steps}-step limit.")


def main():
    ap = argparse.ArgumentParser(description="Computer-use agent for Ubuntu (X11).")
    ap.add_argument("task", nargs="*", help="what to do; omit to be asked interactively")
    ap.add_argument("--backend", choices=BACKENDS, default="gemini")
    ap.add_argument("--model", help="model id (default depends on backend)")
    ap.add_argument("--fallbacks", default=",".join(GEMINI_FALLBACKS),
                    help="gemini: comma-separated models to switch to when the main one "
                         "is overloaded; '' to disable (default: %(default)s)")
    ap.add_argument("--thinking", choices=["minimal", "low", "medium", "high"],
                    help="gemini: thinking level; lower is faster (default: per model)")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--confirm", action="store_true", help="approve every action before it runs")
    args = ap.parse_args()

    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        sys.exit("This needs an X11 session (pyautogui can't control Wayland). "
                 "Log out and pick 'Ubuntu on Xorg'.")

    desktop = Desktop()
    model = args.model or DEFAULT_MODELS[args.backend]
    fallbacks = [m.strip() for m in args.fallbacks.split(",") if m.strip()]
    backend = BACKENDS[args.backend](model, desktop.width, desktop.height,
                                     fallbacks=fallbacks, thinking=args.thinking)

    print(f"Computer-use agent | backend: {args.backend} | model: {model}"
          + (f" (fallbacks: {', '.join(fallbacks)})" if args.backend == "gemini" and fallbacks else "")
          + f" | screen: {desktop.width}x{desktop.height}")
    print("Actions run on your real desktop"
          + (" (you'll approve each one)." if args.confirm else " without asking.")
          + " Abort: Ctrl+C, or move the mouse to the top-left corner.")

    tasks = [" ".join(args.task)] if args.task else None
    while True:
        if tasks is not None:
            if not tasks:
                break
            task = tasks.pop()
        else:
            try:
                task = input("\nWhat should I do? (empty line or 'quit' to exit)\ntask> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if task.lower() in ("", "quit", "exit", "q"):
                break
        try:
            run_task(backend, desktop, task, args.max_steps, args.confirm)
        except KeyboardInterrupt:
            print("\n>> Aborted (Ctrl+C).")
        except desktop.gui.FailSafeException:
            print("\n>> Aborted (mouse moved to a screen corner).")
        except Exception as e:
            print(f"\n>> Task failed: {type(e).__name__}: {str(e)[:500]}")


if __name__ == "__main__":
    main()
