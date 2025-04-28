# src/reg_agent/agents/cag_agent.py

import os
import uuid
from typing import List

import google.auth
import google.auth.transport.requests
import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from reg_agent.config import BASE_URL, MODEL_NAME, log
from reg_agent.tools.duckdb_tool import DuckDBToolDeps, fetch_text_by_ids


# --- Agent Input Model (Specific to CAG) ---
# This defines what the CAG agent expects as input when called programmatically
class CAGAgentInput(BaseModel):
    original_query: str = Field(description="The user's original query.")
    doc_ids: List[uuid.UUID] = Field(description="List of relevant document UUIDs.")


# --- Agent Output Model (Optional) ---
# Define structured output if needed, otherwise defaults to string
class CAGAgentResult(BaseModel):
    answer: str = Field(
        description="The final answer generated based on the documents."
    )
    # Add fields for sources, errors, etc. if needed later


# --- Agent Creation Function ---
def create_cag_agent(llm: OpenAIModel | None = None) -> Agent[DuckDBToolDeps, str]:
    """Sets up dependencies and creates the CAGAgent instance.

    Args:
        llm: An optional pre-initialized LLM instance.

    Returns:
        An initialized Agent instance for Cache Augmented Generation.
    """
    log.info("Creating CAGAgent instance...")

    # --- Logfire Conditional Setup (Similar to QueryAgent) ---
    instrument_flag = False
    enable_logfire_env = os.environ.get("ENABLE_LOGFIRE", "false").lower()
    if enable_logfire_env == "true":
        # Simplified for brevity - copy full logic from query_agent if needed
        try:
            logfire.configure()
            instrument_flag = True
            log.info("Logfire instrumentation enabled for CAGAgent.")
        except Exception as e:
            log.error("Failed to configure Logfire for CAGAgent.", error=e)
            instrument_flag = False
    else:
        log.info("Logfire instrumentation disabled for CAGAgent.")

    # --- LLM Setup (Similar to QueryAgent) ---
    if llm is None:
        log.info("Setting up LLM for CAGAgent from config...")
        # Simplified for brevity - copy full logic from query_agent if needed
        try:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            adc_token = credentials.token
            if not adc_token:
                raise ValueError("Could not get ADC token")
            provider = OpenAIProvider(base_url=BASE_URL, api_key=adc_token)
            llm = OpenAIModel(MODEL_NAME, provider=provider)
            log.info("LLM setup complete for CAGAgent.")
        except Exception as e:
            log.error("Failed during LLM setup for CAGAgent", exc_info=True)
            raise RuntimeError("CAGAgent LLM setup failed") from e
    else:
        log.info("Using provided LLM instance for CAGAgent.")

    # --- Agent Definition ---
    agent = Agent(
        model=llm,
        deps_type=DuckDBToolDeps,
        tools=[fetch_text_by_ids],  # Include the new tool
        instructions=(
            "You are an assistant designed to answer questions based *only* on provided document excerpts.\n"
            "You will be given the user's original query and a list of document IDs.\n\n"
            "**Workflow:**\n"
            "1.  Use the `fetch_text_by_ids` tool to retrieve the text content for ALL the provided document IDs.\n"
            "2.  If the tool returns an error or no text is found for any relevant ID, state that you cannot answer without the document content.\n"
            "3.  Combine the retrieved text excerpts.\n"
            "4.  Analyze the combined text in relation to the user's original query.\n"
            "5.  Synthesize a concise answer to the query based *solely* on the information present in the retrieved text.\n"
            "6.  If the text does not contain information relevant to the query, state that the provided documents do not contain the answer.\n"
            "7.  Do NOT use any prior knowledge or external information. Stick strictly to the provided document content."
        ),
        # output_type=CAGAgentResult, # Optional: Use if structured output is desired
        instrument=instrument_flag,
    )

    log.info("CAGAgent instance created successfully.")
    return agent


# Example of how this might be called programmatically (orchestration logic)
# async def run_full_query(user_query: str, query_agent: Agent, cag_agent: Agent, deps: DuckDBToolDeps):
#     # 1. Run Query Agent
#     query_result = await query_agent.run(user_query, deps=deps)
#     # TODO: Parse query_result to get doc_ids (assuming it can return them)
#     doc_ids_found = [...] # Extract IDs here
#
#     if doc_ids_found:
#         # 2. Run CAG Agent
#         cag_input = CAGAgentInput(original_query=user_query, doc_ids=doc_ids_found)
#         # Need to construct the prompt for the CAG agent based on the input model
#         # This might require a helper or adjusting how the agent is run for programmatic input
#         cag_prompt = f"User Query: {cag_input.original_query}\nDocument IDs: {[str(id) for id in cag_input.doc_ids]}\nPlease fetch the text for these IDs and answer the query based on their content."
#         final_answer = await cag_agent.run(cag_prompt, deps=deps)
#         return final_answer.output
#     else:
#         # Handle case where query agent found no documents or returned a summary
#         return query_result.output # Or some other message
