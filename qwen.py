import base64
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from typing import Any

load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
print(f"API Key loaded: {'Yes' if api_key else 'No'}")
from PIL import ImageGrab  # pip install pillow

# Computer use tools — model decides which to call and provides x, y, text etc.
tools: list[Any] = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot to see the current state of the screen. Always call this first before acting.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
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
                    "x": {"type": "integer", "description": "X coordinate to scroll at"},
                    "y": {"type": "integer", "description": "Y coordinate to scroll at"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "integer", "description": "Number of scroll steps"}
                },
                "required": ["x", "y", "direction", "amount"]
            }
        }
    }
]

def take_screenshot():
    img = ImageGrab.grab()
    img.save("screen.png")
    with open("screen.png", "rb") as f:
        return base64.b64encode(f.read()).decode()

try:
    client = OpenAI(
        api_key=api_key,
        base_url="https://ws-kn7wswwru4udmh42.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    )

    completion = client.chat.completions.create(
        model="qwen3-vl-235b-a22b-thinking",
        messages=[
            {
                "role": "system",
                "content": "You are a computer use agent. When given a goal, use the available tools to operate the computer. Always take a screenshot first to see the current screen state before acting."
            },
            {
                "role": "user",
                "content": "Take a screenshot and tell me what you see on the screen."
            }
        ],
        tools=tools,
        tool_choice="auto"
    )

    msg = completion.choices[0].message

    # Check if model wants to call a tool
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            func = getattr(tool_call, 'function', None)
            name = func.name if func else tool_call.name
            args = func.arguments if func else "{}"
            print(f"Model called tool: {name}")
            print(f"With args: {args}")
    else:
        print(msg.content)

except Exception as e:
    print(f"Error message: {e}")
    print("See: https://www.alibabacloud.com/help/model-studio/developer-reference/error-code")