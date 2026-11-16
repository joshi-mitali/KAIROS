"""Rotate configured Groq keys on 429; respect per-key cooldowns, never retry forever."""
import os
import random
import threading
import time
from functools import lru_cache
from types import SimpleNamespace


SHORT_RETRY_MAX_S = 6.0  # a 429 whose Retry-After is at most this long gets exactly one jittered retry


class GroqCooldownError(RuntimeError):
    status_code = 429
    retry_after = None  # seconds until the soonest key is usable again


class GroqKeyPool:
    def __init__(self, keys):
        self.keys = list(dict.fromkeys(key.strip() for key in keys if key.strip()))
        self.cooldowns = {}
        self.index = 0
        self.lock = threading.Lock()

    def current(self):
        with self.lock:
            for offset in range(len(self.keys)):
                index = (self.index + offset) % len(self.keys)
                key = self.keys[index]
                if self.cooldowns.get(key, 0) <= time.monotonic():
                    self.index = index
                    return key
            if not self.keys:
                raise ValueError("No Groq API key is configured.")
            delay = max(1, min(self.cooldowns.values()) - time.monotonic())
            err = GroqCooldownError(f"All configured Groq keys are cooling down; retry after {delay:.0f}s.")
            err.retry_after = delay
            raise err

    def rate_limited(self, key, error):
        response = getattr(error, "response", None)
        try:
            delay = max(1, float(response.headers.get("retry-after", "60"))) if response else 60
        except (TypeError,ValueError):
            delay = 60
        with self.lock:
            self.cooldowns[key] = time.monotonic() + delay
        return delay


@lru_cache
def get_key_pool():
    return GroqKeyPool([os.environ.get("GROQ_API_KEY", ""), *os.environ.get("GROQ_API_KEYS", "").split(",")])


class GroqPoolClient:
    def __init__(self):
        self.clients = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        """One jittered retry on a short 429, independent of GROQ_MAX_RETRIES (which the local launcher sets to 0)."""
        try:
            return self._create(**kwargs)
        except GroqCooldownError as exc:
            if exc.retry_after is None or exc.retry_after > SHORT_RETRY_MAX_S:
                raise
            time.sleep(exc.retry_after + random.uniform(0, 0.5))
            return self._create(**kwargs)

    def _create(self, **kwargs):
        pool = get_key_pool()
        delays = []
        for _ in range(len(pool.keys)):
            key = pool.current()
            if key not in self.clients:
                if os.environ.get("KAIROS_LANGFUSE_ENABLED", "false").lower() in ("true", "1"):
                    from kairos.observability.langfuse_tracing import get_langfuse
                    get_langfuse()
                    from langfuse.openai import OpenAI
                else:
                    from openai import OpenAI
                self.clients[key] = OpenAI(api_key=key, base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), timeout=float(os.environ.get("GROQ_TIMEOUT_SEC", "45")), max_retries=0)
            try:
                return self.clients[key].chat.completions.create(**kwargs)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 429:
                    raise
                delays.append(pool.rate_limited(key, exc))
        err = GroqCooldownError("Groq key pool exhausted; retry after the provider cooldown. Account-wide limits may affect every key.")
        err.retry_after = min(delays, default=None)
        raise err
