import os
import unittest
from unittest.mock import patch

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agent.llm import PROVIDERS
from app.agent.provider_factory import create_provider_model
from app.config import ProviderSettings

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_dental_services",
        "description": "search services",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
}

OPENAI_SETTINGS = {
    "protocol": "openai",
    "base_url": "http://127.0.0.1:9000/v1",
    "model": "test-openai-model",
    "api_key": "test-openai-key-SECRET",
    "temperature": 0.2,
    "max_tokens": 128,
    "timeout": 5.0,
    "max_retries": 1,
}

ANTHROPIC_SETTINGS = {
    "protocol": "anthropic",
    "base_url": "http://127.0.0.1:9001",
    "model": "test-anthropic-model",
    "api_key": "test-anthropic-key-SECRET",
    "temperature": 0.3,
    "max_tokens": 256,
    "timeout": 7.0,
    "max_retries": 2,
}


class ProviderSettingsTests(unittest.TestCase):
    def test_unknown_protocol_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProviderSettings(**{**OPENAI_SETTINGS, "protocol": "google"})

    def test_invalid_base_urls_are_rejected(self):
        invalid_urls = (
            "",
            "   ",
            "localhost:9000/v1",
            "ftp://host/v1",
            "http://",
            "https://user:pass@host/v1",
            "http://host with space",
        )
        for bad_url in invalid_urls:
            with self.subTest(base_url=bad_url):
                with self.assertRaises(ValidationError):
                    ProviderSettings(**{**OPENAI_SETTINGS, "base_url": bad_url})

    def test_missing_base_url_is_rejected(self):
        without_base_url = {
            key: value
            for key, value in OPENAI_SETTINGS.items()
            if key != "base_url"
        }
        with self.assertRaises(ValidationError):
            ProviderSettings(**without_base_url)

    def test_blank_values_and_out_of_range_numbers_are_rejected(self):
        invalid_fields = (
            ("model", "   "),
            ("api_key", ""),
            ("temperature", 1.5),
            ("timeout", 0),
            ("max_retries", -1),
            ("max_tokens", 0),
        )
        for field_name, bad_value in invalid_fields:
            with self.subTest(field=field_name):
                with self.assertRaises(ValidationError):
                    ProviderSettings(**{**OPENAI_SETTINGS, field_name: bad_value})

    def test_api_key_is_hidden_in_text_and_json_output(self):
        settings = ProviderSettings(**OPENAI_SETTINGS)
        secret = OPENAI_SETTINGS["api_key"]
        self.assertNotIn(secret, repr(settings))
        self.assertNotIn(secret, str(settings))
        self.assertNotIn(secret, settings.model_dump_json())
        self.assertNotIn(secret, str(settings.model_dump()))

    def test_validation_error_output_does_not_leak_api_key(self):
        secret = OPENAI_SETTINGS["api_key"]
        with self.assertRaises(ValidationError) as caught:
            ProviderSettings(**{**OPENAI_SETTINGS, "base_url": "not-a-url"})
        self.assertNotIn(secret, str(caught.exception))


