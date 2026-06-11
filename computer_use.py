import openai  # OpenRouter is OpenAI-compatible
import base64
from PIL import ImageGrab  # pip install pillow

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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"
)

def take_screenshot():
    img = ImageGrab.grab()
    img.save("screen.png")
    with open("screen.png", "rb") as f:
        return base64.b64encode(f.read()).decode()

def ask_model(user_goal: str, screenshot_b64: str):
    response = client.chat.completions.create(
        model="qwen/qwen2.5-vl-72b-instruct:free",
        max_tokens=500,
        messages=[
            {
                "role": "system",
                "content": "You are a computer use agent. When given a screenshot and a goal, respond ONLY with a JSON object like: {\"action\": \"click\", \"x\": 450, \"y\": 230} or {\"action\": \"type\", \"text\": \"hello\"} or {\"action\": \"done\", \"message\": \"task complete\"}. No explanation, no markdown, only raw JSON."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                    },
                    {
                        "type": "text",
                        "text": user_goal
                    }
                ]
            }
        ]
    )
    return response.choices[0].message.content

# Try it
screenshot = take_screenshot()
try:
    result = ask_model("Click the Chrome icon to open the browser", screenshot)
    print(result)
    print("Data type of result:", type(result))
    print("Now you would parse the JSON and perform the action on your computer using something like pyautogui. This is just a demo of getting the model's response.")

except openai.APIStatusError as e:
    print(f"API Error: {e.message}")
    print("Check your OpenRouter credits: https://openrouter.ai/settings/credits")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")