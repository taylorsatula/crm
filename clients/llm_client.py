"""
LLM client for OpenAI-compatible APIs.

Uses the OpenAI Python library to connect to any OpenAI-compatible endpoint
(OpenAI, OpenRouter, local models, etc.). Configuration comes from Vault.

Usage:
    from clients.llm_client import LLMClient

    client = LLMClient()
    response = client.generate(
        messages=[
            {"role": "system", "content": "You extract structured data."},
            {"role": "user", "content": "Parse this: ..."}
        ],
        response_format={"type": "json_object"}
    )
    print(response.content)
"""

import logging
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from clients.vault_client import get_llm_config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Error from LLM client operations."""
    pass


class LLMResponse(BaseModel):
    """Response from LLM generation."""

    content: str
    raw_response: dict[str, Any] | None = None


class LLMClient:
    """
    OpenAI-compatible LLM client.

    Connects to any OpenAI-compatible API using configuration from Vault.
    Supports standard chat completions with optional JSON mode.
    """

    def __init__(self):
        """Initialize client with config from Vault."""
        try:
            config = get_llm_config()
        except Exception as e:
            raise LLMError(f"Failed to get LLM config from Vault: {e}")

        self.api_key = config["api_key"]
        self.base_url = config["base_url"]
        self.model_name = config["model_name"]

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        logger.info(f"LLM client initialized with model: {self.model_name}")

    def generate(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None
    ) -> LLMResponse:
        """
        Generate a completion from the LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            response_format: Optional format spec (e.g., {"type": "json_object"})
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with content and optional raw response

        Raises:
            LLMError: If API call fails or returns no response
        """
        try:
            kwargs: dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
            }

            if response_format:
                kwargs["response_format"] = response_format

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            response = self._client.chat.completions.create(**kwargs)

            if not response.choices:
                raise LLMError("No response choices returned from LLM")

            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                raw_response={
                    "id": response.id,
                    "model": response.model,
                    "usage": response.usage.model_dump(mode="json") if response.usage else None
                }
            )

        except LLMError:
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise LLMError(f"LLM API call failed: {e}")
