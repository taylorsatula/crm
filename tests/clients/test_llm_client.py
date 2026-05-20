"""Tests for the OpenAI-compatible Chat Completions LLM client."""

import os
from types import SimpleNamespace

import openai
import pytest


class FakeCompletions:
    def __init__(self):
        self.calls = []
        self.responses = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            return _completion(content="default")

        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeModels:
    def __init__(self):
        self.list_calls = []
        self.retrieve_calls = []
        self.error = None

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(id="gpt-test")])

    def retrieve(self, model, **kwargs):
        self.retrieve_calls.append((model, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(id=model)


class FakeOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())
        self.models = FakeModels()


@pytest.fixture
def fake_openai(monkeypatch):
    from clients import llm_client as module

    fake_client = FakeOpenAIClient()
    init_calls = []

    def openai_factory(**kwargs):
        init_calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(module, "OpenAI", openai_factory)
    return fake_client, init_calls


def _completion(content="pong", usage=None, model="gpt-test"):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(
        id="chatcmpl_123",
        model=model,
        choices=[choice],
        usage=usage,
    )


def _usage(**overrides):
    data = {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _chunk(content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice], usage=usage)


def _usage_chunk(usage):
    return SimpleNamespace(choices=[], usage=usage)


def _tool_delta(
    *,
    index=0,
    tool_id=None,
    tool_type=None,
    name=None,
    arguments=None,
):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(
        index=index,
        id=tool_id,
        type=tool_type,
        function=function,
    )


class TestLLMClientInit:
    def test_init_defaults_to_gpt_5_mini_and_configures_openai(self, fake_openai):
        from clients.llm_client import LLMClient

        _, init_calls = fake_openai

        client = LLMClient(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            organization="org_123",
            project="proj_123",
            timeout=30,
            max_retries=4,
        )

        assert client.model == "gpt-5-mini"
        assert init_calls == [
            {
                "api_key": "test-key",
                "base_url": "https://openrouter.ai/api/v1",
                "organization": "org_123",
                "project": "proj_123",
                "timeout": 30,
                "max_retries": 4,
            }
        ]

    def test_init_fetches_vault_config_with_optional_base_url(
        self, fake_openai, monkeypatch
    ):
        from clients import llm_client as module

        _, init_calls = fake_openai
        monkeypatch.setattr(
            module,
            "get_llm_config",
            lambda: {
                "api_key": "vault-key",
                "base_url": "https://llm.example.com/v1",
            },
        )

        client = module.LLMClient()

        assert client.api_key == "vault-key"
        assert client.base_url == "https://llm.example.com/v1"
        assert init_calls[0]["api_key"] == "vault-key"
        assert init_calls[0]["base_url"] == "https://llm.example.com/v1"


class TestGenerate:
    def test_generate_uses_chat_completions_and_preserves_roles(self, fake_openai):
        from clients.llm_client import LLMClient, LLMResponse

        fake_client, _ = fake_openai
        usage = _usage(
            completion_tokens_details=SimpleNamespace(reasoning_tokens=3)
        )
        fake_client.chat.completions.responses.append(
            _completion(content="structured answer", usage=usage)
        )

        messages = [
            {"role": "system", "content": "broad instructions"},
            {"role": "developer", "content": "implementation guidance"},
            {"role": "user", "content": "hello"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object"},
                },
            }
        ]

        client = LLMClient(api_key="test-key", model="gpt-test")
        result = client.generate(
            messages=messages,
            model="provider/model",
            tools=tools,
            temperature=0.2,
            max_completion_tokens=77,
            response_format={"type": "json_object"},
            metadata={"request_id": "req_1"},
            tool_choice="auto",
            parallel_tool_calls=True,
            seed=123,
            stop=["END"],
            top_p=0.9,
            extra_body={"provider": {"order": ["openai"]}},
            reasoning_effort="low",
            safety_identifier="user_123",
            service_tier="default",
            verbosity="low",
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "structured answer"
        assert result.usage["prompt_tokens"] == 11
        assert result.usage["completion_tokens"] == 7
        assert result.usage["completion_tokens_details"]["reasoning_tokens"] == 3

        call = fake_client.chat.completions.calls[0]
        assert call["model"] == "provider/model"
        assert call["messages"] == messages
        assert [message["role"] for message in call["messages"]] == [
            "system",
            "developer",
            "user",
        ]
        assert call["tools"] == tools
        assert call["temperature"] == 0.2
        assert call["max_completion_tokens"] == 77
        assert call["response_format"] == {"type": "json_object"}
        assert call["metadata"] == {"request_id": "req_1"}
        assert call["tool_choice"] == "auto"
        assert call["parallel_tool_calls"] is True
        assert call["seed"] == 123
        assert call["stop"] == ["END"]
        assert call["top_p"] == 0.9
        assert call["extra_body"] == {"provider": {"order": ["openai"]}}
        assert call["reasoning_effort"] == "low"
        assert call["safety_identifier"] == "user_123"
        assert call["service_tier"] == "default"
        assert call["verbosity"] == "low"

    def test_generate_uses_max_completion_tokens_when_requested(self, fake_openai):
        from clients.llm_client import LLMClient

        fake_client, _ = fake_openai
        client = LLMClient(api_key="test-key")

        client.generate(
            messages=[{"role": "user", "content": "hello"}],
            max_completion_tokens=42,
        )

        call = fake_client.chat.completions.calls[0]
        assert call["max_completion_tokens"] == 42
        assert "temperature" not in call

    def test_generate_omits_optional_parameters_by_default(self, fake_openai):
        from clients.llm_client import LLMClient

        fake_client, _ = fake_openai
        client = LLMClient(api_key="test-key")

        client.generate(messages=[{"role": "user", "content": "hello"}])

        assert fake_client.chat.completions.calls[0] == {
            "model": "gpt-5-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }

    def test_generate_rejects_unsupported_roles_without_conversion(self, fake_openai):
        from clients.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        with pytest.raises(ValueError, match="Unsupported message role"):
            client.generate(messages=[{"role": "function", "content": "legacy"}])

    def test_generate_validates_tool_messages(self, fake_openai):
        from clients.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        with pytest.raises(ValueError, match="tool_call_id"):
            client.generate(messages=[{"role": "tool", "content": "result"}])

    def test_tool_definitions_must_be_openai_function_tools(self, fake_openai):
        from clients.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        with pytest.raises(ValueError, match="OpenAI function tools"):
            client.generate(
                messages=[{"role": "user", "content": "hello"}],
                tools=[{"name": "lookup", "input_schema": {"type": "object"}}],
            )

    def test_generate_maps_openai_errors_to_llm_error(self, fake_openai):
        from clients.llm_client import LLMClient, LLMError

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.append(openai.OpenAIError("boom"))
        client = LLMClient(api_key="test-key")

        with pytest.raises(LLMError, match="boom"):
            client.generate(messages=[{"role": "user", "content": "hello"}])


class TestLLMHealthCheck:
    def test_health_check_retrieves_configured_model_with_timeout(
        self, fake_openai
    ):
        from clients.llm_client import LLMClient

        fake_client, _ = fake_openai
        client = LLMClient(api_key="test-key", model="provider/model")

        assert client.health_check() is True
        assert fake_client.models.retrieve_calls == [
            ("provider/model", {"timeout": 10.0})
        ]

    def test_health_check_maps_openai_errors(self, fake_openai):
        from clients.llm_client import LLMClient, LLMError

        fake_client, _ = fake_openai
        fake_client.models.error = openai.OpenAIError("model lookup failed")
        client = LLMClient(api_key="test-key")

        with pytest.raises(LLMError, match="model lookup failed"):
            client.health_check()


class TestStreaming:
    def test_stream_yields_text_usage_and_complete_events(self, fake_openai):
        from clients.llm_client import CompleteEvent, LLMClient, TextEvent, UsageEvent

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.append(
            [
                _chunk(content="Hel"),
                _chunk(content="lo"),
                _usage_chunk(_usage()),
            ]
        )
        client = LLMClient(api_key="test-key")

        events = list(
            client.stream(messages=[{"role": "user", "content": "Say hello"}])
        )

        assert [event.content for event in events if isinstance(event, TextEvent)] == [
            "Hel",
            "lo",
        ]
        usage_events = [event for event in events if isinstance(event, UsageEvent)]
        assert usage_events[0].usage["prompt_tokens"] == 11
        complete = [event for event in events if isinstance(event, CompleteEvent)][0]
        assert complete.response == {"role": "assistant", "content": "Hello"}

        call = fake_client.chat.completions.calls[0]
        assert call["stream"] is True
        assert call["stream_options"] == {"include_usage": True}

    def test_stream_executes_fragmented_tool_calls_and_continues(self, fake_openai):
        from clients.llm_client import (
            CompleteEvent,
            LLMClient,
            TextEvent,
            ToolCompletedEvent,
            ToolDetectedEvent,
            ToolExecutingEvent,
        )

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="lookup",
                            )
                        ]
                    ),
                    _chunk(
                        tool_calls=[_tool_delta(arguments='{"query"')]
                    ),
                    _chunk(
                        tool_calls=[_tool_delta(arguments=': "crm"}')]
                    ),
                ],
                [_chunk(content="Tool result handled.")],
            ]
        )
        client = LLMClient(api_key="test-key")
        executor_calls = []

        def tool_executor(name, arguments):
            executor_calls.append((name, arguments))
            return "lookup result"

        tool = {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object"}},
        }
        events = list(
            client.stream(
                messages=[
                    {"role": "system", "content": "Use tools when useful."},
                    {"role": "user", "content": "Find CRM details."},
                ],
                tools=[tool],
                tool_executor=tool_executor,
            )
        )

        assert any(isinstance(event, ToolDetectedEvent) for event in events)
        executing = [event for event in events if isinstance(event, ToolExecutingEvent)]
        assert executing[0].tool_name == "lookup"
        assert executing[0].tool_id == "call_1"
        assert executing[0].arguments == {"query": "crm"}
        assert executor_calls == [("lookup", {"query": "crm"})]
        completed = [event for event in events if isinstance(event, ToolCompletedEvent)]
        assert completed[0].result == "lookup result"
        assert [event.content for event in events if isinstance(event, TextEvent)] == [
            "Tool result handled."
        ]
        complete_events = [event for event in events if isinstance(event, CompleteEvent)]
        assert len(complete_events) == 1
        assert complete_events[0].response == {
            "role": "assistant",
            "content": "Tool result handled.",
        }

        second_call_messages = fake_client.chat.completions.calls[1]["messages"]
        assert second_call_messages[0]["role"] == "system"
        assert second_call_messages[-2] == {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"query": "crm"}',
                    },
                }
            ],
        }
        assert second_call_messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "lookup result",
        }

    def test_stream_reports_tool_executor_failures(self, fake_openai):
        from clients.llm_client import LLMClient, ToolErrorEvent

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="lookup",
                                arguments='{"query": "crm"}',
                            )
                        ]
                    )
                ],
                [_chunk(content="Handled failure.")],
            ]
        )
        client = LLMClient(api_key="test-key")

        def failing_executor(name, arguments):
            raise RuntimeError("tool failed")

        events = list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=failing_executor,
            )
        )

        errors = [event for event in events if isinstance(event, ToolErrorEvent)]
        assert errors[0].error == "tool failed"
        second_call_messages = fake_client.chat.completions.calls[1]["messages"]
        assert second_call_messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Error: tool failed",
        }

    def test_stream_requires_executor_when_tools_are_enabled(self, fake_openai):
        from clients.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        with pytest.raises(ValueError, match="tool_executor is required"):
            list(
                client.stream(
                    messages=[{"role": "user", "content": "Find CRM details."}],
                    tools=[
                        {
                            "type": "function",
                            "function": {"name": "lookup"},
                        }
                    ],
                )
            )

    def test_tool_definitions_reject_duplicate_names(self, fake_openai):
        from clients.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        with pytest.raises(ValueError, match="Duplicate tool name: lookup"):
            client.generate(
                messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {"type": "function", "function": {"name": "lookup"}},
                    {"type": "function", "function": {"name": "lookup"}},
                ],
            )

    def test_stream_rejects_undeclared_tool_calls_without_calling_executor(
        self, fake_openai
    ):
        from clients.llm_client import LLMClient, TextEvent, ToolErrorEvent

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="delete_everything",
                                arguments="{}",
                            )
                        ]
                    )
                ],
                [_chunk(content="Recovered.")],
            ]
        )
        client = LLMClient(api_key="test-key")
        executor_calls = []

        events = list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=lambda name, arguments: executor_calls.append(
                    (name, arguments)
                ),
            )
        )

        assert executor_calls == []
        tool_errors = [event for event in events if isinstance(event, ToolErrorEvent)]
        assert tool_errors[0].tool_name == "delete_everything"
        assert tool_errors[0].error == "Tool is not declared: delete_everything"
        assert [event.content for event in events if isinstance(event, TextEvent)] == [
            "Recovered."
        ]
        second_call_messages = fake_client.chat.completions.calls[1]["messages"]
        assert second_call_messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Error: tool is not declared: delete_everything",
        }

    def test_stream_allows_model_to_repair_invalid_tool_arguments(self, fake_openai):
        from clients.llm_client import ErrorEvent, LLMClient, TextEvent, ToolErrorEvent

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="lookup",
                                arguments='{"query"',
                            )
                        ]
                    )
                ],
                [_chunk(content="Repaired.")],
            ]
        )
        client = LLMClient(api_key="test-key")
        executor_calls = []

        events = list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=lambda name, arguments: executor_calls.append(
                    (name, arguments)
                ),
            )
        )

        assert executor_calls == []
        assert not [event for event in events if isinstance(event, ErrorEvent)]
        tool_errors = [event for event in events if isinstance(event, ToolErrorEvent)]
        assert tool_errors[0].error.startswith("invalid tool arguments:")
        assert [event.content for event in events if isinstance(event, TextEvent)] == [
            "Repaired."
        ]
        second_call_messages = fake_client.chat.completions.calls[1]["messages"]
        assert second_call_messages[-1]["role"] == "tool"
        assert second_call_messages[-1]["tool_call_id"] == "call_1"
        assert second_call_messages[-1]["content"].startswith(
            "Error: invalid tool arguments:"
        )

    def test_stream_aborts_malformed_tool_call_shape(self, fake_openai):
        from clients.llm_client import CompleteEvent, ErrorEvent, LLMClient

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.append(
            [_chunk(tool_calls=[_tool_delta(arguments='{"query": "crm"}')])]
        )
        client = LLMClient(api_key="test-key")
        executor_calls = []

        events = list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=lambda name, arguments: executor_calls.append(
                    (name, arguments)
                ),
            )
        )

        assert executor_calls == []
        errors = [event for event in events if isinstance(event, ErrorEvent)]
        assert errors[0].error == "Discarded malformed streamed tool call"
        assert errors[0].details == "index 0: missing tool call id"
        assert not [event for event in events if isinstance(event, CompleteEvent)]
        assert len(fake_client.chat.completions.calls) == 1

    def test_stream_stops_when_tool_round_limit_is_exceeded(self, fake_openai):
        from clients.llm_client import ErrorEvent, LLMClient

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="lookup",
                                arguments='{"query": "first"}',
                            )
                        ]
                    )
                ],
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_2",
                                tool_type="function",
                                name="lookup",
                                arguments='{"query": "second"}',
                            )
                        ]
                    )
                ],
            ]
        )
        client = LLMClient(api_key="test-key")
        executor_calls = []

        events = list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=lambda name, arguments: executor_calls.append(
                    (name, arguments)
                )
                or "lookup result",
                max_tool_rounds=1,
            )
        )

        assert executor_calls == [("lookup", {"query": "first"})]
        errors = [event for event in events if isinstance(event, ErrorEvent)]
        assert errors[0].error == "Tool loop exceeded max_tool_rounds"
        assert errors[0].details == "max_tool_rounds=1"
        assert len(fake_client.chat.completions.calls) == 2

    def test_stream_uses_forced_tool_choice_only_on_first_call(self, fake_openai):
        from clients.llm_client import LLMClient

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.extend(
            [
                [
                    _chunk(
                        tool_calls=[
                            _tool_delta(
                                tool_id="call_1",
                                tool_type="function",
                                name="lookup",
                                arguments='{"query": "crm"}',
                            )
                        ]
                    )
                ],
                [_chunk(content="Done.")],
            ]
        )
        client = LLMClient(api_key="test-key")

        list(
            client.stream(
                messages=[{"role": "user", "content": "Find CRM details."}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup"},
                    }
                ],
                tool_executor=lambda name, arguments: "lookup result",
                tool_choice={"type": "function", "function": {"name": "lookup"}},
            )
        )

        assert fake_client.chat.completions.calls[0]["tool_choice"] == {
            "type": "function",
            "function": {"name": "lookup"},
        }
        assert "tool_choice" not in fake_client.chat.completions.calls[1]

    def test_stream_maps_openai_errors_to_error_event(self, fake_openai):
        from clients.llm_client import ErrorEvent, LLMClient

        fake_client, _ = fake_openai
        fake_client.chat.completions.responses.append(openai.OpenAIError("boom"))
        client = LLMClient(api_key="test-key")

        events = list(
            client.stream(messages=[{"role": "user", "content": "hello"}])
        )

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert events[0].error == "boom"


