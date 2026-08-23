from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings, get_llm


def test_valid_settings_report_configured_without_exposing_key():
    configured = Settings(
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_api_key="test-key-that-must-not-be-logged",
        database_path=ROOT / "database" / "test.db",
        chroma_persist_directory=ROOT / "data" / "processed" / "test-chroma",
        log_level="INFO",
        llm_base_url="",
    )

    assert configured.configured is True
    assert not hasattr(configured, "api_key")


def test_missing_settings_report_not_configured_and_error_is_safe():
    incomplete = Settings(
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_api_key="",
        database_path=ROOT / "database" / "test.db",
        chroma_persist_directory=ROOT / "data" / "processed" / "test-chroma",
        log_level="INFO",
        llm_base_url="",
    )

    assert incomplete.configured is False
    import src.config as config
    original = config.settings
    config.settings = incomplete
    try:
        with pytest.raises(RuntimeError, match="LLM_API_KEY must be configured") as error:
            get_llm()
        assert "test-key" not in str(error.value)
    finally:
        config.settings = original


def test_gemini_provider_supports_existing_tool_binding():
    import src.config as config
    from src.agent.graph import _TOOL_SCHEMAS

    original = config.settings
    config.settings = Settings(
        llm_provider="gemini",
        llm_model="gemini-3.1-flash-lite",
        llm_api_key="placeholder-key-for-construction-only",
        database_path=original.database_path,
        chroma_persist_directory=original.chroma_persist_directory,
        log_level=original.log_level,
        llm_base_url="",
    )
    try:
        llm = get_llm()
        bound = llm.bind_tools(_TOOL_SCHEMAS)
        assert bound is not None
        assert config.settings.configured is True
    finally:
        config.settings = original
