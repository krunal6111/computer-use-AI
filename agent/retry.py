import time
import traceback
from datetime import datetime

import requests

from agent.config import ERROR_LOG, MAX_RETRIES, RETRYABLE_STATUS


class RetryNow(Exception):
    """Raised by a backend to ask for an immediate retry (e.g. after switching model)."""


def _status(e):
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code
    return getattr(getattr(e, "response", None), "status_code", None)


def _is_network_error(e):
    import httpx  # used by google-genai

    return isinstance(e, (requests.Timeout, requests.ConnectionError,
                          httpx.TimeoutException, httpx.NetworkError))


def _detail(e):
    """The server's own error message: requests keeps it on the response,
    google-genai already puts it in str(e)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return e.response.text
    return str(e)


def _log_error(e, attempt, seconds):
    resp = getattr(e, "response", None)
    headers = dict(getattr(resp, "headers", None) or {})
    with open(ERROR_LOG, "a") as f:
        f.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} "
                f"attempt {attempt}/{MAX_RETRIES}, status {_status(e)}, {seconds:.1f}s\n")
        if headers:
            f.write(f"response headers: {headers}\n")
        f.write(f"response body: {_detail(e)}\n")
        f.write("".join(traceback.format_exception(e)))


def with_retries(fn):
    """Call fn(), retrying overloads / rate limits / network blips with backoff.
    Every failure is appended in full (body + traceback) to ERROR_LOG."""
    for attempt in range(1, MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            return fn()
        except RetryNow:
            continue
        except Exception as e:
            _log_error(e, attempt, time.monotonic() - started)
            status = _status(e)
            daily_quota = status == 429 and "PerDay" in str(e)
            retryable = status in RETRYABLE_STATUS or _is_network_error(e)
            if attempt == MAX_RETRIES or daily_quota or not retryable:
                raise
            reason = {429: "Rate limited", 503: "Model overloaded"}.get(
                status, "Timed out" if _is_network_error(e) else "Temporary error")
            delay = min(2 ** (attempt - 1), 15)
            print(f"   ... {reason} ({status or type(e).__name__}), retrying in {delay}s "
                  f"[{attempt}/{MAX_RETRIES - 1}]")
            print(f"       {' '.join(_detail(e).split())[:200]}  (full details: logs/errors.log)")
            time.sleep(delay)
