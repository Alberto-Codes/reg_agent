# src/reg_agent/services/metadata_service.py
import structlog
import asyncio
import os
import logging
import google.auth
import google.auth.transport.requests
from pydantic import BaseModel, Field
from typing import Type, Optional, cast
import httpx

# For __main__ testing - load environment variables if available
from dotenv import load_dotenv

# --- Switch imports for OpenAI compatibility ---
from pydantic_ai.agent import Agent
# Use OpenAIModel and OpenAIProvider now
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

# --- Configuration Loading ---
load_dotenv()
log = structlog.get_logger()

# Model name needs publisher prefix (e.g., "google/gemini-1.5-flash-latest")
_raw_model_name = os.getenv("VERTEX_MODEL_NAME", 'google/gemini-1.5-flash-latest') # Updated default
if not _raw_model_name.startswith("google/"):
    log.warning(
        "VERTEX_MODEL_NAME provided without 'google/' prefix. Prepending.",
        raw_name=_raw_model_name
    )
    MODEL_NAME = f"google/{_raw_model_name}"
else:
    MODEL_NAME = _raw_model_name

# Base URL for the Vertex OpenAI-compatible endpoint is now required
BASE_URL = os.getenv("VERTEX_OPENAI_ENDPOINT_URL")
# API Key is no longer used directly for authentication
# API_KEY = os.getenv("VERTEX_API_KEY", "None") # Default to string "None" as placeholder

if not MODEL_NAME:
    # This is a critical configuration, raise error if missing
    log.error("VERTEX_MODEL_NAME environment variable is required but not set.")
    raise ValueError("VERTEX_MODEL_NAME must be set via environment variable.")
if not BASE_URL:
    log.error("VERTEX_OPENAI_ENDPOINT_URL environment variable is required but not set.")
    raise ValueError("VERTEX_OPENAI_ENDPOINT_URL must be set via environment variable.")


# --- Response Model ---
class BaseMetadata(BaseModel):
    """Basic placeholder for extracted metadata."""

    summary: str = Field(..., description="A brief summary of the document.")
    extracted_ok: bool = Field(
        ..., description="Flag indicating if extraction was successful."
    )


# --- Service Definition ---
class MetadataExtractionService:
    """
    Service using pydantic-ai and Vertex AI Gemini via its OpenAI-compatible endpoint.
    Reads configuration from environment variables at module load time.
    Uses Google Application Default Credentials (ADC) for authentication.
    """

    def __init__(self, output_type: Type[BaseModel] = BaseMetadata):
        """Initializes the pydantic-ai Agent using OpenAI-compatible settings."""
        self.output_type = output_type
        log.info(
            "Initializing MetadataExtractionService for OpenAI-compatible endpoint",
            model=MODEL_NAME,
            base_url=BASE_URL,
            auth_method="ADC", # Indicate ADC is being used
            output_type=self.output_type.__name__,
        )
        try:
            # --- Start Authentication Logic ---
            # Get application default credentials
            credentials, project_id = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            # Create a transport request object
            auth_req = google.auth.transport.requests.Request()
            # Refresh credentials to get the access token
            credentials.refresh(auth_req)

            if not credentials.token:
                log.error("Failed to obtain access token from credentials.")
                raise ValueError("Could not get ADC access token.")

            log.debug("Obtained ADC token for authentication.")

            # --- End Authentication Logic ---

            # Instantiate OpenAIProvider passing ADC token as api_key
            provider = OpenAIProvider(
                api_key=credentials.token, # Pass ADC token as the API key
                base_url=BASE_URL, # Keep base_url explicit
                # http_client=http_client, # Remove client
            )
            # Use OpenAIModel with the specific Gemini model name and the provider
            llm = OpenAIModel(
                MODEL_NAME,  # Pass model name as positional argument
                provider=provider,
            )
            # Agent uses the specified llm and expects output matching output_type
            self.agent = Agent(model=llm, output_type=self.output_type)
            log.info("Agent initialized successfully for OpenAI-compatible endpoint.")
        except google.auth.exceptions.DefaultCredentialsError as cred_err:
            log.error(
                "Failed to find Application Default Credentials (ADC). "
                "Ensure you are authenticated (e.g., `gcloud auth application-default login`).",
                exc_info=True
            )
            raise RuntimeError("MetadataExtractionService initialization failed due to missing ADC.") from cred_err
        except Exception as e:
            log.error("Failed to initialize pydantic-ai agent", exc_info=True)
            raise RuntimeError("MetadataExtractionService initialization failed") from e

    async def extract_metadata(self, text: str) -> Optional[BaseModel]:
        """Extracts structured metadata from text using the configured agent."""
        if not text:
            log.warning("Cannot extract metadata from empty text.")
            return None

        log.debug("Attempting metadata extraction", text_length=len(text))
        # Simple prompt asking for the defined output structure
        prompt = f"Extract metadata from the following text:\n\n---\n{text}\n---"

        try:
            # The agent handles structuring the output based on self.output_type
            run_result = await self.agent.run(prompt)
            result = (
                run_result.output
            )  # Extract the BaseMetadata (or specified type) instance
            log.info(
                "Metadata extraction successful.", output_type=type(result).__name__
            )
            return result
        except Exception as e:
            log.error("Metadata extraction failed", error=str(e), exc_info=True)
            return None


# --- Test Runner ---
async def main_test():
    """Basic test function to run the service."""
    log.info("Starting metadata service test (OpenAI-compatible endpoint)...")
    try:
        # Initialize using global config, default output type
        service = MetadataExtractionService()
    except Exception as e:
        log.error("Failed to initialize service for testing.", error=str(e))
        return

    sample_text = "This is a simple test document about cloud computing and AI via OpenAI endpoint."
    log.info("Running extraction test...", sample_text=sample_text)
    metadata_result = await service.extract_metadata(sample_text)

    if metadata_result:
        log.info(
            "Test extraction successful:",
            result=metadata_result.model_dump_json(indent=2),
        )
    else:
        log.error("Test extraction failed.")


if __name__ == "__main__":
    # Basic logging setup for direct execution
    # Ensures logger is configured only once if script is reloaded
    root_logger = logging.getLogger()
    if not root_logger.hasHandlers():
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer()
        )
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)  # Set default level
    # Ensure level is set even if handlers existed
    root_logger.setLevel(logging.INFO)

    asyncio.run(main_test())
