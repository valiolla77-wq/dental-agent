import unittest
from unittest.mock import patch

from langchain_openai import ChatOpenAI

from app.agent.llm import (
    LLMConfig,
    PROVIDERS,
    create_chat_model,
    load_llm_config,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.registry import get_llm_tool_schemas


class AgentLLMTests(unittest.TestCase):
    def test_configuration_is_read_from_environment_values(self):
        settings = load_llm_config(
            {
                "AGENT_LLM_PROVIDER": "ollama",
                "AGENT_LLM_MODEL": "test-model-tag",
                "AGENT_LLM_BASE_URL": "http://127.0.0.1:11434",
                "AGENT_LLM_TEMPERATURE": "0.15",
                "AGENT_LLM_API_KEY": "test-secret",
            }
        )
        self.assertEqual(settings.provider, "ollama")
        self.assertEqual(settings.model, "test-model-tag")
        self.assertEqual(settings.base_url, "http://127.0.0.1:11434")
        self.assertEqual(settings.temperature, 0.15)
        self.assertEqual(settings.api_key, "test-secret")

    def test_missing_required_configuration_fails_without_echoing_values(self):
        with self.assertRaisesRegex(ValueError, "AGENT_LLM_*"):
            load_llm_config({})

    def test_invalid_temperature_is_rejected(self):
        values = {
            "AGENT_LLM_PROVIDER": "ollama",
            "AGENT_LLM_MODEL": "model-tag",
            "AGENT_LLM_BASE_URL": "http://localhost:11434",
            "AGENT_LLM_TEMPERATURE": "not-a-number",
        }
        with self.assertRaisesRegex(ValueError, "TEMPERATURE"):
            load_llm_config(values)

    def test_provider_factory_creates_ollama_without_network_call(self):
        model = create_chat_model(
            LLMConfig(
                provider="ollama",
                model="test-model-tag",
                base_url="http://127.0.0.1:11434",
                temperature=0.2,
            )
        )
        self.assertEqual(model.model, "test-model-tag")
        self.assertEqual(model.temperature, 0.2)
        self.assertEqual(str(model.base_url), "http://127.0.0.1:11434")

    def test_openrouter_configuration_uses_provider_specific_api_key(self):
        settings = load_llm_config(
            {
                "AGENT_LLM_PROVIDER": "openrouter",
                "AGENT_LLM_MODEL": "vendor/model-name",
                "AGENT_LLM_BASE_URL": "https://openrouter.ai/api/v1",
                "AGENT_LLM_TEMPERATURE": "0",
                "OPENROUTER_API_KEY": "test-openrouter-secret",
                "OPENROUTER_HTTP_REFERER": "https://example.test",
                "OPENROUTER_APP_TITLE": "Dental Agent Test",
            }
        )
        self.assertEqual(settings.provider, "openrouter")
        self.assertEqual(settings.api_key, "test-openrouter-secret")
        self.assertEqual(settings.app_url, "https://example.test")
        self.assertEqual(settings.app_title, "Dental Agent Test")
        self.assertNotIn("test-openrouter-secret", repr(settings))

    def test_openrouter_provider_creates_model_and_binds_registry_schemas(self):
        model = create_chat_model(
            LLMConfig(
                provider="openrouter",
                model="vendor/model-name",
                base_url="https://openrouter.ai/api/v1",
                temperature=0,
                api_key="test-openrouter-secret",
            )
        )
        self.assertEqual(model.model, "vendor/model-name")
        self.assertEqual(model.temperature, 0)
        self.assertEqual(str(model.openrouter_api_base), "https://openrouter.ai/api/v1")
        self.assertIsNotNone(model.bind_tools(get_llm_tool_schemas()))
        self.assertNotIn("test-openrouter-secret", repr(model))

    def test_openrouter_missing_api_key_fails_without_secret_details(self):
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY") as context:
            create_chat_model(
                LLMConfig(
                    provider="openrouter",
                    model="vendor/model-name",
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0,
                )
            )
        self.assertNotIn("test-openrouter-secret", str(context.exception))

    def test_openrouter_config_reads_key_from_environment_and_not_legacy_key(self):
        values = {
            "AGENT_LLM_PROVIDER": "openrouter",
            "AGENT_LLM_MODEL": "vendor/model-name",
            "AGENT_LLM_BASE_URL": "https://openrouter.ai/api/v1",
            "AGENT_LLM_TEMPERATURE": "0",
            "AGENT_LLM_API_KEY": "legacy-secret",
        }
        settings = load_llm_config(values)
        self.assertIsNone(settings.api_key)
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY"):
            create_chat_model(settings)

    def test_openrouter_model_construction_does_not_log_api_key(self):
        with self.assertNoLogs(level="DEBUG"):
            model = create_chat_model(
                LLMConfig(
                    provider="openrouter",
                    model="vendor/model-name",
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0,
                    api_key="test-openrouter-secret",
                )
            )
        self.assertNotIn("test-openrouter-secret", repr(model))

    def test_provider_accepts_current_registry_tool_schemas(self):
        model = create_chat_model(
            LLMConfig(
                provider="ollama",
                model="test-model-tag",
                base_url="http://127.0.0.1:11434",
                temperature=0.2,
            )
        )
        bound_model = model.bind_tools(get_llm_tool_schemas())
        self.assertIsNotNone(bound_model)

    def test_registry_exports_only_named_tool_schemas(self):
        schemas = get_llm_tool_schemas()
        names = [schema["function"]["name"] for schema in schemas]
        self.assertEqual(len(names), 7)
        self.assertIn("book_appointment", names)
        self.assertIn("search_dental_services", names)
        self.assertTrue(all(schema["type"] == "function" for schema in schemas))

    def test_openai_configuration_uses_generic_api_key(self):
        settings = load_llm_config(
            {
                "AGENT_LLM_PROVIDER": "openai",
                "AGENT_LLM_MODEL": "local-model",
                "AGENT_LLM_BASE_URL": "http://127.0.0.1:20128/v1",
                "AGENT_LLM_TEMPERATURE": "0",
                "AGENT_LLM_API_KEY": "test-openai-compatible-secret",
            }
        )
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.api_key, "test-openai-compatible-secret")
        self.assertNotIn("test-openai-compatible-secret", repr(settings))

    def test_openai_provider_builds_chatopenai_with_custom_endpoint(self):
        model = create_chat_model(
            LLMConfig(
                provider="openai",
                model="local-model",
                base_url="http://127.0.0.1:20128/v1",
                temperature=0,
                api_key="test-openai-compatible-secret",
            )
        )
        self.assertIsInstance(model, ChatOpenAI)
        self.assertEqual(model.model_name, "local-model")
        self.assertEqual(
            str(model.root_client.base_url).rstrip("/"),
            "http://127.0.0.1:20128/v1",
        )
        self.assertEqual(
            model.root_client.api_key, "test-openai-compatible-secret"
        )
        self.assertIsNotNone(model.bind_tools(get_llm_tool_schemas()))
        self.assertNotIn(
            "test-openai-compatible-secret", repr(model) + str(model)
        )

    def test_openai_provider_passes_validated_provider_settings(self):
        with patch(
            "app.agent.provider_factory.create_provider_model"
        ) as factory:
            create_chat_model(
                LLMConfig(
                    provider="openai",
                    model="local-model",
                    base_url="http://127.0.0.1:20128/v1",
                    temperature=0.25,
                    api_key="test-openai-compatible-secret",
                )
            )
        provider_settings = factory.call_args.args[0]
        self.assertEqual(provider_settings.protocol, "openai")
        self.assertEqual(
            provider_settings.base_url, "http://127.0.0.1:20128/v1"
        )
        self.assertEqual(provider_settings.model, "local-model")
        self.assertEqual(provider_settings.temperature, 0.25)
        self.assertEqual(provider_settings.timeout, 60.0)
        self.assertEqual(provider_settings.max_retries, 0)
        self.assertEqual(
            provider_settings.api_key.get_secret_value(),
            "test-openai-compatible-secret",
        )

    def test_openai_provider_requires_agently_api_key(self):
        with self.assertRaisesRegex(ValueError, "AGENT_LLM_API_KEY"):
            create_chat_model(
                LLMConfig(
                    provider="openai",
                    model="local-model",
                    base_url="http://127.0.0.1:20128/v1",
                    temperature=0,
                )
            )

    def test_openai_provider_exists_alongside_existing_providers(self):
        self.assertEqual(
            set(PROVIDERS), {"ollama", "openrouter", "openai"}
        )

    def test_factory_rejects_unregistered_provider(self):
        with self.assertRaisesRegex(ValueError, "not supported"):
            create_chat_model(
                LLMConfig(
                    provider="unconfigured",
                    model="model-tag",
                    base_url="http://localhost",
                    temperature=0.2,
                )
            )

    def test_system_prompt_has_core_safety_and_scope_rules(self):
        for rule in (
            "حدس نزن",
            "تأیید",
            "تجویز دارو",
            "Errorهای Tool",
            "book_appointment",
            "خودت به‌صورت متنی",
        ):
            self.assertIn(rule, SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
