"""Provider-neutral chat model configuration and construction."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage


class ToolCallingChatModel(Protocol):
    def bind_tools(self, tools: Sequence[dict[str, Any]]) -> "ToolCallingChatModel": ...

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage: ...


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    temperature: float
    api_key: str | None = field(default=None, repr=False)
    app_url: str | None = None
    app_title: str | None = None


class LLMProvider(Protocol):
    def create(self, config: LLMConfig) -> ToolCallingChatModel: ...


def load_llm_config(
    environ: Mapping[str, str] | None = None,
) -> LLMConfig:
    """Load required LLM settings from process environment or local .env."""
    if environ is None:
        load_dotenv()
        environ = os.environ

    required = (
        "AGENT_LLM_PROVIDER",
        "AGENT_LLM_MODEL",
        "AGENT_LLM_BASE_URL",
        "AGENT_LLM_TEMPERATURE",
    )
    missing = [key for key in required if not environ.get(key, "").strip()]
    if missing:
        raise ValueError(
            "LLM configuration is incomplete; set the required AGENT_LLM_* values."
        )

    try:
        temperature = float(environ["AGENT_LLM_TEMPERATURE"])
    except (TypeError, ValueError) as exc:
        raise ValueError("AGENT_LLM_TEMPERATURE must be numeric.") from exc
    if not 0 <= temperature <= 1:
        raise ValueError("AGENT_LLM_TEMPERATURE is outside the supported range.")

    provider = environ["AGENT_LLM_PROVIDER"].strip().lower()
    api_key = (
        environ.get("OPENROUTER_API_KEY") or None
        if provider == "openrouter"
        else environ.get("AGENT_LLM_API_KEY") or None
    )

    return LLMConfig(
        provider=provider,
        model=environ["AGENT_LLM_MODEL"].strip(),
        base_url=environ["AGENT_LLM_BASE_URL"].strip(),
        temperature=temperature,
        api_key=api_key,
        app_url=environ.get("OPENROUTER_HTTP_REFERER") or None,
        app_title=environ.get("OPENROUTER_APP_TITLE") or None,
    )


class OllamaProvider:
    def create(self, config: LLMConfig) -> ToolCallingChatModel:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
        )


class OpenRouterProvider:
    def create(self, config: LLMConfig) -> ToolCallingChatModel:
        if not config.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required when AGENT_LLM_PROVIDER=openrouter."
            )

        from langchain_openrouter import ChatOpenRouter

        return ChatOpenRouter(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=config.temperature,
            app_url=config.app_url,
            app_title=config.app_title,
            max_retries=0,
        )


class OpenAICompatibleProvider:
    """OpenAI-compatible endpoint using the project's validated factory."""

    def create(self, config: LLMConfig) -> ToolCallingChatModel:
        if not config.api_key:
            raise ValueError(
                "AGENT_LLM_API_KEY is required when AGENT_LLM_PROVIDER=openai."
            )

        # Import lazily: provider_factory imports ToolCallingChatModel from
        # this module, so a top-level import would create a cycle.
        from app.agent.provider_factory import create_provider_model
        from app.config import ProviderSettings

        settings = ProviderSettings(
            protocol="openai",
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            temperature=config.temperature,
            timeout=60.0,
            max_retries=0,
        )
        return create_provider_model(settings)


PROVIDERS: dict[str, LLMProvider] = {
    "ollama": OllamaProvider(),
    "openrouter": OpenRouterProvider(),
    "openai": OpenAICompatibleProvider(),
}


def create_chat_model(
    config: LLMConfig | None = None,
) -> ToolCallingChatModel:
    settings = config or load_llm_config()
    provider = PROVIDERS.get(settings.provider)
    if provider is None:
        raise ValueError("Configured LLM provider is not supported.")
    return provider.create(settings)
