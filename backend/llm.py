"""The single path to any LLM.

``call(tier, system, user, max_tokens, schema)``:
  * exact-prompt cache (diskcache)
  * token-bucket budgeter for TPM and RPM at 80% of the configured limits;
    each call reserves ``estimated_input + max_tokens`` and awaits refill
  * global concurrency cap (``asyncio.Semaphore``)
  * retries with exponential backoff + jitter on 429/5xx/connection errors,
    honouring ``retry-after``; at most 5 attempts, then ``LLMUnavailable``
  * JSON extraction + Pydantic validation, with exactly one repair call
  * per-run usage accounting (contextvar) with a token ceiling that switches
    the run to reduced mode at 80%
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from backend.cache import get_cache, make_key
from backend.config import settings

log = logging.getLogger(__name__)
Tier = Literal["small", "large"]
T = TypeVar("T", bound=BaseModel)
MAX_ATTEMPTS = 5
SAFETY = 0.8


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Provider unreachable / rate limited after all retries; callers degrade."""


class LLMConfigError(ValueError):
    """Setup problem (unknown provider, missing/invalid key, unknown model).

    Deliberately *not* an ``LLMError``: agents catch ``LLMError`` and degrade,
    but a configuration error must stop the run with a clear message instead
    of producing an empty report."""


class LLMSchemaError(LLMError):
    """Output failed validation twice; callers skip the item and log it."""


class RetryableError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 3.6))


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------
def _clock() -> float:
    return time.monotonic()


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class TokenBucket:
    """Continuous-refill token bucket (``per_minute`` units per 60 s) with a
    60-second sliding-window guard.

    The bucket smooths bursts; the window guarantees that the units admitted
    in any 60-second window never exceed ``per_minute`` (a plain bucket alone
    could admit up to twice its capacity in the first minute). Callers reserve
    an estimate, then ``settle`` with the real usage.
    """

    WINDOW = 60.0

    def __init__(self, per_minute: float) -> None:
        self.capacity = max(1.0, float(per_minute))
        self.rate = self.capacity / self.WINDOW
        self.tokens = self.capacity
        self.updated = _clock()
        self.window: deque[list[float]] = deque()
        self._lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        while self.window and self.window[0][0] <= now - self.WINDOW:
            self.window.popleft()

    def used(self) -> float:
        self._refill(_clock())
        return sum(e[1] for e in self.window)

    async def acquire(self, n: float) -> list[float]:
        """Reserve ``n`` units, awaiting refill as needed. Returns the reservation."""
        n = float(n)
        need = min(n, self.capacity)  # an oversized call waits for a full, empty bucket
        async with self._lock:  # FIFO: one waiter at a time
            while True:
                now = _clock()
                self._refill(now)
                in_window = sum(e[1] for e in self.window)
                ok_bucket = self.tokens >= need
                ok_window = (in_window + n <= self.capacity) or not self.window
                if ok_bucket and ok_window:
                    self.tokens -= need
                    entry = [now, n]
                    self.window.append(entry)
                    return entry
                delay = 0.0
                if not ok_bucket:
                    delay = (need - self.tokens) / self.rate
                if not ok_window:
                    delay = max(delay, self.window[0][0] + self.WINDOW - now)
                await _sleep(max(delay, 0.01))

    def settle(self, entry: list[float], actual: float) -> None:
        """Replace the reserved estimate with the actual usage (refund or extra charge)."""
        delta = entry[1] - float(actual)
        entry[1] = float(actual)
        self._refill(_clock())
        self.tokens = min(self.capacity, self.tokens + delta)


@dataclass
class Budgeter:
    tpm: TokenBucket
    rpm: TokenBucket
    sem: asyncio.Semaphore

    @classmethod
    def from_settings(cls) -> "Budgeter":
        return cls(
            tpm=TokenBucket(settings.tpm_limit * SAFETY),
            rpm=TokenBucket(max(1, settings.rpm_limit * SAFETY)),
            sem=asyncio.Semaphore(max(1, settings.llm_concurrency)),
        )


_budgeters: dict[int, Budgeter] = {}


def budgeter() -> Budgeter:
    """One budgeter per event loop (tests create several loops)."""
    loop = asyncio.get_running_loop()
    b = _budgeters.get(id(loop))
    if b is None:
        b = _budgeters[id(loop)] = Budgeter.from_settings()
    return b


def reset_budgeter() -> None:
    _budgeters.clear()


# --------------------------------------------------------------------------
# usage accounting
# --------------------------------------------------------------------------
@dataclass
class RunUsage:
    ceiling: int = field(default_factory=lambda: settings.run_token_ceiling)
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    cache_hits: int = 0
    web_searches: int = 0
    failures: list[str] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def reduced_mode(self) -> bool:
        return self.total >= SAFETY * self.ceiling

    @property
    def exhausted(self) -> bool:
        return self.total >= self.ceiling


_usage: contextvars.ContextVar[RunUsage | None] = contextvars.ContextVar("run_usage", default=None)


