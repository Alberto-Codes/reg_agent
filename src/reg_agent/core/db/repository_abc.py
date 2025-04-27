import uuid
from abc import ABC, abstractmethod
from typing import Any, Generic, List, Optional, TypeVar

from sqlmodel import SQLModel

from .models import FileRecord, FileStatus

# Define TypeVars for generic repository
T = TypeVar("T", bound=SQLModel)
IdType = TypeVar("IdType")


class AbstractRepository(ABC, Generic[T, IdType]):
    """Abstract base class for a generic repository."""

    @abstractmethod
    def add(self, entity: T) -> None:
        """Adds a new entity to the repository."""
        raise NotImplementedError

    @abstractmethod
    def get(self, id: IdType) -> Optional[T]:
        """Retrieves an entity by its identifier."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> List[T]:
        """Retrieves all entities from the repository."""
        raise NotImplementedError


class AbstractDocumentRepository(AbstractRepository[FileRecord, uuid.UUID]):
    """Abstract interface specific to the FileRecord repository."""

    @abstractmethod
    def get(self, id: uuid.UUID) -> Optional[FileRecord]:
        """Retrieves a FileRecord entity by its identifier."""
        raise NotImplementedError

    @abstractmethod
    def exists_by_source_path(self, source_path: str) -> bool:
        """Checks if a record exists based on its source path."""
        raise NotImplementedError

    @abstractmethod
    def get_records_by_status(self, status: FileStatus | List[FileStatus]) -> List[FileRecord]:
        """Retrieves records based on their processing status or list of statuses."""
        raise NotImplementedError

    # --- Methods for Issue #18 --- #

    @abstractmethod
    def find_by_metadata(
        self, metadata_filter: dict[str, Any], limit: Optional[int] = None
    ) -> List[FileRecord]:
        """Finds records matching the provided metadata filter.

        Args:
            metadata_filter: A dictionary where keys are metadata fields
                             and values are the expected values.
            limit: Optional maximum number of records to return.

        Returns:
            A list of matching FileRecord objects.
        """
        raise NotImplementedError

    @abstractmethod
    def get_distinct_values(self, metadata_key: str) -> List[Any]:
        """Gets distinct values for a specific key within the metadata JSON field.

        Args:
            metadata_key: The key within the JSON metadata to query.

        Returns:
            A list of unique values found for that key across all records.
        """
        raise NotImplementedError

    @abstractmethod
    def get_queryable_fields(self) -> List[str]:
        """Gets the list of metadata fields considered safe/indexed for querying.

        Returns:
            A list of queryable metadata field names.
        """
        raise NotImplementedError
