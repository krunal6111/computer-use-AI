# Computer-Use AI Agent

A computer-use AI agent for Ubuntu (X11): it takes a screenshot, sends it to an
LLM (Gemini or NVIDIA NIM), and executes whatever mouse/keyboard action the
model picks via `pyautogui` — click, type, scroll, open a URL, etc. It repeats
this screenshot → decide → act loop until the model says the task is done.
    
A small always-on-top HUD window shows live step-by-step progress so you can
watch what it's doing even when it switches focus to another app.

## Setup

**1. System packages** (Ubuntu/Debian — required even after `pip install`):
```bash
sudo apt-get install python3-tk python3-dev scrot xclip tesseract-ocr xdotool
```

**2. Python dependencies:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. API key** — create a `.env` file in the project root with at least one:
```
GEMINI_API_KEY=your_key_here
NVIDIA_API_KEY=your_key_here
```

**4. Requires an X11 session** (not Wayland) — `pyautogui` can't control
Wayland. Log out and choose "Ubuntu on Xorg" at the login screen if needed.

## Usage

```bash
./computer_agent.py "Open Firefox and search for Ubuntu 26.04"
./computer_agent.py --backend nim "some task"   # use NVIDIA NIM instead of Gemini
./computer_agent.py                              # interactive: asks for tasks one at a time
./computer_agent.py --no-hud "some task"         # disable the overlay window
./computer_agent.py --confirm "some task"        # ask before every single action
```

Run `./computer_agent.py --help` for all flags (model selection, fallback
models, thinking level, max steps).

**Safety**: actions run on your real desktop. To abort, press `Ctrl+C` in the
terminal, or move the mouse to the top-left corner of the screen.

## Project layout

- `computer_agent.py` — entry point shim
- `agent/cli.py` — argument parsing, startup
- `agent/orchestrator.py` — the screenshot → decide → act loop
- `agent/desktop.py` — screen capture and pyautogui-driven mouse/keyboard actions
- `agent/backends/` — `gemini.py` and `nim.py`, the two interchangeable LLM backends
- `agent/hud.py` — the always-on-top status overlay
- `agent/prompts.py` — the system prompt sent to the model
- `agent/config.py` — tunable constants (timeouts, retries, thinking level, etc.)
