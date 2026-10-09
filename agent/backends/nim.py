import base64
import json
import os
import sys

import requests

from agent.config import KEEP_SCREENSHOTS, NIM_URL, REQUEST_TIMEOUT
from agent.prompts import NIM_EXTRA_PROMPT, SYSTEM_PROMPT
from agent.tool_types import ToolCall

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
