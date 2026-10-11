"""Factory building tool-calling chat models for custom provider endpoints.

Supports any service exposing an OpenAI-compatible or Anthropic-compatible
API, selected purely by protocol — never by vendor or service name. The
custom ``base_url`` is always passed through unchanged; no vendor default
endpoint or environment API key is ever substituted. Settings must come from
a trusted server-side source (see ``app.config.ProviderSettings``), not from
agent/user message state.
"""

from __future__ import annotations

from app.agent.llm import ToolCallingChatModel
from app.config import ProviderSettings


def create_provider_model(settings: ProviderSettings) -> ToolCallingChatModel:
    """Build a tool-calling chat model from validated provider settings."""
    if settings.protocol == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )

    if settings.protocol == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )

    raise ValueError("Configured provider protocol is not supported.")
