# src/reg_agent/services/metadata_service.py
import asyncio
import logging
import os
from typing import Optional, Type, List

import google.auth
import google.auth.transport.requests
import httpx
import structlog

# For __main__ testing - load environment variables if available
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# --- Switch imports for OpenAI compatibility ---
from pydantic_ai.agent import Agent

# Use OpenAIModel and OpenAIProvider now
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

# --- Custom Auth ---
from reg_agent.auth.token_manager import ImpersonatedTokenManager

# --- Configuration Loading ---
load_dotenv()
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
    if "/" not in raw_name:  # Simpler check if prefix is missing
        log.warning(
            "VERTEX_MODEL_NAME potentially missing publisher prefix. Assuming 'google/'.",
            raw_name=raw_name,
        )
        return f"google/{raw_name}"
    # Consider adding check if prefix is other than 'google/' if needed
    return raw_name


MODEL_NAME = _get_vertex_model_name()
BASE_URL = _get_required_env_var("VERTEX_OPENAI_ENDPOINT_URL")
# Updated: Optional target SA name or email for impersonation
TARGET_SA_NAME_OR_EMAIL = os.getenv("TARGET_SA_NAME_OR_EMAIL")


# --- Dynamic Bearer Token Authentication for httpx ---
class DynamicBearerAuth(httpx.Auth):
    """Custom httpx Auth class to fetch a token dynamically before requests."""

    def __init__(self, token_manager: ImpersonatedTokenManager):
        self._token_manager = token_manager

    def auth_flow(self, request: httpx.Request):
        token = self._token_manager.get_token()  # Get fresh token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


# --- Response Models ---
# Removed ActionItem class as it's being simplified to List[str]
# class ActionItem(BaseModel):
#     """Represents a required action or remediation item identified in the document."""
#
#     description: str = Field(..., description="Description of the required action.")
#     # Future fields like due_date, status, etc. can be added later.


class RegulationDocumentMetadata(BaseModel):
    """
    Structured metadata extracted from regulatory documents like Consent Orders or Letters.
    Designed for flexibility in the MVP stage.
    All fields are required. Return 'N/A' for missing string fields and [] for missing list fields.
    """

    document_type: str = Field(
        description="Inferred type of document (e.g., 'Consent Order', 'Supervisory Letter', 'Examination Report'). Return 'N/A' if not found.",
    )
    issuing_agency: str = Field(
        description="Name of the federal agency issuing the document (e.g., OCC, FRB, CFPB, FDIC). Return 'N/A' if not found.",
    )
    subject_institution: str = Field(
        description="Name of the bank or financial institution subject to the document. Return 'N/A' if not found.",
    )
    document_identifier: str = Field(
        description="Official identifier or number for the document, if available (e.g., Order number). Return 'N/A' if not found.",
    )
    key_topics: List[str] = Field(
        default_factory=list,
        description="List of key topics, regulations, or areas of concern mentioned (e.g., BSA/AML, IT Security, Fair Lending, UDAAP). Extract the most relevant terms. Return [] if none found.",
    )
    summary: str = Field(
        ...,
        description="A concise summary of the document's purpose and main points, capturing the essence of the regulatory action or communication.",
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="List of strings, where each string is a specific, discrete action or remediation step required by the institution, if explicitly mentioned. Return [] if none found.",
    )
    # Future: Add fields for related documents, severity rating, etc.

    # We can remove extracted_ok as the successful return implies it was ok.
    # extracted_ok: bool = Field(
    #     True, description="Flag indicating if the LLM believes extraction was successful."
    # )


