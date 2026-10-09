"""
computer_agent - real computer use on Ubuntu (X11).

A plain agent loop:  screenshot -> model picks an action -> run it with
pyautogui -> new screenshot -> ... until the model says it's done.

Backends
  gemini  Google AI Studio (GEMINI_API_KEY). Uses Gemini's *native* Computer
          Use tool with ENVIRONMENT_DESKTOP, i.e. the action set the model was
          trained on (click, type, hotkey, scroll, ... in 0-999 coordinates).
  nim     NVIDIA NIM, OpenAI-compatible (NVIDIA_API_KEY). Declares a standard
          `computer` function tool. Works with vision models that do GUI
          grounding in 0-1000 normalized coordinates, e.g. google/gemma-4-31b-it.

Usage
  ./computer_agent.py "Open the Files app and create a folder named test"
  ./computer_agent.py --backend nim "Open Firefox and search for Ubuntu 26.04"
  ./computer_agent.py                  # asks you for tasks one at a time

Safety
  Actions run on your REAL desktop, without asking, unless you pass --confirm.
  To abort: press Ctrl+C in this terminal, or shove the mouse into the
  top-left corner of the screen (pyautogui fail-safe).
"""

import argparse
import os
import sys

from agent.backends import BACKENDS
from agent.config import DEFAULT_MODELS, GEMINI_FALLBACKS
from agent.desktop import Desktop
from agent.orchestrator import run_task


def main():
    ap = argparse.ArgumentParser(description="Computer-use agent for Ubuntu (X11).")
    ap.add_argument("task", nargs="*", help="what to do; omit to be asked interactively")
    ap.add_argument("--backend", choices=BACKENDS, default="gemini")
    ap.add_argument("--model", help="model id (default depends on backend)")
    ap.add_argument("--fallbacks", default=",".join(GEMINI_FALLBACKS),
                    help="gemini: comma-separated models to switch to when the main one "
                         "is overloaded; '' to disable (default: %(default)s)")
    ap.add_argument("--thinking", choices=["minimal", "low", "medium", "high"],
                    help="gemini: thinking level; lower is faster (default: per model)")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--confirm", action="store_true", help="approve every action before it runs")
    args = ap.parse_args()

    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        sys.exit("This needs an X11 session (pyautogui can't control Wayland). "
                 "Log out and pick 'Ubuntu on Xorg'.")

    desktop = Desktop()
    model = args.model or DEFAULT_MODELS[args.backend]
    fallbacks = [m.strip() for m in args.fallbacks.split(",") if m.strip()]
    backend = BACKENDS[args.backend](model, desktop.width, desktop.height,
                                     fallbacks=fallbacks, thinking=args.thinking)

    print(f"Computer-use agent | backend: {args.backend} | model: {model}"
          + (f" (fallbacks: {', '.join(fallbacks)})" if args.backend == "gemini" and fallbacks else "")
          + f" | screen: {desktop.width}x{desktop.height}")
    print("Actions run on your real desktop"
          + (" (you'll approve each one)." if args.confirm else " without asking.")
          + " Abort: Ctrl+C, or move the mouse to the top-left corner.")

    tasks = [" ".join(args.task)] if args.task else None
    while True:
        if tasks is not None:
            if not tasks:
                break
            task = tasks.pop()
        else:
            try:
                task = input("\nWhat should I do? (empty line or 'quit' to exit)\ntask> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if task.lower() in ("", "quit", "exit", "q"):
                break
        try:
            run_task(backend, desktop, task, args.max_steps, args.confirm)
        except KeyboardInterrupt:
            print("\n>> Aborted (Ctrl+C).")
        except desktop.gui.FailSafeException:
            print("\n>> Aborted (mouse moved to a screen corner).")
        except Exception as e:
            print(f"\n>> Task failed: {type(e).__name__}: {str(e)[:500]}")