def current_usage() -> RunUsage | None:
    return _usage.get()


def set_usage(u: RunUsage | None) -> contextvars.Token:
    return _usage.set(u)


def reset_usage(token: contextvars.Token) -> None:
    _usage.reset(token)


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------
@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


Provider = Callable[[str, str, str, int, float], Awaitable[Completion]]
_provider_override: Provider | None = None


def set_provider(fn: Provider | None) -> None:
    """Install a custom provider (tests, local stubs). ``None`` restores the env default."""
    global _provider_override
    _provider_override = fn


_anthropic_client = None


async def _anthropic(model: str, system: str, user: str, max_tokens: int, temperature: float) -> Completion:
    global _anthropic_client
    import anthropic

    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None, max_retries=0)
    try:
        resp = await _anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            # Static system prompt first, marked for provider prompt caching.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.RateLimitError as e:
        raise RetryableError("rate limited", _retry_after(getattr(e, "response", None))) from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500 or e.status_code in (408, 409, 429, 529):
            raise RetryableError(f"status {e.status_code}", _retry_after(e.response)) from e
        if e.status_code in (401, 403, 404):
            raise LLMConfigError(f"Anthropic rejected the request (HTTP {e.status_code}): {e.message}") from e
        raise LLMError(f"anthropic error {e.status_code}: {e.message}") from e
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        raise RetryableError("connection error") from e
    text = "".join(getattr(b, "text", "") for b in resp.content)
    u = resp.usage
    tin = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    return Completion(text=text, tokens_in=tin, tokens_out=u.output_tokens or 0)


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_RETRY_AFTER = 120.0  # longer waits (e.g. a daily quota) fail fast instead of hanging the run


def _is_groq() -> bool:
    return settings.llm_provider == "groq" or "api.groq.com" in settings.openai_base_url


def _compat_base_url() -> str:
    if settings.llm_provider == "groq" and "api.openai.com" in settings.openai_base_url:
        return GROQ_BASE_URL
    return settings.openai_base_url.rstrip("/")


def _compat_key() -> str:
    if _is_groq():
        return settings.groq_api_key or settings.openai_api_key
    return settings.openai_api_key


def _is_reasoning_model(model: str) -> bool:
    return "gpt-oss" in model


async def _openai_compatible(model: str, system: str, user: str, max_tokens: int, temperature: float) -> Completion:
    import httpx

    key = _compat_key()
    if not key:
        raise LLMConfigError(
            "No API key set. Put your key in .env as GROQ_API_KEY (or OPENAI_API_KEY) and restart the backend."
        )
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if _is_reasoning_model(model):
        # gpt-oss thinks before answering; keep that short so it does not eat
        # the output budget, and do not return the reasoning text.
        body["reasoning_effort"] = settings.reasoning_effort
        if _is_groq():
            body["include_reasoning"] = False
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{_compat_base_url()}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise RetryableError(f"connection error: {e}") from e
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(f"status {r.status_code}: {r.text[:200]}", _retry_after(r))
    if r.status_code in (401, 403):
        raise LLMConfigError(f"The model provider rejected the API key (HTTP {r.status_code}). Check the key in .env.")
    if r.status_code == 404 or (r.status_code == 400 and "model_not_found" in r.text):
        raise LLMConfigError(f"Model '{model}' was not found at the provider. Check SMALL_MODEL / LARGE_MODEL in .env.")
    if r.status_code >= 400:
        err = _error_body(r)
        failed = err.get("failed_generation")
        if failed is not None or err.get("code") == "json_validate_failed":
            # JSON mode rejected the output: hand it back so the repair step can fix it.
            return Completion(text=str(failed or ""), tokens_in=0, tokens_out=0)
        raise LLMError(f"provider error {r.status_code}: {r.text[:300]}")
    data = r.json()
    u = data.get("usage") or {}
    return Completion(
        text=data["choices"][0]["message"].get("content") or "",
        tokens_in=u.get("prompt_tokens", 0),
        tokens_out=u.get("completion_tokens", 0),
    )


def _error_body(r: Any) -> dict:
    try:
        err = r.json().get("error") or {}
        return err if isinstance(err, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _retry_after(response: Any) -> float | None:
    try:
        v = response.headers.get("retry-after")
        return float(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def _provider() -> Provider:
    if _provider_override is not None:
        return _provider_override
    if settings.llm_provider == "anthropic":
        return _anthropic
    if settings.llm_provider in {"openai", "openai_compatible", "groq"}:
        return _openai_compatible
    raise LLMConfigError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r} in .env. Use 'groq', 'openai' or 'anthropic'."
    )


def check_config() -> None:
    """Fail fast (before any web search or indexing) on an obviously broken setup."""
    if _provider_override is not None:
        return
    provider = _provider()
    if provider is _anthropic and not settings.anthropic_api_key:
        raise LLMConfigError("ANTHROPIC_API_KEY is empty in .env (or set LLM_PROVIDER=groq with GROQ_API_KEY).")
    if provider is _openai_compatible and not _compat_key():
        raise LLMConfigError("No API key set. Put your key in .env as GROQ_API_KEY (or OPENAI_API_KEY) and restart the backend.")


