import io
import subprocess
import time
import webbrowser

from PIL import Image

from agent.config import SCREENSHOT_WIDTH

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