class TestLLMResponse:
    def test_has_content_and_usage_attributes(self):
        from clients.llm_client import LLMResponse

        response = LLMResponse(
            content="Test",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

        assert response.content == "Test"
        assert response.usage["prompt_tokens"] == 10
        assert response.usage["completion_tokens"] == 5


class TestStreamEvents:
    def test_usage_event(self):
        from clients.llm_client import UsageEvent

        event = UsageEvent(usage={"total_tokens": 15})

        assert event.usage["total_tokens"] == 15

    def test_tool_events(self):
        from clients.llm_client import (
            ErrorEvent,
            TextEvent,
            ToolCompletedEvent,
            ToolDetectedEvent,
            ToolExecutingEvent,
        )

        assert TextEvent(content="Hello").content == "Hello"
        assert ToolDetectedEvent(tool_name="search", tool_id="call_123").tool_id == (
            "call_123"
        )
        assert ToolExecutingEvent(
            tool_name="search",
            tool_id="call_123",
            arguments={"query": "test"},
        ).arguments == {"query": "test"}
        assert ToolCompletedEvent(
            tool_name="search",
            tool_id="call_123",
            result="Found 5 results",
        ).result == "Found 5 results"
        assert ErrorEvent(error="API failed", details="Rate limit").details == (
            "Rate limit"
        )


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="live LLM smoke tests require RUN_LIVE_LLM_TESTS=1 and OPENAI_API_KEY",
)
def test_live_generate_smoke():
    from clients.llm_client import LLMClient, LLMResponse

    client = LLMClient(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    )
    result = client.generate(
        messages=[{"role": "user", "content": "Reply with exactly: PONG"}],
        max_completion_tokens=16,
    )

    assert isinstance(result, LLMResponse)
    assert result.content
