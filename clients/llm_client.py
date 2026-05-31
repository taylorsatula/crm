"""
OpenAI-compatible Chat Completions LLM client.

The rest of the application talks to LLMs through this module only. The client
uses the OpenAI Chat Completions API shape so it can target OpenAI, OpenRouter,
or another compatible provider by configuring model and base_url.
"""

import json
import logging
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI
from pydantic import BaseModel

from clients.vault_client import get_llm_config

logger = logging.getLogger(__name__)

_VALID_MESSAGE_ROLES = {"system", "developer", "user", "assistant", "tool"}


# === Response Types ===


class LLMResponse(BaseModel):
    """Non-streaming response."""

    content: str
    raw_response: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


# === Stream Events ===


@dataclass
class TextEvent:
    """Text chunk from LLM."""

    content: str


@dataclass
class UsageEvent:
    """Token usage emitted during streaming."""

    usage: dict[str, Any]


@dataclass
class ToolDetectedEvent:
    """Tool call detected in response."""

    tool_name: str
    tool_id: str


@dataclass
class ToolExecutingEvent:
    """Tool execution starting."""

    tool_name: str
    tool_id: str
    arguments: dict


@dataclass
class ToolCompletedEvent:
    """Tool execution succeeded."""

    tool_name: str
    tool_id: str
    result: str


@dataclass
class ToolErrorEvent:
    """Tool execution failed."""

    tool_name: str
    tool_id: str
    error: str


@dataclass
class CompleteEvent:
    """Stream finished."""

    response: Any


@dataclass
class ErrorEvent:
    """Stream error."""

    error: str
    details: str | None = None


StreamEvent = (
    TextEvent
    | UsageEvent
    | ToolDetectedEvent
    | ToolExecutingEvent
    | ToolCompletedEvent
    | ToolErrorEvent
    | CompleteEvent
    | ErrorEvent
)


# === Errors ===


class LLMError(Exception):
    """LLM operation error."""


# === Client ===


