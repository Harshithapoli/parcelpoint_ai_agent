"""Minimal Phase 2 entry point."""

from src.config import settings


def main() -> None:
	"""Report that the configuration layer can be loaded."""
	print(
		"ParcelPilot AI Agent configuration loaded "
		f"(provider={settings.llm_provider or 'not configured'})."
	)


if __name__ == "__main__":
	main()