def model_for(tier: Tier) -> str:
    return settings.large_model if tier == "large" else settings.small_model


# --------------------------------------------------------------------------
# JSON handling
# --------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    s = text.strip()
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # first balanced {...} or [...]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        while start >= 0:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(s)):
                ch = s[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = s.find(open_ch, start + 1)
    raise ValueError("no JSON object found in model output")


def _validate(schema: type[T] | None, raw: str) -> T | Any:
    data = extract_json(raw)
    if schema is None:
        return data
    if isinstance(data, list):
        # tolerate a bare list when the schema has exactly one list field
        fields = list(schema.model_fields)
        if len(fields) == 1:
            data = {fields[0]: data}
    return schema.model_validate(data)


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------
async def _raw_call(tier: Tier, system: str, user: str, max_tokens: int, temperature: float, label: str) -> Completion:
    usage = current_usage()
    if usage and usage.exhausted:
        raise LLMUnavailable("run token ceiling reached")
    b = budgeter()
    est = estimate_tokens(system) + estimate_tokens(user) + max_tokens
    provider = _provider()
    model = model_for(tier)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Take the concurrency slot first so the budget is reserved at the
        # moment the request is actually sent (not while queued for a slot).
        await b.sem.acquire()
        reservation: list[float] | None = None
        try:
            await b.rpm.acquire(1)
            reservation = await b.tpm.acquire(est)
            comp = await provider(model, system, user, max_tokens, temperature)
        except RetryableError as e:
            b.sem.release()
            if reservation is not None:
                b.tpm.settle(reservation, 0)  # rejected calls consume nothing
            if attempt == MAX_ATTEMPTS:
                raise LLMUnavailable(f"{label}: {e}") from e
            if e.retry_after is not None and e.retry_after > MAX_RETRY_AFTER:
                raise LLMUnavailable(
                    f"{label}: rate limit needs a {e.retry_after:.0f}s wait (daily quota likely used up)"
                ) from e
            delay = e.retry_after if e.retry_after is not None else min(30.0, 1.5 * 2 ** (attempt - 1))
            delay += random.uniform(0, 0.5 * delay + 0.25)
            log.warning("LLM %s retry %d in %.1fs (%s)", label, attempt, delay, e)
            await _sleep(delay)
            continue
        except BaseException:
            b.sem.release()
            if reservation is not None:
                b.tpm.settle(reservation, est)
            raise
        b.sem.release()
        actual = comp.tokens_in + comp.tokens_out if (comp.tokens_in or comp.tokens_out) else est
        b.tpm.settle(reservation, actual)
        if usage:
            usage.tokens_in += comp.tokens_in or estimate_tokens(system + user)
            usage.tokens_out += comp.tokens_out or estimate_tokens(comp.text)
            usage.calls += 1
            usage.log.append({"label": label, "tier": tier, "in": comp.tokens_in, "out": comp.tokens_out})
        return comp
    raise LLMUnavailable(label)  # pragma: no cover


async def call(
    tier: Tier,
    system: str,
    user: str,
    max_tokens: int,
    schema: type[T] | None = None,
    temperature: float = 0.0,
    label: str = "llm",
    use_cache: bool | None = None,
) -> T:
    """Run one LLM call through the budgeter and return the validated object."""
    use_cache = settings.llm_cache if use_cache is None else use_cache
    cache = get_cache("llm") if use_cache else None
    key = make_key(settings.llm_provider, model_for(tier), system, user, max_tokens, temperature, schema.__name__ if schema else None)
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            try:
                out = _validate(schema, cached)
                u = current_usage()
                if u:
                    u.cache_hits += 1
                return out
            except (ValueError, ValidationError):
                pass

    comp = await _raw_call(tier, system, user, max_tokens, temperature, label)
    try:
        out = _validate(schema, comp.text)
        if cache is not None:
            cache.set(key, comp.text)
        return out
    except (ValueError, ValidationError) as err:
        repair_user = (
            f"{user}\n\nYOUR PREVIOUS OUTPUT WAS INVALID: {str(err)[:600]}\n"
            f"PREVIOUS OUTPUT (truncated): {comp.text[:1500]}\n"
            "Return only corrected JSON that matches the schema."
        )
        comp2 = await _raw_call(tier, system, repair_user, max_tokens, temperature, f"{label}:repair")
        try:
            out = _validate(schema, comp2.text)
        except (ValueError, ValidationError) as err2:
            u = current_usage()
            if u:
                u.failures.append(f"{label}: schema failure after repair: {str(err2)[:200]}")
            raise LLMSchemaError(f"{label}: {err2}") from err2
        if cache is not None:
            cache.set(key, comp2.text)
        return out
