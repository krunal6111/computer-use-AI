import base64
import json
import pyautogui
from PIL import ImageGrab
from typing import Any


# ── Tool implementations ──────────────────────────────────────────────────────

def screenshot() -> dict:
    """Takes a screenshot and returns it as a base64-encoded image dict.
    Returns a dict instead of a plain string because the model needs the
    image passed back as an image_url content block, not plain text."""
    img = ImageGrab.grab()
    img.save("screen.png")
    with open("screen.png", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"type": "image", "data": b64}


def left_click(x: int, y: int) -> dict:
    """Clicks at the given screen coordinates."""
    pyautogui.click(x, y)
    return {"status": "success", "action": "left_click", "x": x, "y": y}


def type_text(text: str) -> dict:
    """Types the given text using the keyboard."""
    pyautogui.typewrite(text, interval=0.05)
    return {"status": "success", "action": "type_text", "text": text}


def key(key: str) -> dict:
    """Presses a keyboard key e.g. 'Return', 'ctrl+c', 'Escape'."""
    pyautogui.hotkey(*key.split("+"))
    return {"status": "success", "action": "key", "key": key}


def scroll(direction: str, amount: int, x: int | None = None, y: int | None = None) -> dict:
    """Scrolls at the given coordinates in the given direction."""
    scroll_map = {"up": amount, "down": -amount}
    x_scroll_map = {"left": -amount, "right": amount}
    if direction in scroll_map:
        pyautogui.scroll(scroll_map[direction], x=x, y=y)
    elif direction in x_scroll_map:
        pyautogui.hscroll(x_scroll_map[direction], x=x, y=y)
    return {"status": "success", "action": "scroll", "direction": direction, "amount": amount}


# ── Tool registry: name → function (dispatcher) ───────────────────────────────

TOOL_REGISTRY = {
    "screenshot": screenshot,
    "left_click": left_click,
    "type_text":  type_text,
    "key":        key,
    "scroll":     scroll,
}


# ── Tool schemas: sent to the model so it knows what tools exist ──────────────

TOOLS: list[Any] = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot to see the current state of the screen. Always call this first before acting.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "left_click",
            "description": "Click at a specific position on the screen",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate in pixels"},
                    "y": {"type": "integer", "description": "Y coordinate in pixels"}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text using the keyboard",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "key",
            "description": "Press a keyboard key e.g. 'Return', 'ctrl+c', 'Escape'",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name to press"}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the screen in a direction",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount":   {"type": "integer", "description": "Number of scroll steps"},
                    "x":        {"type": ["integer", "null"], "description": "Optional X coordinate to scroll at. If omitted, uses the current mouse position"},
                    "y":        {"type": ["integer", "null"], "description": "Optional Y coordinate to scroll at. If omitted, uses the current mouse position"}
                },
                "required": ["direction", "amount"]
            }
        }
    }
]


# ── tool_result helper: formats tool output for the messages list ─────────────

def tool_result(tool_call_id: str, result: dict) -> dict:
    """Formats a tool execution result to append to messages.
    Screenshot results are sent back as image_url blocks so the model can see them.
    All other results are sent as plain JSON text."""
    if result.get("type") == "image":
        # Alibaba's API does not support image_url inside a tool role message.
        # So we return two messages:
        # 1. A plain text tool result (keeps conversation structure valid)
        # 2. A user message with the actual image (so the model can see it)
        return [
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": "Screenshot taken successfully."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{result['data']}"}
                    },
                    {
                        "type": "text",
                        "text": "Here is the current screenshot. Use it to decide the next action."
                    }
                ]
            }
        ]
    return [
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(result)
        }
    ]

# if __name__ == "__main__":
    # Test the tools
    # print("Testing screenshot tool...")
    # result = screenshot()
    # print("Screenshot result:", result)
    
    # print("Testing left_click tool...")
    # result = left_click(100, 100)
    # print("Left click result:", result)
    
    # print("Testing type_text tool...")
    # result = type_text("Hello, world!")
    # print("Type text result:", result)
    
    # print("Testing key tool...")
    # result = key("ctrl+c")
    # print("Key press result:", result)
    
    # print("Testing scroll tool...")
    # result = scroll(None, None, "up", 400)
    # print("Scroll result:", result)