class ProviderFactoryTests(unittest.TestCase):
    def test_openai_model_uses_custom_endpoint_and_settings(self):
        model = create_provider_model(ProviderSettings(**OPENAI_SETTINGS))
        self.assertIsInstance(model, ChatOpenAI)
        self.assertEqual(model.model_name, "test-openai-model")
        self.assertEqual(model.temperature, 0.2)
        self.assertEqual(model.max_tokens, 128)
        self.assertEqual(model.request_timeout, 5.0)
        self.assertEqual(model.max_retries, 1)
        self.assertEqual(
            str(model.root_client.base_url).rstrip("/"),
            "http://127.0.0.1:9000/v1",
        )
        self.assertEqual(model.root_client.api_key, "test-openai-key-SECRET")

    def test_anthropic_model_uses_custom_endpoint_and_settings(self):
        model = create_provider_model(ProviderSettings(**ANTHROPIC_SETTINGS))
        self.assertIsInstance(model, ChatAnthropic)
        self.assertEqual(model.model, "test-anthropic-model")
        self.assertEqual(model.temperature, 0.3)
        self.assertEqual(model.max_tokens, 256)
        self.assertEqual(model.default_request_timeout, 7.0)
        self.assertEqual(model.max_retries, 2)
        self.assertEqual(model.anthropic_api_url, "http://127.0.0.1:9001")
        self.assertEqual(str(model._client.base_url), "http://127.0.0.1:9001")
        self.assertEqual(
            model.anthropic_api_key.get_secret_value(), "test-anthropic-key-SECRET"
        )

    def test_factory_passes_exact_arguments_to_openai_constructor(self):
        with patch("langchain_openai.ChatOpenAI") as constructor:
            create_provider_model(ProviderSettings(**OPENAI_SETTINGS))
        constructor.assert_called_once_with(
            model="test-openai-model",
            base_url="http://127.0.0.1:9000/v1",
            api_key="test-openai-key-SECRET",
            temperature=0.2,
            max_tokens=128,
            timeout=5.0,
            max_retries=1,
        )

    def test_factory_passes_exact_arguments_to_anthropic_constructor(self):
        with patch("langchain_anthropic.ChatAnthropic") as constructor:
            create_provider_model(ProviderSettings(**ANTHROPIC_SETTINGS))
        constructor.assert_called_once_with(
            model="test-anthropic-model",
            base_url="http://127.0.0.1:9001",
            api_key="test-anthropic-key-SECRET",
            temperature=0.3,
            max_tokens=256,
            timeout=7.0,
            max_retries=2,
        )

    def test_factory_rejects_protocol_that_bypassed_settings_validation(self):
        bypassed = ProviderSettings.model_construct(
            protocol="gemini",
            base_url="http://127.0.0.1:9000/v1",
            model="m",
            api_key=None,
        )
        with self.assertRaises(ValueError):
            create_provider_model(bypassed)

    def test_no_fallback_to_official_endpoint_or_environment_key(self):
        environment = {
            "OPENAI_API_KEY": "env-openai-KEY",
            "ANTHROPIC_API_KEY": "env-anthropic-KEY",
        }
        with patch.dict(os.environ, environment):
            openai_model = create_provider_model(ProviderSettings(**OPENAI_SETTINGS))
            anthropic_model = create_provider_model(
                ProviderSettings(**ANTHROPIC_SETTINGS)
            )
        self.assertNotIn("api.openai.com", str(openai_model.root_client.base_url))
        self.assertEqual(openai_model.root_client.api_key, OPENAI_SETTINGS["api_key"])
        self.assertNotEqual(
            openai_model.root_client.api_key, environment["OPENAI_API_KEY"]
        )
        self.assertNotIn("api.anthropic.com", anthropic_model.anthropic_api_url)
        self.assertNotEqual(
            anthropic_model.anthropic_api_key.get_secret_value(),
            environment["ANTHROPIC_API_KEY"],
        )

    def test_construction_never_logs_api_key(self):
        with self.assertNoLogs(level="DEBUG"):
            model = create_provider_model(ProviderSettings(**OPENAI_SETTINGS))
        self.assertNotIn(OPENAI_SETTINGS["api_key"], repr(model) + str(model))

    def test_bound_models_emit_provider_native_tool_schemas(self):
        openai_model = create_provider_model(ProviderSettings(**OPENAI_SETTINGS))
        openai_bound = openai_model.bind_tools([TOOL_SCHEMA])
        self.assertTrue(hasattr(openai_bound, "ainvoke"))
        self.assertEqual(
            openai_bound.kwargs["tools"][0]["function"]["name"],
            "search_dental_services",
        )

        anthropic_model = create_provider_model(ProviderSettings(**ANTHROPIC_SETTINGS))
        anthropic_bound = anthropic_model.bind_tools([TOOL_SCHEMA])
        self.assertTrue(hasattr(anthropic_bound, "ainvoke"))
        self.assertEqual(
            anthropic_bound.kwargs["tools"][0]["name"], "search_dental_services"
        )
        self.assertIn("input_schema", anthropic_bound.kwargs["tools"][0])

    def test_existing_ollama_and_openrouter_providers_are_unchanged(self):
        self.assertEqual(set(PROVIDERS), {"ollama", "openrouter", "openai"})


if __name__ == "__main__":
    unittest.main()
