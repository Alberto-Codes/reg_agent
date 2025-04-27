"""
Contains repository classes for database interactions.
"""

import uuid
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, text
from sqlmodel import Session, select

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repository_abc import AbstractDocumentRepository

log = structlog.get_logger()


# --- Concrete Repository Implementation ---
class DocumentRepository(AbstractDocumentRepository):
    """Handles database operations for FileRecord objects."""

    def __init__(self, session: Session):
        """
        Initializes the repository with a database session.

        Args:
            session: The SQLModel session to use for database operations.
        """
        self.session = session
        log.debug("DocumentRepository initialized with session.")

    def add(self, record: FileRecord) -> None:
        """
        Adds a FileRecord to the session (does not commit).

        Args:
            record: The FileRecord instance to add.
        """
        log.info(
            "Adding FileRecord to session",
            source_path=record.source_path,
            initial_status=record.status,
        )
        try:
            self.session.add(record)
            log.debug("FileRecord added to session successfully", record_id=record.id)
        except Exception as e:
            log.exception(
                "Error adding FileRecord to session",
                record_id=record.id,
                source_path=record.source_path,
                error=str(e),
            )
            # Re-raise the exception to allow the calling context (e.g., session manager)
            # to handle rollbacks appropriately.
            raise

    def get(self, record_id: uuid.UUID) -> Optional[FileRecord]:
        """Retrieves a FileRecord by its UUID."""
        log.debug("Fetching record by ID", record_id=record_id)
        try:
            # SQLModel's session.get is efficient for primary key lookups
            record = self.session.get(FileRecord, record_id)
            if record:
                log.debug("Record found by ID", record_id=record_id)
            else:
                log.debug("Record not found by ID", record_id=record_id)
            return record
        except Exception as e:
            log.exception(
                "Error fetching record by ID", record_id=record_id, error=str(e)
            )
            raise

    def list(self) -> List[FileRecord]:
        """Retrieves all FileRecord entities from the repository."""
        log.debug("Fetching all records")
        try:
            statement = select(FileRecord)
            results = self.session.exec(statement).all()
            log.info("Fetched all records", count=len(results))
            return list(results)
        except Exception as e:
            log.exception("Error fetching all records", error=str(e))
            raise

    def exists_by_source_path(self, source_path: str) -> bool:
        """
        Checks if a record with the given source_path already exists.

        Args:
            source_path: The source path to check for.

        Returns:
            True if a record with the source_path exists, False otherwise.
        """
        log.debug("Checking existence by source_path", path=source_path)
        try:
            # Use select(1) or select(FileRecord.id) for efficiency if only existence is needed
            statement = (
                select(FileRecord.id)
                .where(FileRecord.source_path == source_path)
                .limit(1)
            )
            result = self.session.exec(statement).first()
            exists = result is not None
            log.debug("Existence check result", path=source_path, exists=exists)
            return exists
        except Exception as e:
            log.exception(
                "Error checking existence by source_path",
                source_path=source_path,
                error=str(e),
            )
            # Depending on desired behavior, you might return False or re-raise
            # Re-raising is generally safer as it indicates an unexpected error.
            raise

    def find_by_metadata(
        self, filters: Dict[str, Any], limit: int | None = None
    ) -> List[FileRecord]:
        """
        Finds records by matching key-value pairs in the meta_data JSON field.

        Args:
            filters: A dictionary where keys are metadata field names
                     and values are the values to filter by.
                     Supports string, numeric, and boolean filter values.
            limit: Optional maximum number of records to return.
        Returns:
            A list of matching FileRecord objects.
        """
        log.debug("Finding records by metadata filters", filters=filters, limit=limit)
        try:
            statement = select(FileRecord)
            conditions = []
            params_dict = {}
            i = 0
            # Dynamically build WHERE clauses for each filter
            for key, value in filters.items():
                # Use unique param names for each condition
                param_key_name = f"key_{i}"
                param_value_name = f"value_{i}"

                # Determine the appropriate JSON extraction function based on the value type
                if isinstance(value, str):
                    extraction_function = "json_extract_string"
                elif isinstance(value, (int, float, bool)):
                    extraction_function = "json_extract"
                else:
                    # Optional: Handle other types or raise an error
                    log.warning(
                        "Unsupported filter value type, attempting string extraction.",
                        key=key,
                        type=type(value),
                    )
                    # Fallback to string extraction might be desired in some cases,
                    # or raise ValueError(f"Unsupported filter value type: {type(value)}")
                    extraction_function = "json_extract_string"
                    value = str(value)  # Coerce if falling back to string

                # Use DuckDB's json_extract/json_extract_string via text()
                condition = text(
                    f"{extraction_function}(meta_data, :{param_key_name}) = :{param_value_name}"
                )
                conditions.append(condition)
                params_dict[param_key_name] = f"$.{key}"
                params_dict[param_value_name] = value  # Pass the original value
                i += 1

            if conditions:
                # Apply all conditions using 'and_'
                statement = statement.where(and_(*conditions))

            # Apply limit if provided
            if limit is not None:
                statement = statement.limit(limit)

            # Execute with the combined parameters using session.execute
            results = self.session.execute(statement, params_dict).scalars().all()
            log.info(
                "Found records by metadata",
                count=len(results),
                filters=filters,
                limit=limit,
            )
            return list(results)
        except Exception as e:
            log.exception(
                "Error finding records by metadata", filters=filters, error=str(e)
            )
            raise

    def get_distinct_values(self, metadata_key: str) -> List[Any]:
        """
        Gets the distinct, non-null string values for a specific key
        within the meta_data JSON field across all records.

        Args:
            metadata_key: The key within the meta_data JSON to query.
        Returns:
            A sorted list of unique string values for the specified key.
            Returns an empty list if the key doesn't exist or has no non-null values.
        """
        log.debug("Getting distinct values for metadata key", key=metadata_key)
        try:
            # Construct the JSON path expression
            json_path = f"$.{metadata_key}"
            # Use text() for DuckDB's json_extract_string and DISTINCT
            # Filter out NULL results from json_extract_string
            query = text(
                "SELECT DISTINCT json_extract_string(meta_data, :key) as value "
                "FROM filerecord "
                "WHERE json_extract_string(meta_data, :key) IS NOT NULL "
                "ORDER BY value"
            )
            # Use session.execute and pass params correctly
            results = self.session.execute(query, {"key": json_path}).scalars().all()
            log.info(
                "Found distinct values for key",
                key=metadata_key,
                count=len(results),
            )
            # Ensure results are strings
            return [str(r) for r in results]
        except Exception as e:
            log.exception(
                "Error getting distinct values for metadata key",
                key=metadata_key,
                error=str(e),
            )
            raise

    def get_queryable_fields(self) -> List[str]:
        """
        Gets the list of metadata keys that are designated as queryable.
        (Placeholder implementation - returns hardcoded list)
        """
        log.debug("Returning predefined list of queryable metadata fields")
        # TODO: Make this dynamic (e.g., from config or introspection) if needed
        return ["author", "title", "year", "topic", "case_number"]  # Example fields

    def get_records_by_status(
        self, status: FileStatus | List[FileStatus]
    ) -> List[FileRecord]:
        """Retrieves all FileRecords with the specified status or list of statuses."""
        if isinstance(status, list):
            status_values = [s.value for s in status]
            log.debug("Fetching records by list of statuses", statuses=status_values)
            statement = select(FileRecord).where(FileRecord.status.in_(status_values))
        elif isinstance(status, FileStatus):
            log.debug("Fetching records by single status", status=status.value)
            statement = select(FileRecord).where(FileRecord.status == status)

        try:
            results = self.session.exec(statement).all()
            log.info(
                "Fetched records by status(es)",
                status_query=str(status),
                count=len(results),
            )
            return list(results)  # Ensure it's a list
        except Exception as e:
            log.exception(
                "Error fetching records by status(es)",
                status_query=str(status),
                error=str(e),
            )
            raise

    def get_records_needing_ocr(self) -> List[FileRecord]:
        """Retrieves all FileRecords where extracted_text is None."""
        log.debug("Fetching records needing OCR")
        try:
            statement = select(FileRecord).where(FileRecord.extracted_text is None)
            results = self.session.exec(statement).all()
            log.info("Fetched records needing OCR", count=len(results))
            return list(results)  # Ensure it's a list
        except Exception as e:
            log.exception("Error fetching records needing OCR", error=str(e))
            raise

    def get_records_needing_metadata(self) -> List[FileRecord]:
        """Retrieves all FileRecords where extracted_text is not None and meta_data is None."""
        log.debug("Fetching records needing metadata")
        try:
            statement = select(FileRecord).where(
                FileRecord.extracted_text is not None, FileRecord.meta_data is None
            )
            results = self.session.exec(statement).all()
            log.info("Fetched records needing metadata", count=len(results))
            return list(results)  # Ensure it's a list
        except Exception as e:
            log.exception("Error fetching records needing metadata", error=str(e))
            raise

    # Add other necessary methods here later, e.g.:
    # def get_by_source_path(self, source_path: str) -> Optional[FileRecord]:
    #     ...
    # def list_all(self) -> List[FileRecord]:
    #     ...
