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
            model="qwen3-vl-235b-a22b-thinking",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
    
    messages = [
        {"role": "system", "content": "You are a computer use agent. When given a goal, use the available tools to operate the computer. Always take a screenshot first to see the current screen state before acting."},
        {"role": "user", "content": "Take a screenshot and tell me what you see on the screen." }
    ]
    
    while True:
        response = call_model(messages)
        msg = response.choices[0].message

        if not msg.tool_calls:
            print("Agent Exiting.", msg.content)
            break

        # Check if model wants to call a tool
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                func = getattr(tool_call, 'function', None)
                name = func.name if func else tool_call.name
                args = func.arguments if func else "{}"
                print(f"Model decided to call tool: {name}")
                print(f"With args: {args}")
                
                result = TOOL_REGISTRY[name](**json.loads(args))
                messages.append(tool_result(tool_call.id, result))  # append result
        else:
            print(msg.content)

except Exception as e:
    print(f"Error message: {e}")
    print("See: https://www.alibabacloud.com/help/model-studio/developer-reference/error-code")