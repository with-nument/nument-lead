"""Provider adapters (Step 4.6, 4.7) against fake SDK clients: request building, normalising, errors, batch."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from nument_engine.llm import gemini as gemini_mod
from nument_engine.llm import openai_provider as openai_mod
from nument_engine.llm.gemini import GeminiProvider
from nument_engine.llm.openai_provider import OpenAIProvider
from nument_engine.llm.schema import provider_schema
from nument_engine.llm.types import LLMRequest, ProviderError, redact
from nument_engine.models import LeadJudgement, SignalClassification


def _req(**overrides: Any) -> LLMRequest:
    base: dict[str, Any] = {
        "task": "classify_signal",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "system": "sys",
        "user": "user text",
        "schema": SignalClassification,
        "max_output_tokens": 900,
        "temperature": None,
        "thinking": "low",
        "tools": [],
        "timeout_s": 30,
    }
    base.update(overrides)
    return LLMRequest(**base)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def gresp(
    text: str = '{"ok": true}',
    *,
    finish: Any = types.FinishReason.STOP,
    grounding: types.GroundingMetadata | None = None,
    candidates: bool = True,
) -> types.GenerateContentResponse:
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100,
        candidates_token_count=20,
        thoughts_token_count=30,
        cached_content_token_count=10,
        tool_use_prompt_token_count=5,
    )
    cands = (
        [
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish,
                grounding_metadata=grounding,
            )
        ]
        if candidates
        else []
    )
    return types.GenerateContentResponse(candidates=cands, usage_metadata=usage)


def api_error(code: int, message: str, status: str = "", details: Any = None) -> genai_errors.APIError:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "status": status}}
    if details is not None:
        body["error"]["details"] = details
    return genai_errors.APIError(code, body)


class FakeGenaiClient:
    def __init__(self, replies: list[Any] | None = None, *, jobs: dict[str, types.BatchJob] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []
        self.jobs = jobs if jobs is not None else {}
        self.created: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        outer = self

        class Models:
            def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
                outer.calls.append({"model": model, "contents": contents, "config": config})
                r = outer.replies.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r

            def list(self) -> list[types.Model]:
                return [
                    types.Model(
                        name="models/gemini-3.8-flash", supported_actions=["generateContent", "batchGenerateContent"]
                    ),
                    types.Model(name="models/gemini-4-argon", supported_actions=["generateContent"]),
                ]

        class Batches:
            def create(self, *, model: str, src: Any, config: Any) -> types.BatchJob:
                outer.created.append({"model": model, "src": src, "config": config})
                name = f"batches/{len(outer.created)}"
                outer.jobs[name] = types.BatchJob(
                    name=name, model=f"models/{model}", state=types.JobState.JOB_STATE_PENDING
                )
                return outer.jobs[name]

            def get(self, *, name: str) -> types.BatchJob:
                if name not in outer.jobs:
                    raise api_error(404, "Requested entity was not found.", "NOT_FOUND")
                return outer.jobs[name]

            def cancel(self, *, name: str) -> None:
                outer.cancelled.append(name)

        self.models = Models()
        self.batches = Batches()


def _provider(*clients: FakeGenaiClient) -> GeminiProvider:
    keys = [f"key-{i}" for i in range(len(clients))]
    by_key = dict(zip(keys, clients, strict=True))
    return GeminiProvider(keys, client_factory=lambda key: by_key[key])


def test_build_config_maps_every_request_field() -> None:
    req = _req(tools=["web_search"], service_tier="flex", temperature=0.2)
    cfg = GeminiProvider.build_config(req)
    assert cfg.thinking_config is not None and cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == provider_schema(SignalClassification)
    assert cfg.tools is not None and cfg.tools[0].google_search is not None
    assert cfg.temperature == 0.2 and cfg.max_output_tokens == 900 and cfg.system_instruction == "sys"
    assert cfg.service_tier == types.ServiceTier.FLEX
    assert cfg.http_options is not None and cfg.http_options.timeout == 30_000
    assert cfg.automatic_continuation is False
    plain = GeminiProvider.build_config(_req(schema=None, thinking=None), for_batch=True)
    assert plain.response_json_schema is None and plain.thinking_config is None and plain.temperature is None
    assert plain.http_options is None and plain.tools is None


def test_generate_normalises_text_usage_and_grounding() -> None:
    grounding = types.GroundingMetadata(
        web_search_queries=["clinic bot pune", "", "clinic bot pune"],
        grounding_chunks=[
            types.GroundingChunk(web=types.GroundingChunkWeb(uri="https://r.example/1", title="forum.example"))
        ],
        grounding_supports=[types.GroundingSupport(segment=types.Segment(text="a post"), grounding_chunk_indices=[0])],
    )
    client = FakeGenaiClient([gresp("hello", grounding=grounding)])
    resp = _provider(client).generate(_req(schema=None, tools=["web_search"]))
    assert resp.text == "hello" and resp.finish_reason == "stop"
    u = resp.usage
    assert (u.input_tokens, u.output_tokens, u.cached_tokens, u.thinking_tokens) == (105, 50, 10, 30)
    assert resp.grounding == {
        "queries": ["clinic bot pune"],
        "sources": [{"uri": "https://r.example/1", "title": "forum.example", "domain": None}],
        "supports": [{"text": "a post", "chunks": [0]}],
    }
    assert u.search_queries == 1
    assert client.calls[0]["model"] == "gemini-3.8-flash" and client.calls[0]["contents"] == "user text"


def test_max_tokens_is_reported_not_raised() -> None:
    resp = _provider(FakeGenaiClient([gresp('{"a":', finish=types.FinishReason.MAX_TOKENS)])).generate(_req())
    assert resp.finish_reason == "max_tokens"


@pytest.mark.parametrize(
    "response",
    [
        gresp(finish=types.FinishReason.SAFETY),
        gresp(candidates=False),
        types.GenerateContentResponse(
            candidates=[], prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY")
        ),
    ],
    ids=["safety", "no-candidates", "prompt-blocked"],
)
def test_blocked_or_empty_answers_raise_blocked(response: types.GenerateContentResponse) -> None:
    with pytest.raises(ProviderError) as caught:
        _provider(FakeGenaiClient([response])).generate(_req())
    assert caught.value.kind == "blocked"


PER_MINUTE = [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]}]
PER_DAY = [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (api_error(429, "You exceeded your current quota", "RESOURCE_EXHAUSTED", PER_MINUTE), "transient"),
        (api_error(429, "You exceeded your current quota", "RESOURCE_EXHAUSTED", PER_DAY), "quota"),
        (api_error(429, "Quota exceeded, limit: 0, model: gemini-4-argon", "RESOURCE_EXHAUSTED"), "not_found"),
        (api_error(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"), "auth"),
        (api_error(400, "User location is not supported for the API use.", "FAILED_PRECONDITION"), "auth"),
        (api_error(403, "Permission denied", "PERMISSION_DENIED"), "auth"),
        (api_error(404, "models/gemini-9 is not found", "NOT_FOUND"), "not_found"),
        (api_error(400, "Thinking level MINIMAL is not supported for this model.", "INVALID_ARGUMENT"), "bad_request"),
        (api_error(503, "The model is overloaded.", "UNAVAILABLE"), "transient"),
        (api_error(500, "Internal error", "INTERNAL"), "transient"),
        (httpx.ReadTimeout("timed out"), "transient"),
        (ValueError("bug"), "unknown"),
    ],
)
def test_gemini_errors_are_classified(exc: BaseException, kind: str) -> None:
    assert gemini_mod.classify_error(exc, "gemini-3.8-flash").kind == kind


def test_backup_key_takes_over_after_a_quota_error() -> None:
    first = FakeGenaiClient([api_error(429, "quota", "RESOURCE_EXHAUSTED", PER_DAY)])
    second = FakeGenaiClient([gresp("one"), gresp("two")])
    provider = _provider(first, second)
    assert provider.generate(_req(schema=None)).text == "one"
    assert provider.active_key == 2
    assert provider.generate(_req(schema=None)).text == "two"
    assert len(first.calls) == 1 and len(second.calls) == 2


def test_last_key_failing_raises_the_classified_error() -> None:
    provider = _provider(FakeGenaiClient([api_error(401, "bad key", "UNAUTHENTICATED")]))
    with pytest.raises(ProviderError) as caught:
        provider.generate(_req())
    assert caught.value.kind == "auth" and caught.value.provider == "gemini"


def test_transient_errors_do_not_switch_keys() -> None:
    first = FakeGenaiClient([api_error(503, "overloaded", "UNAVAILABLE")])
    provider = _provider(first, FakeGenaiClient())
    with pytest.raises(ProviderError) as caught:
        provider.generate(_req())
    assert caught.value.kind == "transient" and provider.active_key == 1


def test_gemini_batch_submit_poll_fetch_and_cancel() -> None:
    client = FakeGenaiClient()
    provider = _provider(client)
    reqs = [_req(key="k1"), _req(key="k2", user="second")]
    name = provider.submit_batch("gemini-3.8-flash", reqs, "nlead:extract_facts:run")
    created = client.created[0]
    assert created["model"] == "gemini-3.8-flash" and created["config"].display_name == "nlead:extract_facts:run"
    src = created["src"]
    assert [r.metadata for r in src] == [{"key": "k1"}, {"key": "k2"}]
    assert src[1].contents[0].parts[0].text == "second"
    assert src[0].config.response_json_schema is None  # the Batch API ignores it (verified 2026-11-12)
    assert src[0].config.response_schema == gemini_mod.batch_schema(SignalClassification)
    assert src[0].config.response_schema.properties["employer_name"].nullable is True
    assert src[0].config.http_options is None

    assert provider.poll_batch(name) == "pending"
    job = client.jobs[name]
    job.state = types.JobState.JOB_STATE_SUCCEEDED
    job.dest = types.BatchJobDestination(
        inlined_responses=[
            types.InlinedResponse(response=gresp('{"x": 1}'), metadata={"key": "k1"}),
            types.InlinedResponse(error=types.JobError(code=13, message="internal"), metadata={"key": "k2"}),
        ]
    )
    assert provider.poll_batch(name) == "succeeded"
    rows = provider.fetch_batch(name)
    assert rows[0].key == "k1" and rows[0].response is not None and rows[0].response.text == '{"x": 1}'
    assert rows[0].response.model == "gemini-3.8-flash" and rows[0].response.usage.input_tokens == 105
    assert rows[1].key == "k2" and rows[1].response is None and rows[1].error == "internal"
    provider.cancel_batch(name)
    assert client.cancelled == [name]


def test_batch_jobs_are_found_under_the_key_that_created_them() -> None:
    owner = FakeGenaiClient(jobs={})
    other = FakeGenaiClient(jobs={})
    owner.jobs["batches/9"] = types.BatchJob(name="batches/9", model="models/gemini-3.8-flash",
                                             state=types.JobState.JOB_STATE_RUNNING)  # fmt: skip
    provider = _provider(other, owner)
    assert provider.poll_batch("batches/9") == "running"


def test_batch_results_file_is_parsed() -> None:
    line = {
        "key": "k1",
        "response": {
            "candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": "{}"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 2},
        },
    }  # fmt: skip
    resp = gemini_mod.response_from_dict(line["response"], "gemini-3.8-flash")  # type: ignore[arg-type]
    assert resp.text == "{}" and resp.usage.output_tokens == 5 and resp.finish_reason == "stop"


def test_list_models_strips_the_prefix() -> None:
    models = _provider(FakeGenaiClient()).list_models()
    assert [m.name for m in models] == ["gemini-3.8-flash", "gemini-4-argon"]
    assert "batchGenerateContent" in models[0].actions


def test_provider_needs_a_key() -> None:
    with pytest.raises(ValueError, match="at least one API key"):
        GeminiProvider(["", ""])


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class FakeOpenAI:
    def __init__(self, replies: list[Any] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []
        self.files_created: list[str] = []
        self.file_contents: dict[str, str] = {}
        self.batch_state = SimpleNamespace(status="in_progress", output_file_id=None, error_file_id=None)
        outer = self

        class Responses:
            def create(self, **kwargs: Any) -> Any:
                outer.calls.append(kwargs)
                r = outer.replies.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r

        class Files:
            def create(self, *, file: Any, purpose: str) -> Any:
                outer.files_created.append(file.read().decode())
                return SimpleNamespace(id="file-in")

            def content(self, file_id: str) -> Any:
                return SimpleNamespace(text=outer.file_contents[file_id])

        class Batches:
            def create(self, **kwargs: Any) -> Any:
                outer.batch_kwargs = kwargs
                return SimpleNamespace(id="batch_1")

            def retrieve(self, batch_id: str) -> Any:
                return outer.batch_state

            def cancel(self, batch_id: str) -> None:
                outer.batch_state.status = "cancelling"

        class Models:
            def list(self) -> list[Any]:
                return [SimpleNamespace(id="gpt-6.1-terra"), SimpleNamespace(id="gpt-6-luna")]

        self.responses = Responses()
        self.files = Files()
        self.batches = Batches()
        self.models = Models()


def oresp(text: str = '{"ok": 1}', *, status: str = "completed", search_calls: int = 0) -> Any:
    usage = SimpleNamespace(
        input_tokens=50,
        output_tokens=40,
        input_tokens_details=SimpleNamespace(cached_tokens=8),
        output_tokens_details=SimpleNamespace(reasoning_tokens=25),
    )
    output = [SimpleNamespace(type="web_search_call") for _ in range(search_calls)] + [SimpleNamespace(type="message")]
    return SimpleNamespace(output_text=text, usage=usage, status=status, incomplete_details=None, output=output)


def _oai(fake: FakeOpenAI) -> OpenAIProvider:
    return OpenAIProvider("sk-test", client_factory=lambda key: fake)


def test_openai_request_uses_strict_schema_reasoning_and_tools() -> None:
    fake = FakeOpenAI([oresp(search_calls=2)])
    resp = _oai(fake).generate(
        _req(provider="openai", model="gpt-6.1-terra", schema=LeadJudgement, tools=["web_search"])
    )
    body = fake.calls[0]
    assert body["model"] == "gpt-6.1-terra" and body["instructions"] == "sys" and body["input"] == "user text"
    assert body["reasoning"] == {"effort": "low"} and "temperature" not in body
    assert body["tools"] == [{"type": "web_search"}] and body["timeout"] == 30
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "LeadJudgement"
    assert fmt["schema"] == provider_schema(LeadJudgement)
    u = resp.usage
    assert (u.input_tokens, u.output_tokens, u.cached_tokens, u.thinking_tokens, u.search_queries) == (50, 40, 8, 25, 2)
    assert resp.finish_reason == "stop" and resp.text == '{"ok": 1}'


def _http_error(cls: type[openai.APIStatusError], status: int, message: str = "error") -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls(message, response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (
            _http_error(openai.AuthenticationError, 401, "Incorrect API key provided: sk-svcacct-abcdefghijklmnop"),
            "auth",
        ),
        (_http_error(openai.PermissionDeniedError, 403), "auth"),
        (_http_error(openai.RateLimitError, 429, "Rate limit reached"), "transient"),
        (_http_error(openai.RateLimitError, 429, "insufficient_quota: check your plan"), "quota"),
        (_http_error(openai.NotFoundError, 404), "not_found"),
        (_http_error(openai.BadRequestError, 400), "bad_request"),
        (_http_error(openai.InternalServerError, 500), "transient"),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")), "transient"),
    ],
)
def test_openai_errors_are_classified_and_redacted(exc: BaseException, kind: str) -> None:
    err = openai_mod.classify_error(exc, "gpt-6.1-terra")
    assert err.kind == kind
    assert "abcdefghijklmnop" not in err.message


def test_openai_content_filter_is_blocked() -> None:
    resp = SimpleNamespace(output_text="", usage=None, status="incomplete",
                           incomplete_details=SimpleNamespace(reason="content_filter"), output=[])  # fmt: skip
    with pytest.raises(ProviderError) as caught:
        _oai(FakeOpenAI([resp])).generate(_req(provider="openai", model="gpt-6.1-terra"))
    assert caught.value.kind == "blocked"


def test_openai_batch_round_trip() -> None:
    fake = FakeOpenAI()
    provider = _oai(fake)
    batch_id = provider.submit_batch(
        "gpt-6.1-terra", [_req(provider="openai", model="gpt-6.1-terra", key="k1")], "nlead"
    )
    assert batch_id == "batch_1" and fake.batch_kwargs["endpoint"] == "/v1/responses"
    line = json.loads(fake.files_created[0].strip())
    assert line["custom_id"] == "k1" and line["url"] == "/v1/responses" and line["body"]["text"]["format"]["strict"]
    assert provider.poll_batch(batch_id) == "running"
    fake.batch_state = SimpleNamespace(status="completed", output_file_id="out", error_file_id="errs")
    fake.file_contents["out"] = json.dumps({
        "custom_id": "k1",
        "response": {"status_code": 200, "body": {
            "model": "gpt-6.1-terra-2025-08-07", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"a\": 1}"}]}],
            "usage": {"input_tokens": 9, "output_tokens": 4}}},
    })  # fmt: skip
    fake.file_contents["errs"] = json.dumps({"custom_id": "k2", "error": {"message": "bad"}})
    assert provider.poll_batch(batch_id) == "succeeded"
    rows = provider.fetch_batch(batch_id)
    assert rows[0].key == "k1" and rows[0].response is not None and rows[0].response.text == '{"a": 1}'
    assert rows[0].response.usage.input_tokens == 9
    assert rows[1].key == "k2" and rows[1].response is None
    assert [m.name for m in provider.list_models()] == ["gpt-6.1-terra", "gpt-6-luna"]


def test_redact_removes_keys_and_tokens() -> None:
    text = "key AIzaSyA1234567890abcdefghijklmnop failed; sk-proj-abcdefghij1234; https://x?key=SECRET1&a=1"
    out = redact(text)
    assert "AIzaSy" not in out and "sk-proj-abcdefghij" not in out and "SECRET1" not in out
    assert "[redacted]" in out and len(redact("x" * 900)) == 500


def test_the_gateway_falls_back_to_the_direct_key_when_it_errors() -> None:
    """ET AI Gateway first: its outages and shared rate limits move the call to the direct Gemini key."""
    gateway = FakeGenaiClient([api_error(502, "could not reach", "UNAVAILABLE")])
    direct = FakeGenaiClient([gresp("hello")])
    by_key = {"gateway-key": gateway, "direct-key": direct}
    provider = GeminiProvider(
        ["gateway-key", "direct-key"],
        client_factory=lambda key: by_key[key],
        base_urls=["https://gateway.example/gemini", None],
    )
    assert provider.generate(_req(schema=None)).text == "hello"
    assert provider.active_key == 2


def test_a_direct_key_does_not_fall_back_on_a_transient_error() -> None:
    first = FakeGenaiClient([api_error(503, "overloaded", "UNAVAILABLE")])
    second = FakeGenaiClient([gresp("never used")])
    with pytest.raises(ProviderError):
        _provider(first, second).generate(_req(schema=None))
