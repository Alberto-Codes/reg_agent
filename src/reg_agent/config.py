# src/reg_agent/config.py
import os
import structlog
from dotenv import load_dotenv

# --- Configuration Loading ---
load_dotenv()  # Load environment variables from .env file
log = structlog.get_logger()


def _get_required_env_var(var_name: str) -> str:
    """Gets an environment variable, raising an error if it's not set."""
    value = os.getenv(var_name)
    if not value:
        log.error(f"{var_name} environment variable is required but not set.")
        raise ValueError(f"{var_name} must be set via environment variable.")
    return value


def _get_vertex_model_name() -> str:
    """Gets the Vertex AI model name, ensuring the 'google/' prefix."""
    raw_name = os.getenv("VERTEX_MODEL_NAME", "google/gemini-1.5-flash-latest")
    if not raw_name:
        # Handle case where env var is explicitly set to empty string
        log.warning("VERTEX_MODEL_NAME is empty, using default.")
        raw_name = "google/gemini-1.5-flash-latest"

    if "/" not in raw_name:  # Simpler check if prefix is missing
        log.warning(
            "VERTEX_MODEL_NAME potentially missing publisher prefix. Assuming 'google/'.",
            raw_name=raw_name,
        )
        return f"google/{raw_name}"
    # Consider adding check if prefix is other than 'google/' if needed
    return raw_name


# --- Exported Configuration Constants ---
MODEL_NAME: str = _get_vertex_model_name()
BASE_URL: str = _get_required_env_var("VERTEX_OPENAI_ENDPOINT_URL")
# Optional target SA name or email for impersonation
TARGET_SA_NAME_OR_EMAIL: str | None = os.getenv("TARGET_SA_NAME_OR_EMAIL")
