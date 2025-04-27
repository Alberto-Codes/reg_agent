# src/reg_agent/agents/query_agent.py

import os
import google.auth
import google.auth.transport.requests
import httpx
import structlog
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
import logfire

from reg_agent.config import BASE_URL, MODEL_NAME, log
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


# --- Agent Creation Function ---
def create_query_agent() -> Agent[DuckDBToolDeps, str]:
    """Sets up dependencies and creates the QueryAgent instance."""
    log.info("Creating QueryAgent instance...")

    # --- Logfire Conditional Setup ---
    instrument_flag = False
    enable_logfire_env = os.environ.get("ENABLE_LOGFIRE", "false").lower()
    log.debug("Read ENABLE_LOGFIRE environment variable", value=enable_logfire_env)
    if enable_logfire_env == "true":
        log.info("ENABLE_LOGFIRE is true, attempting to configure Logfire...")
        try:
            # Minimal configuration, adjust as needed (e.g., add service_name)
            logfire.configure()
            # Instrument HTTPX if making external LLM calls, etc.
            # logfire.instrument_httpx(capture_all=True)
            instrument_flag = True
            log.info("Logfire instrumentation enabled.")
        except Exception as e:
            # Log error but don't prevent agent creation
            log.error("Failed to configure Logfire, disabling instrumentation.", error=e, exc_info=True)
            instrument_flag = False
    else:
        log.info("Logfire instrumentation disabled (ENABLE_LOGFIRE not 'true').")

    # --- LLM Setup (Using config, similar to MetadataExtractionService) ---
    log.info("Setting up LLM for QueryAgent...")
    direct_adc_token: str | None = None
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
        log.debug("Obtained direct ADC token for QueryAgent authentication.")
    except google.auth.exceptions.DefaultCredentialsError as cred_err:
        log.error(
            "Failed to find Application Default Credentials (ADC) for QueryAgent. "
            "Ensure authenticated (e.g., `gcloud auth application-default login`).",
            exc_info=True,
        )
        raise RuntimeError(
            "QueryAgent LLM setup failed due to missing ADC."
        ) from cred_err
    except Exception as adc_err:
        log.error(
            "Failed during direct ADC token retrieval for QueryAgent", exc_info=True
        )
        raise RuntimeError("QueryAgent LLM setup failed during ADC setup") from adc_err

    if not direct_adc_token:
        raise RuntimeError("Failed to obtain authentication token for QueryAgent LLM.")

    log.info(
        "Initializing OpenAIProvider for QueryAgent with direct ADC token",
        base_url=BASE_URL,
    )
    provider = OpenAIProvider(base_url=BASE_URL, api_key=direct_adc_token)

    log.info("Initializing OpenAIModel for QueryAgent", model_name=MODEL_NAME)
    llm = OpenAIModel(MODEL_NAME, provider=provider)
    log.info("LLM setup complete for QueryAgent.")

    # --- Agent Definition ---
    agent = Agent(
        model=llm,
        deps_type=DuckDBToolDeps,
        tools=[explore_metadata, query_metadata],
        instructions=(
            "You are an expert assistant specialized in querying a document database via its metadata.\n"\
            "Your primary goal is to translate the user\'s natural language request into an effective query using the available tools.\n\n"\
            "**Workflow:**\n"\
            "1.  **Analyze Intent:** Carefully determine the user\'s objective and the key concepts or entities they are asking about.\n"\
            "2.  **Assess Specificity:**\n"\
            "    *   **Specific Query:** If the user provides clear metadata fields and values (e.g., \'issuing_agency=CFPB\', \'document_type=Consent Order\'), proceed directly to step 4.\n"\
            "    *   **Ambiguous Query:** If the query is broad, conceptual, or lacks specific filters (e.g., \'Tell me about Wells Fargo cases\', \'Find documents on sales practices\'), proceed to step 3.\n"\
            "3.  **Explore (if ambiguous):**\n"\
            "    *   Use the `explore_metadata` tool. Start by exploring the available *fields* to understand the search possibilities.\n"\
            "    *   Based on the user\'s query and the available fields, identify potentially relevant fields (e.g., for \'Wells Fargo cases\', explore values for \'subject_institution\', \'key_topics\').\n"\
            "    *   Use `explore_metadata` again to get distinct *values* for those 1-2 most relevant fields to discover specific terms (e.g., find \'Wells Fargo Bank, N.A.\' is a value for \'subject_institution\').\n"\
            "4.  **Query:**\n"\
            "    *   Construct the best possible `query_metadata` call using the specific filters identified either directly from the user\'s request or discovered through exploration.\n"\
            "    *   Prioritize using exact matches found via exploration (e.g., use `subject_institution=\'Wells Fargo Bank, N.A.\'` instead of just \'Wells Fargo\').\n"\
            "5.  **Refine (if necessary):**\n"\
            "    *   **Too Many Results:** If `query_metadata` returns too many document IDs (e.g., > 10), analyze the results. Inform the user you found many results and suggest adding filters based on other relevant fields discovered during exploration (e.g., \'I found N documents about Wells Fargo. You could filter by key_topics like \\'Sales Practices\\' or \\'Mortgages\\'.\'). Alternatively, you might attempt a refined query yourself if the context strongly suggests a specific refinement.\n"\
            "    *   **No Results:** If `query_metadata` returns no results, inform the user. You could suggest broadening the search slightly or exploring values for a different field.\n\n"\
            "**Tool Usage Guidance:**\n"\
            "*   Use `explore_metadata` primarily to discover *options* (available fields and specific values) when the user\'s query isn\'t precise enough for `query_metadata`.\n"\
            "*   Use `query_metadata` as the primary tool to retrieve document IDs once you have formulated specific filter criteria.\n"\
            "*   Return a clear summary of your findings or actions to the user."
        ),
        instrument=instrument_flag,
    )
    log.info("Query Agent created successfully.", instrumentation_enabled=instrument_flag)
    return agent


# --- Module Level Instance ---
# Create the agent instance when the module is imported
query_agent = create_query_agent()

# --- Example Usage Removed ---
# The example usage code block, including the async function
# and the if __name__ == "__main__" block, has been moved to
# scripts/run_query_agent.py