# --- Service Definition ---
class MetadataExtractionService:
    """
    Service using pydantic-ai and Vertex AI Gemini via its OpenAI-compatible endpoint.
    Reads configuration from environment variables at module load time.
    Supports direct ADC or impersonated ADC via TARGET_SA_NAME_OR_EMAIL.
    """

    def __init__(self, output_type: Type[BaseModel] = RegulationDocumentMetadata):
        """Initializes the pydantic-ai Agent using OpenAI-compatible settings."""
        self.output_type = output_type
        self.token_manager: Optional[ImpersonatedTokenManager] = None
        self.http_client: Optional[httpx.AsyncClient] = None

        auth_method = "Direct ADC"
        # Remove provider_kwargs dictionary
        direct_adc_token: Optional[str] = None  # Store direct token here if needed

        if TARGET_SA_NAME_OR_EMAIL:  # Updated check
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
                # Create httpx client directly
                self.http_client = httpx.AsyncClient(
                    auth=DynamicBearerAuth(self.token_manager)
                )
                # No api_key needed when using custom client with auth
                log.info("Using httpx client with dynamic token for impersonation.")
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
                # --- Original Direct ADC Logic --- #
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_req = google.auth.transport.requests.Request()
                credentials.refresh(auth_req)
                if not credentials.token:
                    log.error("Failed to obtain access token from direct ADC.")
                    raise ValueError("Could not get direct ADC access token.")
                # Store the token directly
                direct_adc_token = credentials.token
                log.debug("Obtained direct ADC token for authentication.")
                # --- End Direct ADC Logic --- #
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
            "Initializing MetadataExtractionService",
            model=MODEL_NAME,
            base_url=BASE_URL,
            auth_method=auth_method,
            output_type=self.output_type.__name__,
        )

        try:
            # Instantiate OpenAIProvider explicitly based on auth method
            if self.http_client:  # Impersonation mode
                provider = OpenAIProvider(
                    base_url=BASE_URL,
                    http_client=self.http_client,  # Pass client explicitly
                )
            elif direct_adc_token:  # Direct ADC mode
                provider = OpenAIProvider(
                    base_url=BASE_URL,
                    api_key=direct_adc_token,  # Pass api_key explicitly
                )
            else:
                # This case should ideally not happen if logic above is correct
                log.error(
                    "Invalid state: Neither http_client nor direct_adc_token available for OpenAIProvider."
                )
                raise RuntimeError(
                    "Failed to determine authentication method for OpenAIProvider."
                )

            # Use OpenAIModel with the specific Gemini model name and the provider
            llm = OpenAIModel(
                MODEL_NAME,  # Pass model name as positional argument
                provider=provider,
            )
            # Agent uses the specified llm and expects output matching output_type
            self.agent = Agent(model=llm, output_type=self.output_type)
            log.info("Agent initialized successfully.")
        except Exception as e:
            log.error("Failed to initialize pydantic-ai agent", exc_info=True)
            # Clean up httpx client if created
            if self.http_client:
                # Ensure the cleanup task is awaited or handled properly
                # Depending on context, running it directly might be simpler if __init__ isn't async
                try:
                    # Attempt synchronous close if possible, or handle async appropriately
                    # For now, log and rely on test runner's finally block
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
        # Updated prompt asking for the new, more detailed structure AND specific handling for missing required fields
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
            # The agent handles structuring the output based on self.output_type
            # If using impersonation, the httpx client will fetch a token via DynamicBearerAuth
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
            return None

    # Add an explicit close method if using impersonation to close httpx client
    async def close(self):
        if self.http_client:
            log.info("Closing custom httpx client.")
            await self.http_client.aclose()
            self.http_client = None


# --- Test Runner ---
async def main_test():
    """Basic test function to run the service."""
    log.info("Starting metadata service test...")
    service = None  # Initialize service to None for finally block
    try:
        # Initialize using global config, default output type (now RegulationDocumentMetadata)
        service = MetadataExtractionService()

        # Sample text simulating a Consent Order snippet
        sample_text = """
        UNITED STATES OF AMERICA
        DEPARTMENT OF THE TREASURY
        OFFICE OF THE COMPTROLLER OF THE CURRENCY

        In the Matter of:
        Example Bank, N.A.
        City, State

        AA-EC-2024-123

        CONSENT ORDER

        The Office of the Comptroller of the Currency of the United States of America ("OCC"),
        through its authorized representative, has supervisory authority over Example Bank, N.A., City, State ("Bank").

        The OCC has found unsafe or unsound practices relating to the Bank's Bank Secrecy Act/Anti-Money Laundering ("BSA/AML") compliance program...

        NOW, THEREFORE, the Bank, by and through its duly elected and acting Board of Directors ("Board"), hereby stipulates and consents to the following:

        ARTICLE III
        BSA/AML COMPLIANCE PROGRAM
        (1) Within 90 days, the Board shall submit to the Assistant Deputy Comptroller a revised, acceptable written BSA/AML program for the Bank.
        (2) The program shall ensure adequate staffing and resources for BSA compliance.

        ARTICLE X
        CIVIL MONEY PENALTY
        (1) The Bank shall pay a civil money penalty of $2,500,000.

        Effective Date: April 27, 2025
        """
        log.info("Running extraction test...", text_snippet=sample_text[:200] + "...")
        metadata_result = await service.extract_metadata(sample_text)

        if metadata_result:
            # Log the full model dump, which will now be RegulationDocumentMetadata
            log.info(
                "Test extraction successful:",
                result=metadata_result.model_dump_json(indent=2),
            )
        else:
            log.error("Test extraction failed.")

    except Exception as e:
        log.error("Test run failed.", error=str(e), exc_info=True)
    finally:
        # Ensure client is closed if service was initialized
        if service and hasattr(service, "close"):
            await service.close()


if __name__ == "__main__":
    # Configure structlog for basic console output when run directly
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
        # Use ConsoleRenderer for prettier output
        processor=structlog.dev.ConsoleRenderer(),
        # foreign_pre_chain tells ProcessorFormatter to add its own processors
        # before the ConsoleRenderer, ensuring timestamps etc. are included.
        foreign_pre_chain=[
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.PATHNAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    # Clear existing handlers to avoid duplication if script is reloaded
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    log.info("Running metadata service in standalone test mode.")
    asyncio.run(main_test())
