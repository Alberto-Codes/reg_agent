# src/reg_agent/services/metadata_service.py
from typing import Optional, Type

import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
import httpx
from pydantic import BaseModel

# --- Pydantic-AI Imports ---
from pydantic_ai.agent import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from reg_agent.auth.http_auth import (
    DynamicBearerAuth,  # type: ignore[import-not-found] # Import from new location
)

# --- Internal Imports ---
from reg_agent.auth.token_manager import (
    ImpersonatedTokenManager,  # type: ignore[import-not-found]
)
from reg_agent.config import (
    BASE_URL,
    MODEL_NAME,
    TARGET_SA_NAME_OR_EMAIL,
    log,
)  # Remove unused type: ignore
from reg_agent.schemas.metadata import (
    RegulationDocumentMetadata,  # type: ignore[import-not-found] # Import schema
)

# --- Constants --- #
# Define longer timeouts and more retries
REQUEST_TIMEOUT_SECONDS = 180.0
CONNECT_TIMEOUT_SECONDS = 20.0  # Keep connect timeout reasonable
MAX_RETRIES = 3


# --- Service Definition ---
class MetadataExtractionService:
    """
    Service using pydantic-ai and Vertex AI Gemini via its OpenAI-compatible endpoint.
    Reads configuration from environment variables via config module.
    Supports direct ADC or impersonated ADC via TARGET_SA_NAME_OR_EMAIL.
    """

    def __init__(self, output_type: Type[BaseModel] = RegulationDocumentMetadata):
        """Initializes the pydantic-ai Agent using OpenAI-compatible settings."""
        self.output_type = output_type
        self.token_manager: Optional[ImpersonatedTokenManager] = None
        self.http_client: Optional[httpx.AsyncClient] = None

        auth_method = "Direct ADC"
        direct_adc_token: Optional[str] = None
        timeout_config = httpx.Timeout(
            REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
        )
        log.info("Configured HTTP timeout", timeout=timeout_config)

        if TARGET_SA_NAME_OR_EMAIL:  # Use imported config constant
            log.info("Impersonation requested", target_sa_input=TARGET_SA_NAME_OR_EMAIL)
            auth_method = f"Impersonated ADC (Target Input: {TARGET_SA_NAME_OR_EMAIL})"
            try:
                self.token_manager = ImpersonatedTokenManager(
                    target_service_account_name_or_email=TARGET_SA_NAME_OR_EMAIL
                )
                log.info(
                    "Token Manager targeting resolved SA",
                    target_sa_email=self.token_manager.target_service_account,
                )
                auth_method = f"Impersonated ADC (Target: {self.token_manager.target_service_account})"
                # Create AsyncClient with custom timeout and auth
                self.http_client = httpx.AsyncClient(
                    auth=DynamicBearerAuth(self.token_manager),  # Use imported class
                    timeout=timeout_config,  # Apply custom timeout
                )
                log.info(
                    "Using httpx.AsyncClient with dynamic token for impersonation",
                    timeout_config=str(timeout_config),
                )
            except Exception as tm_err:
                log.error(
                    "Failed to initialize ImpersonatedTokenManager", exc_info=True
                )
                raise RuntimeError(
                    "MetadataExtractionService initialization failed during token manager setup"
                ) from tm_err
        else:
            log.info("Using direct ADC authentication.")
            try:
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_req = google.auth.transport.requests.Request()
                credentials.refresh(auth_req)
                if not credentials.token:
                    log.error("Failed to obtain access token from direct ADC.")
                    raise ValueError("Could not get direct ADC access token.")
                direct_adc_token = credentials.token
                log.debug("Obtained direct ADC token for authentication.")
            except google.auth.exceptions.DefaultCredentialsError as cred_err:
                log.error(
                    "Failed to find Application Default Credentials (ADC). "
                    "Ensure you are authenticated (e.g., `gcloud auth application-default login`).",
                    exc_info=True,
                )
                raise RuntimeError(
                    "MetadataExtractionService initialization failed due to missing ADC."
                ) from cred_err
            except Exception as adc_err:
                log.error("Failed during direct ADC token retrieval", exc_info=True)
                raise RuntimeError(
                    "MetadataExtractionService initialization failed during ADC setup"
                ) from adc_err

        log.info(
            "Initializing MetadataExtractionService Provider/Model",
            model=MODEL_NAME,
            base_url=BASE_URL,
            auth_method=auth_method,
            output_type=self.output_type.__name__,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
        )

        try:
            # Initialize provider differently based on auth method
            if self.http_client:
                # Pass base_url and the custom async client directly
                log.info(
                    "Initializing OpenAIProvider with custom httpx.AsyncClient",
                    base_url=BASE_URL,
                    timeout_config=str(self.http_client.timeout),
                )
                provider = OpenAIProvider(
                    base_url=BASE_URL,
                    http_client=self.http_client,
                    # Timeout/retries are now handled by the http_client
                )
            elif direct_adc_token:
                # Pass base_url and ADC token as api_key
                log.info(
                    "Initializing OpenAIProvider with direct ADC token",
                    base_url=BASE_URL,
                )
                provider = OpenAIProvider(
                    base_url=BASE_URL,
                    api_key=direct_adc_token,
                    # Rely on OpenAIModel/library defaults for timeout/retries here
                )
            else:
                log.error(
                    "Invalid state: Neither http_client nor direct_adc_token available for OpenAIProvider."
                )
                raise RuntimeError(
                    "Failed to determine authentication method for OpenAIProvider."
                )

            # Remove model_settings, rely on provider/client settings
            llm = OpenAIModel(
                MODEL_NAME,
                provider=provider,
            )
            self.agent = Agent(model=llm, output_type=self.output_type)
            log.info("Agent initialized successfully.")
        except Exception as e:
            log.error("Failed to initialize pydantic-ai agent", exc_info=True)
            if self.http_client:
                try:
                    log.warning(
                        "Need to ensure http_client is closed cleanly on init error."
                    )
                except Exception as close_err:
                    log.error(
                        "Error trying to close client during init failure",
                        nested_error=str(close_err),
                    )
            raise RuntimeError("MetadataExtractionService initialization failed") from e

    async def extract_metadata(self, text: str) -> Optional[BaseModel]:
        """Extracts structured metadata from text using the configured agent."""
        if not text:
            log.warning("Cannot extract metadata from empty text.")
            return None

        log.debug("Attempting metadata extraction", text_length=len(text))
        # Prompt remains the same here
        prompt = f"""Analyze the following regulatory document text and extract structured metadata according to the requested format.
Focus on identifying key details like document type, issuing agency, subject institution, document identifier, key topics, action items, and a summary.

IMPORTANT: You MUST provide a value for ALL fields defined in the requested format.
- If the information for a string field (like 'document_type', 'issuing_agency', 'subject_institution', 'document_identifier') cannot be clearly determined from the text, return the string value 'N/A' for that field. Do NOT omit the field.
- For list fields (like 'key_topics', 'action_items'), return an empty list [] if no relevant items are found. Do NOT omit the field.
- The 'summary' field must always contain a concise summary.

Document Text:
---
{text}
---

Respond ONLY with the structured data requested, ensuring all defined fields are present in the output."""

        try:
            run_result = await self.agent.run(prompt)
            result = (
                run_result.output
            )  # Extract the RegulationDocumentMetadata (or specified type) instance
            log.info(
                "Metadata extraction successful.", output_type=type(result).__name__
            )
            return result
        except Exception as e:
            log.error("Metadata extraction failed", error=str(e), exc_info=True)
            # Consider logging specific error types differently if needed
            # e.g., differentiate APIConnectionError from validation errors
            return None

    async def close(self):
        if self.http_client:
            log.info("Closing custom httpx client.")
            await self.http_client.aclose()
            self.http_client = None


# Remove main_test function and __main__ block (moved to scripts/test_metadata_service.py)
