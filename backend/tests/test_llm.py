import asyncio
import json

import pytest
from pydantic import BaseModel

from backend import llm
from backend.llm import Completion, RetryableError


class Out(BaseModel):
    value: int


def test_extract_json_variants():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('Sure! {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    with pytest.raises(ValueError):
        llm.extract_json("no json here")


async def test_schema_repair_makes_exactly_one_extra_call():
    calls = []

    async def provider(model, system, user, max_tokens, temperature):
        calls.append(user)
        return Completion(text='{"value": "x"}' if len(calls) == 1 else '{"value": 3}', tokens_in=10, tokens_out=5)

    llm.set_provider(provider)
    out = await llm.call("small", "sys", "user", 50, Out, use_cache=False)
    assert out.value == 3 and len(calls) == 2
    assert "INVALID" in calls[1]


async def test_schema_failure_after_repair_raises():
    async def provider(model, system, user, max_tokens, temperature):
        return Completion(text="nope", tokens_in=1, tokens_out=1)

    llm.set_provider(provider)
    with pytest.raises(llm.LLMSchemaError):
        await llm.call("small", "sys", "user", 50, Out, use_cache=False)


async def test_retries_then_succeeds_and_cache_hits(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(llm, "_sleep", fake_sleep)
    attempts = {"n": 0}

    async def provider(model, system, user, max_tokens, temperature):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RetryableError("429", retry_after=2.0)
        return Completion(text='{"value": 7}', tokens_in=10, tokens_out=5)

    llm.set_provider(provider)
    usage = llm.RunUsage()
    tok = llm.set_usage(usage)
    try:
        assert (await llm.call("small", "s", "u", 20, Out)).value == 7
        assert (await llm.call("small", "s", "u", 20, Out)).value == 7  # cached
    finally:
        llm.reset_usage(tok)
    assert attempts["n"] == 3
    assert all(s >= 2.0 for s in sleeps)  # honoured retry-after
    assert usage.calls == 1 and usage.cache_hits == 1


async def test_gives_up_after_five_attempts(monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(llm, "_sleep", fake_sleep)
    n = {"c": 0}

    async def provider(*a):
        n["c"] += 1
        raise RetryableError("503")

    llm.set_provider(provider)
    with pytest.raises(llm.LLMUnavailable):
        await llm.call("small", "s", "u", 20, Out, use_cache=False)
    assert n["c"] == llm.MAX_ATTEMPTS


async def test_stress_30_calls_stay_under_tpm(monkeypatch):
    """30 concurrent calls against a 10k TPM limit on a virtual clock:
    the tokens admitted in any 60-second window never exceed 80% of the limit."""
    from backend.config import settings

    clock = {"t": 0.0}
    monkeypatch.setattr(llm, "_clock", lambda: clock["t"])

    async def fake_sleep(s):
        clock["t"] += s
        await asyncio.sleep(0)

    monkeypatch.setattr(llm, "_sleep", fake_sleep)
    monkeypatch.setattr(settings, "tpm_limit", 10_000)
    monkeypatch.setattr(settings, "rpm_limit", 1_000)
    llm.reset_budgeter()
    admitted: list[tuple[float, int]] = []

    async def provider(model, system, user, max_tokens, temperature):
        used = llm.estimate_tokens(system) + llm.estimate_tokens(user) + max_tokens
        admitted.append((clock["t"], used))
        await asyncio.sleep(0)
        return Completion(text='{"value": 1}', tokens_in=used - max_tokens, tokens_out=max_tokens)

    llm.set_provider(provider)
    user = "x" * 3600  # ~1000 input tokens
    await asyncio.gather(*(llm.call("small", "s", f"{user}{i}", 500, Out, use_cache=False) for i in range(30)))
    assert len(admitted) == 30
    cap = 0.8 * 10_000
    for t0, _ in admitted:
        window = sum(n for t, n in admitted if t0 <= t < t0 + 60)
        assert window <= cap, (t0, window)
    # ~45k tokens at 8k/min must take more than 4 virtual minutes
    assert max(t for t, _ in admitted) > 4 * 60


async def test_unknown_provider_is_a_config_error(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "llm_provider", "nonsense")
    with pytest.raises(llm.LLMConfigError):
        await llm.call("small", "s", "u", 20, Out, use_cache=False)
    assert not issubclass(llm.LLMConfigError, llm.LLMError)  # agents must not swallow it


async def test_groq_request_shape_and_json_failure_repair(monkeypatch):
    import httpx

    from backend.config import settings

    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "small_model", "openai/gpt-oss-20b")
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append((str(request.url), request.headers["authorization"], body))
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed", "failed_generation": '{"value": "x"'}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"value": 4}'}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 3}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    out = await llm.call("small", "Return JSON", "u", 50, Out, use_cache=False)
    assert out.value == 4 and len(sent) == 2  # failed generation went through the repair step
    url, auth, body = sent[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert auth == "Bearer gsk_test"
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False


async def test_long_retry_after_fails_fast(monkeypatch):
    async def provider(*a):
        raise RetryableError("429", retry_after=3600)

    llm.set_provider(provider)
    with pytest.raises(llm.LLMUnavailable, match="daily quota"):
        await llm.call("small", "s", "u", 20, Out, use_cache=False)
