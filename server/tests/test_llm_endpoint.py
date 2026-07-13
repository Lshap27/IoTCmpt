from app.core.config import Settings
from app.services.llm import resolve_chat_completions_url


def test_deepseek_base_url_gets_chat_completions_suffix():
    assert resolve_chat_completions_url("https://api.deepseek.com") == ("https://api.deepseek.com/chat/completions")


def test_versioned_base_url_and_trailing_slash_are_normalized():
    assert resolve_chat_completions_url("https://example.com/v1/") == ("https://example.com/v1/chat/completions")


def test_legacy_full_endpoint_is_not_duplicated():
    endpoint = "https://example.com/openai/v1/chat/completions?api-version=2026-01-01"
    assert resolve_chat_completions_url(endpoint) == endpoint


def test_default_online_model_is_deepseek_v4_flash():
    settings = Settings(_env_file=None)

    assert settings.llm_endpoint == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
