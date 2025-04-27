# src/reg_agent/config.py
import os
import sys
import logging
import structlog
from structlog.typing import Processor # Import Processor type
from dotenv import load_dotenv

# --- Configuration Loading ---
load_dotenv()  # Load environment variables from .env file

# --- Logging Configuration ---

# Define processors for structlog
shared_processors: list[Processor] = [ # Add type hint
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    # Add context variables automatically (useful for request IDs, etc.)
    structlog.contextvars.merge_contextvars,
]

structlog.configure(
    processors=shared_processors + [
        # Prepare event dict for standard library formatter
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Configure the standard library logging handler
handler = logging.StreamHandler(sys.stdout) # Log to stdout

# Use structlog's ProcessorFormatter to format records for the handler
formatter = structlog.stdlib.ProcessorFormatter(
    # The foreign_pre_chain is used for messages not originating from structlog
    foreign_pre_chain=shared_processors,
    # Define the final formatting step (e.g., ConsoleRenderer for dev)
    # Keep ConsoleRenderer here for pretty output
    processor=structlog.dev.ConsoleRenderer(),
)

handler.setFormatter(formatter)

# Get the root logger and add the handler
root_logger = logging.getLogger()
root_logger.addHandler(handler)
root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

# Suppress overly verbose loggers if needed (e.g., from libraries)
# logging.getLogger("some_noisy_library").setLevel(logging.WARNING)

log = structlog.get_logger() # Get the configured logger


def _get_required_env_var(var_name: str) -> str:
    """Gets an environment variable, raising an error if it's not set."""
    value = os.getenv(var_name)
    if not value:
        # Use the configured logger
        log.error("Missing required environment variable", variable_name=var_name)
        raise ValueError(f"{var_name} must be set via environment variable.")
    return value


def _get_vertex_model_name() -> str:
    """Gets the Vertex AI model name, ensuring the 'google/' prefix."""
    raw_name = os.getenv("VERTEX_MODEL_NAME", "google/gemini-1.5-flash-latest")
    if not raw_name:
        # Handle case where env var is explicitly set to empty string
        log.warning("VERTEX_MODEL_NAME is empty, using default.", default_name="google/gemini-1.5-flash-latest")
        raw_name = "google/gemini-1.5-flash-latest"

    if "/" not in raw_name:  # Simpler check if prefix is missing
        log.warning(
            "VERTEX_MODEL_NAME potentially missing publisher prefix. Assuming 'google/'.",
            raw_name=raw_name,
            assumed_prefix="google/"
        )
        return f"google/{raw_name}"
    # Consider adding check if prefix is other than 'google/' if needed
    log.debug("Using Vertex AI model name", model_name=raw_name)
    return raw_name


# --- Exported Configuration Constants ---
MODEL_NAME: str = _get_vertex_model_name()
BASE_URL: str = _get_required_env_var("VERTEX_OPENAI_ENDPOINT_URL")
# Optional target SA name or email for impersonation
TARGET_SA_NAME_OR_EMAIL: str | None = os.getenv("TARGET_SA_NAME_OR_EMAIL")

log.info(
    "Configuration loaded",
    model_name=MODEL_NAME,
    base_url=BASE_URL,
    target_sa=TARGET_SA_NAME_OR_EMAIL if TARGET_SA_NAME_OR_EMAIL else "(Direct ADC)",
    log_level=logging.getLevelName(root_logger.level) # Corrected function call
)


if __name__ == "__main__": # pragma: no cover
    # Example of how to access and print the loaded config
    print(f"Model Name: {MODEL_NAME}")
    print(f"Base URL: {BASE_URL}")
    print(f"Target SA: {TARGET_SA_NAME_OR_EMAIL or '(Direct ADC)'}")
    print(f"Log Level: {logging.getLevelName(root_logger.level)}")
