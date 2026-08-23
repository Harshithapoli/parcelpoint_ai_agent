"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import dotenv_values, load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
_DOTENV_VALUES = dotenv_values(PROJECT_ROOT / ".env")


def _config_value(name: str, default: str = "") -> str:
    """Load config from environment, Streamlit secrets, or local .env."""

    # 1. Environment variables
    process_value = os.getenv(name)
    if process_value and process_value.strip():
        return process_value

    # 2. Streamlit Cloud secrets
    try:
        import streamlit as st

        secret_value = st.secrets.get(name)
        if secret_value is not None and str(secret_value).strip():
            return str(secret_value)
    except Exception:
        pass

    # 3. Local .env
    dotenv_value = _DOTENV_VALUES.get(name)
    if dotenv_value is not None and str(dotenv_value).strip():
        return str(dotenv_value)

    return default


@dataclass(frozen=True)
class Settings:
	"""Runtime settings for the ParcelPilot application."""

	llm_provider: str = _config_value("LLM_PROVIDER")
	llm_model: str = _config_value("LLM_MODEL")
	llm_api_key: str = _config_value("LLM_API_KEY")
	database_path: Path = PROJECT_ROOT / os.getenv(
		"DATABASE_PATH", "database/parcelpilot.db"
	)
	chroma_persist_directory: Path = PROJECT_ROOT / os.getenv(
		"CHROMA_PERSIST_DIRECTORY", "data/processed/chroma"
	)
	log_level: str = os.getenv("LOG_LEVEL", "INFO")
	llm_base_url: str = os.getenv("LLM_BASE_URL", "")

	@property
	def configured(self) -> bool:
		"""Whether all required LLM settings are present without exposing secrets."""
		return all(
			(
				self.llm_provider.strip(),
				self.llm_model.strip(),
				self.llm_api_key.strip(),
			)
		)


settings = Settings()


def get_llm():
	"""Construct the configured chat model, failing clearly when configuration is absent."""
	if not settings.configured:
		if not settings.llm_provider.strip():
			raise RuntimeError(
				"LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY before running the agent."
			)
		if not settings.llm_model.strip():
			raise RuntimeError("LLM_MODEL must be configured before running the agent.")
		if not settings.llm_api_key.strip():
			raise RuntimeError("LLM_API_KEY must be configured before running the agent.")

	provider = settings.llm_provider.strip().lower()

	try:
		if provider == "openai":
			from langchain_openai import ChatOpenAI

			kwargs = {"model": settings.llm_model, "api_key": settings.llm_api_key}
			if settings.llm_base_url:
				kwargs["base_url"] = settings.llm_base_url
			return ChatOpenAI(**kwargs)
		if provider in {"gemini", "google_genai", "google-generative-ai"}:
			from langchain_google_genai import ChatGoogleGenerativeAI

			return ChatGoogleGenerativeAI(
				model=settings.llm_model,
				google_api_key=settings.llm_api_key,
			)
		if provider == "anthropic":
			from langchain_anthropic import ChatAnthropic

			return ChatAnthropic(model=settings.llm_model, api_key=settings.llm_api_key)
	except ImportError as exc:
		raise RuntimeError(
			f"LLM provider '{provider}' is unavailable. Install its LangChain integration."
		) from exc

	raise RuntimeError(
		f"Unsupported LLM_PROVIDER '{provider}'. Supported providers are gemini, openai, and anthropic."
	)
