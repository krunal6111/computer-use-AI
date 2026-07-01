import os
import json
from qwen_agent.agents import Assistant
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("DASHSCOPE_API_KEY")

llm_cfg = {
    'model': 'qwen3-vl-235b-a22b-instruct',
    'model_type': 'qwenvl_oai',
    'model_server': 'https://ws-kn7wswwru4udmh42.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1',
    'api_key': api_key,
    'generate_cfg': {
        'use_raw_api': True,
    }
}

tools = [{
    "mcpServers": {
        "open-computer-use": {
            "command": "open-computer-use",
            "args": ["mcp"]
        }
    }
}]

bot = Assistant(
    llm=llm_cfg,
    system_message="You are a computer use agent. Use the available tools to operate the computer. Only perform the task the user explicitly asks for. Do not do anything extra beyond the stated goal.",
    function_list=tools
)

step = 0

def log_step(response):
    """Prints each message in the response list clearly so you can track every tool call and result."""
    global step
    for msg in response:
        role = msg.get('role', 'unknown')

        if role == 'assistant':
            # Extract tool calls if present
            content = msg.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        step += 1
                        print(f"\n[Step {step}] Tool call: {block.get('name')}")
                        print(f"          Args: {json.dumps(block.get('input', {}), indent=10)}")
            elif isinstance(content, str) and content.strip():
                print(f"\n[Assistant] {content.strip()}")

        elif role == 'tool':
            content = msg.get('content', '')
            # Don't print raw screenshot base64 — just confirm it was received
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'image_url':
                        print(f"          ↳ Result: [screenshot received]")
                    elif isinstance(block, dict) and block.get('type') == 'text':
                        print(f"          ↳ Result: {block.get('text', '')}")
            elif isinstance(content, str):
                print(f"          ↳ Result: {content}")

        elif role == 'user':
            # Skip — these are just screenshot injections, not useful to log
            pass

user_goal = input("What do you want to do?: ")
messages = [{'role': 'user', 'content': user_goal}]

print("\nAgent running... Press Ctrl+C to stop at any time.\n")

try:
    for response in bot.run(messages):
        log_step(response)
except KeyboardInterrupt:
    print("\n[Stopped by user]")