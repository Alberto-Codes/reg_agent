# src/reg_agent/tools/duckdb_tool.py

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import structlog
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import RunContext

from reg_agent.core.db.repositories import DocumentRepository

log = structlog.get_logger()


# --- Dependency Dataclass ---
# This will be passed via RunContext and holds the necessary repository
@dataclass
class DuckDBToolDeps:
    repo: DocumentRepository


# --- Input/Output Models for Tools ---


class ExploreMetadataInput(BaseModel):
    field: Optional[str] = Field(
        None,
        description="Specific metadata field to get distinct values for. If None, returns all queryable fields.",
    )


class ExploreMetadataOutput(BaseModel):
    queryable_fields: Optional[List[str]] = Field(
        None, description="List of all top-level queryable metadata fields."
    )
    distinct_values: Optional[List[Any]] = Field(
        None, description="List of distinct values for the requested field."
    )
    error: Optional[str] = Field(None, description="Error message if operation failed.")

    @field_validator("*", mode="before")
    def check_at_least_one_value(cls, values):
        return values


class QueryMetadataInput(BaseModel):
    filters: Dict[str, Union[str, int, float, bool]] = Field(
        ...,
        description="Dictionary of metadata fields and their desired values to filter by.",
    )
    limit: Optional[int] = Field(
        None, description="Maximum number of document IDs to return."
    )


class QueryMetadataOutput(BaseModel):
    matching_doc_ids: List[uuid.UUID] = Field(
        ..., description="List of UUIDs for documents matching the filters."
    )
    count: int = Field(..., description="Number of documents found.")
    error: Optional[str] = Field(None, description="Error message if operation failed.")


# --- Input/Output Models for Fetch Text Tool ---
class FetchTextByIdsInput(BaseModel):
    doc_ids: List[uuid.UUID] = Field(
        ..., description="List of document UUIDs to fetch extracted text for."
    )


class FetchTextByIdsOutput(BaseModel):
    texts: Dict[uuid.UUID, Optional[str]] = Field(
        ...,
        description="Dictionary mapping document UUIDs to their extracted text. Value is None if text is missing.",
    )
    error: Optional[str] = Field(None, description="Error message if operation failed.")


# --- Tool Functions ---

# Note: PydanticAI uses the function docstring as the tool description for the LLM.
# The @tool decorator is not needed if functions are passed directly to Agent(tools=[...])


async def count_documents(ctx: RunContext[DuckDBToolDeps]) -> int:
    """Returns the total number of documents currently stored in the database."""
    repo = ctx.deps.repo
    log.info("Running count_documents tool")
    try:
        count = await asyncio.to_thread(repo.get_total_document_count)
        log.info("Count documents result", count=count)
        return count
    except Exception as e:
        # For a simple count, maybe returning 0 or -1 is better than raising?
        # Or log and return a specific error code/message? Let's return 0 for now.
        error_msg = "Error counting documents"
        log.exception(error_msg, error=e)
        return -1  # Indicate error


async def explore_metadata(
    ctx: RunContext[DuckDBToolDeps], params: ExploreMetadataInput
) -> ExploreMetadataOutput:
    """
    Explores the available metadata fields in the DuckDB database or gets distinct values for a specific field.

    Use this tool to understand what criteria you can filter documents by.
    If you provide a field name, it returns the unique values for that field.
    If you don't provide a field name, it returns all available filterable fields.
    """
    repo = ctx.deps.repo
    log.info("Running explore_metadata tool", field=params.field)

    if params.field:
        try:
            values = await asyncio.to_thread(repo.get_distinct_values, params.field)
            log.info(
                "Found distinct values for field", field=params.field, count=len(values)
            )
            return ExploreMetadataOutput(
                distinct_values=values, queryable_fields=None, error=None
            )
        except Exception as e:
            error_msg = f"Error getting distinct values for field '{params.field}'"
            log.exception(error_msg, error=e)
            return ExploreMetadataOutput(
                distinct_values=None, queryable_fields=None, error=f"{error_msg}: {e}"
            )
    else:
        try:
            fields = await asyncio.to_thread(repo.get_queryable_fields)
            log.info("Found queryable fields", count=len(fields))
            return ExploreMetadataOutput(
                queryable_fields=fields, distinct_values=None, error=None
            )
        except Exception as e:
            error_msg = "Error getting queryable fields"
            log.exception(error_msg, error=e)
            return ExploreMetadataOutput(
                queryable_fields=None, distinct_values=None, error=f"{error_msg}: {e}"
            )


async def query_metadata(
    ctx: RunContext[DuckDBToolDeps], params: QueryMetadataInput
) -> QueryMetadataOutput:
    """
    Queries the DuckDB database for documents matching specific metadata filters.

    Provide a dictionary of filters where keys are metadata field names and values are the
    exact values to match (strings, numbers, or booleans).
    Returns a list of document IDs that match ALL provided filters.
    """
    repo = ctx.deps.repo
    log.info("Running query_metadata tool", filters=params.filters, limit=params.limit)

    try:
        matching_records = await asyncio.to_thread(
            repo.find_by_metadata, filters=params.filters, limit=params.limit
        )
        doc_ids = [record.id for record in matching_records]
        count = len(doc_ids)
        log.info("Found matching documents", count=count, filters=params.filters)
        return QueryMetadataOutput(matching_doc_ids=doc_ids, count=count, error=None)
    except Exception as e:
        error_msg = f"Error querying metadata with filters {params.filters}"
        log.exception(error_msg, error=e)
        return QueryMetadataOutput(
            matching_doc_ids=[], count=0, error=f"{error_msg}: {e}"
        )


async def fetch_text_by_ids(
    ctx: RunContext[DuckDBToolDeps], params: FetchTextByIdsInput
) -> FetchTextByIdsOutput:
    """
    Fetches the extracted text content for a given list of document UUIDs.
    """
    repo = ctx.deps.repo
    log.info("Running fetch_text_by_ids tool", count=len(params.doc_ids))
    try:
        text_map = await asyncio.to_thread(
            repo.get_extracted_text_by_ids, params.doc_ids
        )
        log.info("Successfully fetched text for IDs", found_count=len(text_map))
        return FetchTextByIdsOutput(texts=text_map, error=None)
    except Exception as e:
        error_msg = "Error fetching text for IDs"
        log.exception(error_msg, error=e)
        return FetchTextByIdsOutput(texts={}, error=f"{error_msg}: {e}")