class LLMClient:
    """OpenAI-compatible Chat Completions client."""

    DEFAULT_MODEL = "gpt-5-mini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        timeout: float | None = None,
        health_timeout: float = 10.0,
        max_retries: int = 2,
    ):
        """
        Initialize the Chat Completions client.

        Args:
            api_key: Provider API key. If None, fetched from Vault.
            model: Model name. If None, uses DEFAULT_MODEL.
            base_url: Optional OpenAI-compatible provider URL.
            organization: Optional OpenAI organization.
            project: Optional OpenAI project.
            timeout: Optional request timeout passed to the SDK.
            health_timeout: Timeout for lightweight health checks.
            max_retries: SDK retry count.
        """
        if api_key is None:
            config = get_llm_config()
            api_key = config["api_key"]
            base_url = base_url or config.get("base_url")

        if not api_key:
            raise ValueError("api_key is required")

        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url
        self.organization = organization
        self.project = project
        self.timeout = timeout
        self.health_timeout = health_timeout
        self.max_retries = max_retries

        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "max_retries": max_retries,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        if organization:
            client_kwargs["organization"] = organization
        if project:
            client_kwargs["project"] = project
        if timeout is not None:
            client_kwargs["timeout"] = timeout

        self._client = OpenAI(**client_kwargs)
        logger.info("LLM client initialized with model: %s", self.model)

    def health_check(self) -> bool:
        """Check provider reachability and access to the configured model."""
        try:
            models = self._client.models.list(timeout=self.health_timeout)
        except openai.OpenAIError as e:
            logger.error("LLM health check failed: %s", e)
            raise LLMError(f"LLM health check failed: {e}")
        except Exception as e:
            logger.error("LLM health check failed: %s", e)
            raise LLMError(f"LLM health check failed: {e}")

        model_ids = {model.id for model in models.data}
        if self.model not in model_ids:
            raise LLMError(f"Configured LLM model is unavailable: {self.model}")

        return True

    def generate(
        self,
        messages: list[dict],
        temperature: float | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
        max_completion_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        seed: int | None = None,
        stop: str | list[str] | None = None,
        top_p: float | None = None,
        extra_body: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        safety_identifier: str | None = None,
        service_tier: str | None = None,
        verbosity: str | None = None,
    ) -> LLMResponse:
        """
        Non-streaming generation for extraction, distillation, etc.

        Messages are passed through with caller-provided roles preserved. Valid
        roles are system, developer, user, assistant, and tool.
        """
        api_messages = self._validate_messages(messages)
        api_tools = self._validate_tools(tools)
        params = self._build_completion_params(
            messages=api_messages,
            model=model or self.model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            tools=api_tools,
            response_format=response_format,
            metadata=metadata,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            seed=seed,
            stop=stop,
            top_p=top_p,
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            safety_identifier=safety_identifier,
            service_tier=service_tier,
            verbosity=verbosity,
        )

        try:
            response = self._client.chat.completions.create(**params)
        except openai.OpenAIError as e:
            logger.error("LLM API error: %s", e)
            raise LLMError(f"LLM API call failed: {e}")

        message = self._first_choice_message(response)
        return LLMResponse(
            content=self._message_content_text(message),
            raw_response=self._object_to_dict(response),
            usage=self._extract_usage(response),
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
        temperature: float | None = None,
        model: str | None = None,
        max_completion_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        seed: int | None = None,
        stop: str | list[str] | None = None,
        top_p: float | None = None,
        extra_body: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        safety_identifier: str | None = None,
        service_tier: str | None = None,
        verbosity: str | None = None,
        max_tool_rounds: int = 6,
    ) -> Generator[StreamEvent, None, None]:
        """Streaming generation with an OpenAI function-tool loop."""
        api_messages = self._validate_messages(messages)
        api_tools = self._validate_tools(tools)
        if api_tools and tool_executor is None:
            raise ValueError("tool_executor is required when tools are enabled")
        if max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be greater than or equal to zero")

        allowed_tool_names = self._tool_names(api_tools)
        current_messages = [dict(message) for message in api_messages]
        use_model = model or self.model
        tool_rounds = 0
        first_request = True

        while True:
            assistant_message = None
            complete_event = None
            for event in self._stream_response(
                messages=current_messages,
                tools=api_tools,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                model=use_model,
                response_format=response_format,
                metadata=metadata,
                tool_choice=tool_choice if first_request else None,
                parallel_tool_calls=parallel_tool_calls,
                seed=seed,
                stop=stop,
                top_p=top_p,
                extra_body=extra_body,
                reasoning_effort=reasoning_effort,
                safety_identifier=safety_identifier,
                service_tier=service_tier,
                verbosity=verbosity,
            ):
                if isinstance(event, CompleteEvent):
                    assistant_message = event.response
                    complete_event = event
                else:
                    yield event

            first_request = False

            if assistant_message is None:
                return

            tool_calls = self._extract_tool_calls(assistant_message)
            if not tool_calls or tool_executor is None:
                if complete_event is not None:
                    yield complete_event
                return

            tool_rounds += 1
            if tool_rounds > max_tool_rounds:
                yield ErrorEvent(
                    "Tool loop exceeded max_tool_rounds",
                    f"max_tool_rounds={max_tool_rounds}",
                )
                return

            current_messages.append(assistant_message)
            tool_execution = self._execute_tool_calls(
                tool_calls,
                tool_executor,
                allowed_tool_names,
            )
            while True:
                try:
                    yield next(tool_execution)
                except StopIteration as completed:
                    tool_messages = completed.value
                    break
            current_messages.extend(tool_messages)

    # === Private ===

    def _build_completion_params(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None,
        max_completion_tokens: int | None,
        tools: list[dict] | None,
        response_format: dict[str, Any] | None,
        metadata: dict[str, str] | None,
        tool_choice: str | dict[str, Any] | None,
        parallel_tool_calls: bool | None,
        seed: int | None,
        stop: str | list[str] | None,
        top_p: float | None,
        extra_body: dict[str, Any] | None,
        reasoning_effort: str | None,
        safety_identifier: str | None,
        service_tier: str | None,
        verbosity: str | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if temperature is not None:
            params["temperature"] = temperature
        if max_completion_tokens is not None:
            params["max_completion_tokens"] = max_completion_tokens
        if tools:
            params["tools"] = tools
        if response_format is not None:
            params["response_format"] = response_format
        if metadata is not None:
            params["metadata"] = metadata
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            params["parallel_tool_calls"] = parallel_tool_calls
        if seed is not None:
            params["seed"] = seed
        if stop is not None:
            params["stop"] = stop
        if top_p is not None:
            params["top_p"] = top_p
        if extra_body is not None:
            params["extra_body"] = extra_body
        if reasoning_effort is not None:
            params["reasoning_effort"] = reasoning_effort
        if safety_identifier is not None:
            params["safety_identifier"] = safety_identifier
        if service_tier is not None:
            params["service_tier"] = service_tier
        if verbosity is not None:
            params["verbosity"] = verbosity
        if stream:
            params["stream"] = True
            params["stream_options"] = {"include_usage": True}

        return params

    def _validate_messages(self, messages: list[dict]) -> list[dict]:
        """Validate message roles and tool messages without rewriting roles."""
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")

        validated = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("each message must be a dict")

            role = message.get("role")
            if role not in _VALID_MESSAGE_ROLES:
                raise ValueError(f"Unsupported message role: {role}")

            if role == "tool":
                if "tool_call_id" not in message:
                    raise ValueError("tool messages require tool_call_id")
                if "content" not in message:
                    raise ValueError("tool messages require content")
            elif "content" not in message and not (
                role == "assistant" and "tool_calls" in message
            ):
                raise ValueError("messages require content unless assistant has tool_calls")

            validated.append(dict(message))

        return validated

    def _validate_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """Validate OpenAI function tool definitions."""
        if tools is None:
            return None
        if not isinstance(tools, list):
            raise ValueError("tools must be a list")

        for tool in tools:
            if not isinstance(tool, dict):
                raise ValueError("each tool must be a dict")
            if tool.get("type") != "function":
                raise ValueError("tools must be OpenAI function tools")
            function = tool.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                raise ValueError("function tools require function.name")

        names = self._tool_names(tools)
        if len(names) != len(tools):
            seen = set()
            for tool in tools:
                name = tool["function"]["name"]
                if name in seen:
                    raise ValueError(f"Duplicate tool name: {name}")
                seen.add(name)

        return [dict(tool) for tool in tools]

    def _tool_names(self, tools: list[dict] | None) -> set[str]:
        if not tools:
            return set()
        return {tool["function"]["name"] for tool in tools}

    def _stream_response(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float | None,
        max_completion_tokens: int | None,
        model: str,
        response_format: dict[str, Any] | None,
        metadata: dict[str, str] | None,
        tool_choice: str | dict[str, Any] | None,
        parallel_tool_calls: bool | None,
        seed: int | None,
        stop: str | list[str] | None,
        top_p: float | None,
        extra_body: dict[str, Any] | None,
        reasoning_effort: str | None,
        safety_identifier: str | None,
        service_tier: str | None,
        verbosity: str | None,
    ) -> Generator[StreamEvent, None, None]:
        """Stream a single API call and build an assistant message."""
        params = self._build_completion_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            tools=tools,
            response_format=response_format,
            metadata=metadata,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            seed=seed,
            stop=stop,
            top_p=top_p,
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            safety_identifier=safety_identifier,
            service_tier=service_tier,
            verbosity=verbosity,
            stream=True,
        )

        text_parts: list[str] = []
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        detected_tool_indexes: set[int] = set()

        try:
            stream = self._client.chat.completions.create(**params)
            for chunk in stream:
                usage = self._extract_usage_from_usage(self._get(chunk, "usage"))
                if usage:
                    yield UsageEvent(usage=usage)

                for choice in self._get(chunk, "choices", []) or []:
                    delta = self._get(choice, "delta")
                    if delta is None:
                        continue

                    content = self._get(delta, "content")
                    if content:
                        text_parts.append(content)
                        yield TextEvent(content)

                    for tool_delta in self._get(delta, "tool_calls", []) or []:
                        index = self._get(tool_delta, "index", 0) or 0
                        entry = tool_calls_by_index.setdefault(
                            index,
                            {
                                "id": None,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )

                        tool_id = self._get(tool_delta, "id")
                        if tool_id:
                            entry["id"] = tool_id

                        tool_type = self._get(tool_delta, "type")
                        if tool_type:
                            entry["type"] = tool_type

                        function_delta = self._get(tool_delta, "function")
                        if function_delta is not None:
                            name_delta = self._get(function_delta, "name")
                            if name_delta:
                                entry["function"]["name"] += name_delta
                            args_delta = self._get(function_delta, "arguments")
                            if args_delta:
                                entry["function"]["arguments"] += args_delta

                        if (
                            index not in detected_tool_indexes
                            and entry["id"]
                            and entry["function"]["name"]
                        ):
                            detected_tool_indexes.add(index)
                            yield ToolDetectedEvent(
                                entry["function"]["name"],
                                entry["id"],
                            )

            assistant_message, malformed_tool_calls = (
                self._build_stream_assistant_message(
                    text_parts, tool_calls_by_index
                )
            )
            for malformed_tool_call in malformed_tool_calls:
                yield ErrorEvent(
                    "Discarded malformed streamed tool call",
                    malformed_tool_call,
                )
            if malformed_tool_calls:
                return
            yield CompleteEvent(response=assistant_message)

        except openai.OpenAIError as e:
            yield ErrorEvent(str(e), getattr(e, "message", None))

    def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        tool_executor: Callable[[str, dict], str],
        allowed_tool_names: set[str],
    ) -> Generator[StreamEvent, None, list[dict[str, str]]]:
        """Execute tool calls concurrently and return ordered tool messages."""
        messages_by_id: dict[str, dict[str, str]] = {}
        executable_calls = []

        for tool_call in tool_calls:
            if tool_call["name"] not in allowed_tool_names:
                content = f"Error: tool is not declared: {tool_call['name']}"
                yield ToolErrorEvent(
                    tool_call["name"],
                    tool_call["id"],
                    f"Tool is not declared: {tool_call['name']}",
                )
                messages_by_id[tool_call["id"]] = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": content,
                }
                continue

            if argument_error := tool_call.get("argument_error"):
                content = f"Error: invalid tool arguments: {argument_error}"
                yield ToolErrorEvent(
                    tool_call["name"],
                    tool_call["id"],
                    f"invalid tool arguments: {argument_error}",
                )
                messages_by_id[tool_call["id"]] = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": content,
                }
                continue

            yield ToolExecutingEvent(
                tool_call["name"],
                tool_call["id"],
                tool_call["arguments"],
            )
            executable_calls.append(tool_call)

        if executable_calls:
            with ThreadPoolExecutor(max_workers=len(executable_calls)) as executor:
                futures = {
                    executor.submit(
                        tool_executor, tool_call["name"], tool_call["arguments"]
                    ): tool_call
                    for tool_call in executable_calls
                }
                for future in as_completed(futures):
                    tool_call = futures[future]
                    try:
                        result = str(future.result())
                        messages_by_id[tool_call["id"]] = {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                        yield ToolCompletedEvent(
                            tool_call["name"],
                            tool_call["id"],
                            result,
                        )
                    except Exception as e:
                        messages_by_id[tool_call["id"]] = {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": f"Error: {e}",
                        }
                        yield ToolErrorEvent(
                            tool_call["name"],
                            tool_call["id"],
                            str(e),
                        )

        return [messages_by_id[tool_call["id"]] for tool_call in tool_calls]

    def _build_stream_assistant_message(
        self,
        text_parts: list[str],
        tool_calls_by_index: dict[int, dict[str, Any]],
    ) -> tuple[dict[str, Any], list[str]]:
        content = "".join(text_parts)
        tool_calls = []
        malformed_tool_calls = []

        for index in sorted(tool_calls_by_index):
            tool_call = tool_calls_by_index[index]
            if error := self._tool_call_shape_error(tool_call):
                malformed_tool_calls.append(f"index {index}: {error}")
                continue
            tool_calls.append(tool_call)

        message: dict[str, Any] = {
            "role": "assistant",
            "content": content if content or not tool_calls else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        return message, malformed_tool_calls

    def _tool_call_shape_error(self, tool_call: dict[str, Any]) -> str | None:
        """Return why a streamed tool call cannot be replayed, if malformed."""
        tool_id = self._get(tool_call, "id")
        if not isinstance(tool_id, str) or not tool_id:
            return "missing tool call id"

        if self._get(tool_call, "type") != "function":
            return "tool call type must be function"

        function = self._get(tool_call, "function")
        if function is None:
            return "missing function payload"

        name = self._get(function, "name")
        if not isinstance(name, str) or not name:
            return "missing function name"

        arguments = self._get(function, "arguments")
        if not isinstance(arguments, str):
            return "function arguments must be a string"

        return None

    def _extract_tool_calls(self, assistant_message: Any) -> list[dict[str, Any]]:
        """Extract completed function tool calls from an assistant message."""
        raw_tool_calls = self._get(assistant_message, "tool_calls", []) or []
        tool_calls = []

        for raw_tool_call in raw_tool_calls:
            if self._tool_call_shape_error(raw_tool_call):
                continue

            function = self._get(raw_tool_call, "function", {}) or {}
            raw_arguments = self._get(function, "arguments", "") or "{}"
            parsed_arguments: dict[str, Any] = {}
            argument_error = None
            try:
                decoded_arguments = json.loads(raw_arguments)
                if isinstance(decoded_arguments, dict):
                    parsed_arguments = decoded_arguments
                else:
                    argument_error = "tool arguments must be a JSON object"
            except json.JSONDecodeError as e:
                argument_error = str(e)

            tool_call = {
                "id": self._get(raw_tool_call, "id"),
                "name": self._get(function, "name"),
                "arguments": parsed_arguments,
                "raw_arguments": raw_arguments,
            }
            if argument_error:
                tool_call["argument_error"] = argument_error
            tool_calls.append(tool_call)

        return tool_calls

    def _first_choice_message(self, response: Any) -> Any:
        choices = self._get(response, "choices", []) or []
        if not choices:
            return None
        return self._get(choices[0], "message")

    def _message_content_text(self, message: Any) -> str:
        """Extract text from an OpenAI-compatible message content field."""
        content = self._get(message, "content")
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                    continue
                text = self._get(block, "text")
                if text:
                    parts.append(text)
            return "".join(parts)
        return str(content)

    def _extract_usage(self, response: Any) -> dict[str, Any] | None:
        """Extract token usage from a response."""
        return self._extract_usage_from_usage(self._get(response, "usage"))

    def _extract_usage_from_usage(self, usage: Any) -> dict[str, Any] | None:
        """Extract OpenAI-compatible usage objects while preserving provider details."""
        if usage is None:
            return None

        usage_data = self._object_to_dict(usage)
        if not usage_data:
            return None

        return usage_data

    def _object_to_dict(self, value: Any) -> Any:
        """Convert SDK objects, simple namespaces, dicts, and lists to dicts."""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, dict):
            return {
                key: self._object_to_dict(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, list):
            return [self._object_to_dict(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True)
        if hasattr(value, "__dict__"):
            return {
                key: self._object_to_dict(item)
                for key, item in vars(value).items()
                if item is not None
            }
        return value

    def _get(self, value: Any, key: str, default: Any = None) -> Any:
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)
