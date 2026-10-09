import time

import requests

from agent.config import MAX_RETRIES, RETRYABLE_STATUS


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


def with_retries(fn):
    """Call fn(), retrying overloads / rate limits / network blips with backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except RetryNow:
            continue
        except Exception as e:
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
            time.sleep(delay)
