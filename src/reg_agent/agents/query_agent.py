# src/reg_agent/agents/query_agent.py

import google.auth
import google.auth.transport.requests
import structlog
from pydantic import BaseModel, Field
from pydantic_ai import Agent

# --- Pydantic-AI Imports for explicit provider/model setup ---
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

# --- Config Imports ---
from reg_agent.config import BASE_URL, MODEL_NAME, log  # Import log from config

# Import the tools and their dependency class
from reg_agent.tools.duckdb_tool import (
    DuckDBToolDeps,
    ExploreMetadataInput,
    ExploreMetadataOutput,
    QueryMetadataInput,
    QueryMetadataOutput,
    explore_metadata,
    query_metadata,
)


# --- Agent Output Model (Optional) ---
# Define what structured output you expect from the agent's final response
# For now, let's assume it might return a summary or the raw result IDs
class QueryAgentResult(BaseModel):
    summary: str = Field(description="A summary of the findings or the direct answer.")
    retrieved_doc_ids: list[str] = Field(
        default_factory=list, description="List of relevant document UUIDs found."
    )
    # Add other fields as needed, e.g., error messages from the agent itself


# --- LLM Setup (Using config, similar to MetadataExtractionService) ---
log.info("Setting up LLM for QueryAgent...")

direct_adc_token: str | None = None
try:
    # Attempt to get direct ADC credentials and token
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    if not credentials.token:
        log.error("Failed to obtain access token from direct ADC.")
        raise ValueError("Could not get direct ADC access token.")
    direct_adc_token = credentials.token
    log.debug("Obtained direct ADC token for QueryAgent authentication.")
    auth_method = "Direct ADC"
except google.auth.exceptions.DefaultCredentialsError as cred_err:
    log.error(
        "Failed to find Application Default Credentials (ADC) for QueryAgent. "
        "Ensure authenticated (e.g., `gcloud auth application-default login`).",
        exc_info=True,
    )
    # Optionally raise an error or fall back to a default/mock LLM if desired
    raise RuntimeError("QueryAgent LLM setup failed due to missing ADC.") from cred_err
except Exception as adc_err:
    log.error("Failed during direct ADC token retrieval for QueryAgent", exc_info=True)
    raise RuntimeError("QueryAgent LLM setup failed during ADC setup") from adc_err

if not direct_adc_token:
    # This should ideally not be reached due to exceptions above, but as a safeguard:
    raise RuntimeError("Failed to obtain authentication token for QueryAgent LLM.")

log.info(
    "Initializing OpenAIProvider for QueryAgent with direct ADC token",
    base_url=BASE_URL,
)
provider = OpenAIProvider(
    base_url=BASE_URL,
    api_key=direct_adc_token,
    # TODO: Consider explicit timeouts/retries if needed
)

log.info("Initializing OpenAIModel for QueryAgent", model_name=MODEL_NAME)
llm = OpenAIModel(
    MODEL_NAME,
    provider=provider,
)

log.info("LLM setup complete for QueryAgent.")


# --- Agent Definition ---

# Define the agent, passing the configured LLM model instance AND the tools list
query_agent = Agent(
    model=llm,  # Pass the configured model instance
    deps_type=DuckDBToolDeps,  # The dependency class holding the repo
    tools=[explore_metadata, query_metadata],  # Pass tool functions directly
    # result_type=QueryAgentResult, # Optional: Enforce a structured final output
    system_prompt=(
        "You are an expert assistant specialized in querying a document database based on metadata. "
        "Your goal is to understand the user's request, identify relevant metadata filters, "
        "and use the provided tools to find matching documents. "
        "First, figure out the user's intent. If the query is vague (e.g., 'finance documents'), "
        "consider using the explore_metadata tool to see available fields or values for relevant fields (like 'topic' or 'year') "
        "before using the query_metadata tool. If the query is specific (e.g., 'documents by author X in year Y'), "
        "use the query_metadata tool directly. If a query yields too many results, suggest refinements to the user "
        "or try exploring metadata to find more specific criteria. "
        "If a query yields no results, inform the user and perhaps suggest exploring available metadata values. "
        "Always prioritize using the query_metadata tool once you have reasonably specific filters."
    ),
    # instrument=True # Optional: Enable Logfire instrumentation if configured
)

log.info("Query Agent initialized with DuckDB tools.")

# --- Example Usage Removed ---
# The example usage code block, including the async function
# and the if __name__ == "__main__" block, has been moved to
# scripts/run_query_agent.py
