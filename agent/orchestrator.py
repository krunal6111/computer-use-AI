import contextlib
import json
import time

from agent.config import SETTLE_SECONDS, SLOW_SETTLE_SECONDS
from agent.desktop import ActionError
from agent.retry import with_retries
from agent.tool_types import ToolResult


def _screenshot(desktop, hud):
    """Take a screenshot the model will see, hiding the HUD first so it
    never appears in what gets sent to the backend."""
    ctx = hud.hide_for_capture() if hud else contextlib.nullcontext()
    with ctx:
        return desktop.screenshot()


def ask_yes_no(question, default=False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"   ?? {question} {hint} ").strip().lower()
    except EOFError:
        return False
    return default if not answer else answer in ("y", "yes")


def settle_time(call):
    """How long to wait after an action before taking the next screenshot."""
    a = call.args
    loads_something = (
        call.name in ("navigate", "open_url")
        or a.get("press_enter")
        or str(a.get("key") or a.get("text") or "").lower() in ("enter", "return", "super", "win")
    )
    return SLOW_SETTLE_SECONDS if loads_something else SETTLE_SECONDS


def describe(call):
    args = {k: v for k, v in call.args.items() if k != "text"}
    if "text" in call.args:
        args["text"] = (call.args["text"][:60] + "...") if len(call.args["text"]) > 60 else call.args["text"]
    return f"{call.name} {json.dumps(args)}" + (f"  - {call.intent}" if call.intent else "")


def run_task(backend, desktop, task, max_steps, confirm_each, hud=None):
    print(f"\n>> Task: {task}")
    if hud:
        hud.post(f"Task: {task}", "info")
        hud.finish_last("info")
    backend.begin(task, _screenshot(desktop, hud))

    started = time.time()
    for step in range(1, max_steps + 1):
        print(f"\n[step {step}] thinking ({backend.model})...")
        if hud:
            hud.post(f"Step {step}: thinking...")
        t0 = time.time()
        text, calls = with_retries(backend.next_actions)
        print(f"   ({time.time() - t0:.1f}s)")
        if text:
            print(f"   model: {text}")
        if not calls:
            print(f"\n>> Done in {step} step(s), {time.time() - started:.0f}s.")
            if hud:
                hud.finish_last("done")
                hud.post(text or f"Done in {step} step(s)", "done")
                hud.finish_last("done")
            return
        if hud:
            hud.finish_last("done")

        results = []
        for call in calls:
            desc = describe(call)
            print(f"   action: {desc}")
            if hud:
                hud.post(desc, "action")
            acknowledged = False
            if call.needs_confirmation:
                print(f"   !! The model wants confirmation: {call.needs_confirmation}")
                if not ask_yes_no("Allow this action?"):
                    print(">> Stopped: you declined the action.")
                    if hud:
                        hud.finish_last("error")
                        hud.post("Stopped: you declined the action", "error")
                        hud.finish_last("error")
                    return
                acknowledged = True
            elif confirm_each and not ask_yes_no("Run it?", default=True):
                print(">> Stopped by you.")
                if hud:
                    hud.finish_last("error")
                    hud.post("Stopped by you", "error")
                    hud.finish_last("error")
                return

            try:
                output, error = desktop.execute(call.name, call.args), False
            except ActionError as e:
                output, error = str(e), True
                print(f"   error: {e}")
            time.sleep(settle_time(call))
            results.append(ToolResult(call, output, _screenshot(desktop, hud), acknowledged, error))
            if hud:
                hud.finish_last("error" if error else "done")

        backend.add_results(results)

    print(f"\n>> Stopped: reached the {max_steps}-step limit.")
    if hud:
        hud.post(f"Stopped: reached the {max_steps}-step limit", "error")
        hud.finish_last("error")
