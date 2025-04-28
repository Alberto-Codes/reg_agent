# src/reg_agent/agents/query_agent.py

import os
import uuid
from typing import List, Optional

import google.auth
import google.auth.transport.requests
import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from reg_agent.config import BASE_URL, MODEL_NAME, log
from reg_agent.tools.duckdb_tool import (
    DuckDBToolDeps,
    explore_metadata,
    query_metadata,
    count_documents,
)


# --- Agent Output Model (Optional) ---
# Define what structured output you expect from the agent's final response
# For now, let's assume it might return a summary or the raw result IDs
class QueryAgentResult(BaseModel):
    summary: str = Field(
        description="A summary of the findings, actions taken, or the direct answer. Explain if IDs are returned or if refinement is needed."
    )
    retrieved_doc_ids: Optional[List[uuid.UUID]] = Field(
        default=None,
        description="List of relevant document UUIDs found (max 10). None if >10 results or 0 results.",
    )
    # Add other fields as needed, e.g., error messages from the agent itself


# --- Agent Creation Function ---
# Restore original return type hint
def create_query_agent(
    llm: OpenAIModel | None = None,
) -> Agent[DuckDBToolDeps, QueryAgentResult | str]:  # Allow string for now
    """Sets up dependencies and creates the QueryAgent instance.

    Args:
        llm: An optional pre-initialized LLM instance (e.g., TestModel for testing).
             If None, a new LLM instance will be created based on config.

    Returns:
        An initialized Agent instance.
    """
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
            log.error(
                "Failed to configure Logfire, disabling instrumentation.",
                error=e,
                exc_info=True,
            )
            instrument_flag = False
    else:
        log.info("Logfire instrumentation disabled (ENABLE_LOGFIRE not 'true').")

    # --- LLM Setup ---
    if llm is None:
        log.info(
            "Setting up LLM for QueryAgent from config (no LLM instance provided)..."
        )
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
            raise RuntimeError(
                "QueryAgent LLM setup failed during ADC setup"
            ) from adc_err

        if not direct_adc_token:
            raise RuntimeError(
                "Failed to obtain authentication token for QueryAgent LLM."
            )

        log.info(
            "Initializing OpenAIProvider for QueryAgent with direct ADC token",
            base_url=BASE_URL,
        )
        provider = OpenAIProvider(base_url=BASE_URL, api_key=direct_adc_token)

        log.info("Initializing OpenAIModel for QueryAgent", model_name=MODEL_NAME)
        llm = OpenAIModel(MODEL_NAME, provider=provider)
        log.info("LLM setup complete for QueryAgent.")
    else:
        log.info("Using provided LLM instance for QueryAgent (e.g., TestModel).")

    # --- Agent Definition ---
    agent = Agent[DuckDBToolDeps, QueryAgentResult | str](
        model=llm,
        deps_type=DuckDBToolDeps,
        tools=[explore_metadata, query_metadata, count_documents],
        instructions=(
            "You are an expert assistant specialized in querying a document database via its metadata or getting document counts.\n"
            "Your primary goal is to translate the user's natural language request into an effective query using the available tools.\n\n"
            "**Available Tools:**\n"
            "- `explore_metadata`: Discover queryable fields or distinct values for a field.\n"
            "- `query_metadata`: Find documents matching specific metadata filters.\n"
            "- `count_documents`: Get the total number of documents in the database.\n\n"
            "**VERY IMPORTANT:** Your final response MUST be ONLY a single, valid JSON string conforming exactly to the following Pydantic model structure:\n"
            "```json\n"
            "{\n"
            "  'summary': 'string', /* A summary of findings, actions, or errors */\n"
            "  'retrieved_doc_ids': ['uuid'] | null /* List of UUIDs (max 10) or null (only if query_metadata was used and returned 0 or >10 results) */\n"
            "}\n"
            "```\n"
            "Do NOT add any introductory text, explanations, apologies, reasoning, or markdown formatting (like ```json) around the JSON output. The JSON string itself should be the entire response.\n\n"
            "**Workflow:**\n"
            "1.  **Analyze Intent:** Determine if the user wants to explore, query by metadata, or count documents.\n"
            "2.  **Choose Tool:** Select the appropriate tool (`explore_metadata`, `query_metadata`, or `count_documents`).\n"
            "3.  **Execute Tool:** Call the chosen tool. For `query_metadata`, if the query is ambiguous, use `explore_metadata` first.\n"
            "4.  **Format Final JSON Output:** Based on the results of the tool calls:\n"
            "    *   **`count_documents` Success:** Construct the JSON with a summary reporting the count and `retrieved_doc_ids` as `null`.\n"
            "    *   **`explore_metadata` Success:** Construct the JSON with a summary describing the fields/values found and `retrieved_doc_ids` as `null`.\n"
            "    *   **`query_metadata` Success (1-10 results):** Construct the JSON with a success summary and the list of UUIDs in `retrieved_doc_ids`.\n"
            "    *   **`query_metadata` Success (>10 results):** Construct the JSON with `retrieved_doc_ids` as `null` and a summary indicating too many results (mention the count).\n"
            "    *   **`query_metadata` Success (0 results):** Construct the JSON with `retrieved_doc_ids` as `null` and a summary indicating no results found.\n"
            "    *   **Any Tool Error:** Construct the JSON with `retrieved_doc_ids` as `null` and a summary explaining the tool error encountered.\n"
            "Remember, the final output MUST be ONLY the JSON string."
        ),
        # output_type=QueryAgentResult, # Keep commented out
        instrument=instrument_flag,
    )

    return agent
