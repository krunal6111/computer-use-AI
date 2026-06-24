import json
from groq import Groq

client = Groq(api_key="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")
MODEL = "openai/gpt-oss-20b"

# ── 1. Define tools ──────────────────────────────────────────
def calculate(expression: str) -> str:
    try:
        result = eval(expression, {"__builtins__": {}})
        return str(result)
    except Exception as e:
        return f"Error: {e}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a math expression. E.g. '12 * 7 + 3'",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "A math expression"}
                },
                "required": ["expression"]
            }
        }
    }
]

# ── 2. The agent loop ────────────────────────────────────────
def run_agent(user_message: str):
    messages = [{"role": "user", "content": user_message}]
    print(f"\nUser: {user_message}")

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message

        # If no tool call → we have the final answer
        if not msg.tool_calls:
            print(f"Agent: {msg.content}")
            break

        # Otherwise → execute the tool
        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"  [Tool] {func_name}({args})")

            result = calculate(args["expression"])
            print(f"  [Result] {result}")

            # Add the assistant's tool call and the result to history
            messages.append(msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

# ── 3. Try it ────────────────────────────────────────────────
run_agent("What is 847 multiplied by 23, then divided by 7?")

# if __name__ == "__main__":
#     result = calculate("847 * 23 / 7")
#     print(type(result))
#     print(result)

