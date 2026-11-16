"""Bounded retries for transient Yahoo failures, with actionable errors for callers."""
import time


class YahooUnavailable(ValueError):
    pass


def fetch_yahoo(operation, fetch, valid=lambda value: value is not None):
    for attempt in range(2):
        try:
            result = fetch()
            if valid(result):
                return result
        except Exception:
            # Never surface the library's global-outage claim or provider response bodies.
            pass
        if attempt == 0:
            time.sleep(.25)
    raise YahooUnavailable(
        f"Yahoo Finance {operation} is temporarily unavailable after two attempts. "
        "Retry later; no archived or invented data was substituted."
    )
