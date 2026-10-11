"""Trusted server-side configuration contracts for the application."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ProviderProtocol = Literal["openai", "anthropic"]


class ProviderSettings(BaseModel):
    """Validated settings for a custom OpenAI- or Anthropic-compatible endpoint.

    Settings must originate from trusted server-side configuration (for
    example a future admin settings layer) and are never extracted from
    agent/user message state. ``base_url`` is mandatory; credentials must not
    be embedded in it. The API key is masked in text output and excluded from
    serialization.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: ProviderProtocol
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: SecretStr = Field(exclude=True)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: float = Field(default=30.0, gt=0.0)
    max_retries: int = Field(default=2, ge=0)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("base_url must not be empty.")
        if any(character.isspace() for character in cleaned):
            raise ValueError("base_url must not contain whitespace.")
        parts = urlsplit(cleaned)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an absolute http(s) URL.")
        if parts.username is not None or parts.password is not None:
            raise ValueError("base_url must not embed credentials.")
        return cleaned

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("model must not be empty.")
        return cleaned

    @field_validator("api_key", mode="after")
    @classmethod
    def _validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key must not be empty.")
        return value
