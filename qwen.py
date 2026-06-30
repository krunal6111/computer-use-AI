import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from computer_tools import TOOLS, TOOL_REGISTRY, tool_result

load_dotenv(override=True)  # Load environment variables from .env file
api_key = os.getenv("DASHSCOPE_API_KEY")
print(f"API Key loaded: {'Yes' if api_key else 'No'}")
try:
    client = OpenAI(
        api_key=api_key,
        base_url="https://ws-kn7wswwru4udmh42.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    )
    def call_model(messages):
        return client.chat.completions.create(
            model="qwen3-vl-235b-a22b-instruct",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
    
    user_content = input("What do you want to do?: ")
    messages = [
        {"role": "system", "content": "You are a computer use agent. When given a goal, use the available tools to operate the computer. Always take a screenshot first to see the current screen state before acting."},
        {"role": "user", "content": user_content }
    ]
    
    while True:

        response = call_model(messages)
        msg = response.choices[0].message

        if not msg.tool_calls:
            print("Agent Exiting.", msg.content)
            break

        # Check if model wants to call a tool
        if msg.tool_calls:
            messages.append(msg)  # append assistant's tool call decision first
            # Process only the FIRST tool call per loop iteration.
            # This forces the model to re-evaluate after seeing the screenshot
            # result before deciding the next action — prevents blind batched execution.
            tool_call = msg.tool_calls[0]
            func = getattr(tool_call, 'function', None)
            name = func.name if func else tool_call.name
            args = func.arguments if func else "{}"
            print(f"Model decided to call tool: {name}")
            print(f"With args: {args}")

            parsed_args = json.loads(args)

            # Guard: model sometimes packs both x,y into x as a list e.g. {"x": [306, 969]}
            # Unpack it automatically so left_click(x, y) gets correct values
            if name == "left_click" and isinstance(parsed_args.get("x"), list):
                coords = parsed_args["x"]
                parsed_args["x"] = coords[0]
                parsed_args["y"] = coords[1]
                print(f"[Fixed malformed args] Unpacked x list → x={parsed_args['x']}, y={parsed_args['y']}")

            result = TOOL_REGISTRY[name](**parsed_args)
            messages.extend(tool_result(tool_call.id, result))

            # Force a screenshot after every non-screenshot tool call
            # so the model always sees the current screen state before deciding next action.
            # We don't leave this to the model's discretion — it will skip it to save steps.
            # Note: we bypass tool_result() here because this screenshot has no matching
            # tool_call_id — we inject it directly as a user message with the image.
            if name != "screenshot":
                auto_shot = TOOL_REGISTRY["screenshot"]()
                print(f"[Debug] Auto-screenshot taken, base64 length: {len(auto_shot['data'])}")
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{auto_shot['data']}"}
                        },
                        {
                            "type": "text",
                            "text": f"Screenshot taken after executing '{name}'. STOP and carefully examine this screenshot. Did the action succeed? Is the screen in the expected state? If not, adjust your plan accordingly. Do NOT continue with your original plan blindly."
                        }
                    ]
                })
                print(f"[Debug] Messages count after auto-screenshot: {len(messages)}")
                print(f"[Debug] Last message role: {messages[-1]['role']}")
        else:
            print(msg.content)

except Exception as e:
    print(f"Error message: {e}")
    print("See: https://www.alibabacloud.com/help/model-studio/developer-reference/error-code")