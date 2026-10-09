"""
Open Interpreter OS-mode profile, tuned for Google Gemini (AI Studio).

Runs the built-in os.py profile as-is (same `interpreter` singleton, no
separate import), then:
  1. Patches the LLM retry loop so a 503 "model overloaded" error is retried
     with real exponential backoff instead of retrying 4x near-instantly and
     then crashing with a traceback.
  2. Prints friendlier status lines: what's happening on a retry, and a
     clear "ready" banner before the `>` prompt.

Loaded via: interpreter --profile /path/to/os_gemini_profile.py --model gemini/...
(run_os.sh already does this.) `interpreter` is injected into this script's
scope by Open Interpreter's own profile loader, same as any .py profile.
"""

import os as _os
import time

import litellm
from interpreter.core.llm import llm as _llm_module

# --- 1. Run the stock os.py profile source in this same scope, so it acts
#         on the one `interpreter` instance already injected here. ---
_os_profile_path = _os.path.join(
    _os.path.dirname(_llm_module.__file__), "..", "..",
    "terminal_interface", "profiles", "defaults", "os.py",
)
_os_profile_path = _os.path.normpath(_os_profile_path)
with open(_os_profile_path, "r", encoding="utf-8") as _f:
    _os_profile_source = _f.read()
# Drop the `from interpreter import interpreter` line: `interpreter` is
# already provided in this scope, and re-importing it is harmless anyway,
# but skip it for clarity / to match how the framework loads .py profiles.
_os_profile_source = _os_profile_source.replace(
    "from interpreter import interpreter", ""
)
exec(_os_profile_source, globals(), globals())

# --- 2. Patch the completion-retry loop with backoff + friendlier output. ---

# Errors worth waiting and retrying (Google/Vertex overload, rate limits,
# transient connection issues). Anything else (bad API key, invalid model,
# etc) should still fail fast and show the real error.
_RETRYABLE_EXCEPTIONS = (
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    litellm.exceptions.APIConnectionError,
)

_MAX_RETRIES = 6
_BASE_DELAY = 2  # seconds; doubles each attempt, capped below
_MAX_DELAY = 30


def _friendly_retry_message(e, attempt, delay):
    reason = "the model is currently overloaded"
    if isinstance(e, litellm.exceptions.RateLimitError):
        reason = "you've hit a rate limit"
    elif isinstance(e, litellm.exceptions.Timeout):
        reason = "the request timed out"
    elif isinstance(e, litellm.exceptions.APIConnectionError):
        reason = "there was a connection problem"
    print(
        f"\n> {reason.capitalize()} (attempt {attempt}/{_MAX_RETRIES}). "
        f"Retrying in {delay}s...\n"
    )


def _patched_fixed_litellm_completions(**params):
    if "local" in params.get("model"):
        params["stop"] = ["<|assistant|>", "<|end|>", "<|eot_id|>"]

    if params.get("model") == "i" and "conversation_id" in params:
        litellm.drop_params = False
    else:
        litellm.drop_params = True

    params["model"] = params["model"].replace(":latest", "")
    params["num_retries"] = 0

    first_error = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            yield from litellm.completion(**params)
            return
        except KeyboardInterrupt:
            print("Exiting...")
            raise SystemExit(0)
        except Exception as e:
            if first_error is None:
                first_error = e

            if (
                isinstance(e, litellm.exceptions.AuthenticationError)
                and "api_key" not in params
            ):
                print(
                    "LiteLLM requires an API key. Trying again with a dummy "
                    "API key. In the future, if this fixes it, please set a "
                    "dummy API key to prevent this message. "
                    "(e.g `interpreter --api_key x` or `self.api_key = 'x'`)"
                )
                params["api_key"] = "x"
                continue

            if (
                isinstance(e, _RETRYABLE_EXCEPTIONS)
                or "503" in str(e)
                or "UNAVAILABLE" in str(e)
            ):
                if attempt >= _MAX_RETRIES:
                    break
                delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                _friendly_retry_message(e, attempt, delay)
                time.sleep(delay)
                continue

            # Not a retryable error (bad model name, bad key format, etc):
            # fail immediately rather than burning through retries.
            raise

    if first_error is not None:
        print(
            f"\n> Gave up after {_MAX_RETRIES} attempts — the model is still "
            "unavailable. Try again in a minute, or switch models with "
            "`MODEL=gemini/<other-model> ./run_os.sh`.\n"
        )
        raise first_error


_llm_module.fixed_litellm_completions = _patched_fixed_litellm_completions
# `Llm.__init__` already bound `self.completions = fixed_litellm_completions`
# by value (not a dynamic lookup), so the module-level patch above alone
# would not affect this already-constructed interpreter.llm instance.
# Rebind the instance attribute directly too:
interpreter.llm.completions = _patched_fixed_litellm_completions

print(
    "\n> Ready. Type an instruction below and press Enter "
    "(Ctrl+C to stop early).\n"
)
