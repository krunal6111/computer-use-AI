import os
import subprocess
import webbrowser
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import pyautogui  # Install via: pip install pyautogui

load_dotenv()  # reads .env into os.environ (GEMINI_API_KEY, etc.)

app = Flask(__name__)

@app.route('/execute', methods=['POST'])
def execute_command():
    data = request.json
    action = data.get("action")
    target = data.get("target", "")

    try:
        if action == "open_website":
            # Opens a URL in your default browser
            webbrowser.open(target)
            return jsonify({"status": "success", "message": f"Opened {target}"})
            
        elif action == "press_keys":
            # Types out text on your keyboard
            pyautogui.write(target, interval=0.1)
            pyautogui.press('enter')
            return jsonify({"status": "success", "message": f"Typed: {target}"})
            
        elif action == "open_application":
            # Opens a local system application
            subprocess.Popen(target)
            return jsonify({"status": "success", "message": f"Launched {target}"})
            
        else:
            return jsonify({"status": "failed", "message": "Unknown action"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(port=5000)
