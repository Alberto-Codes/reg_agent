"""
Contains repository classes for database interactions.
"""

import structlog
from sqlmodel import Session, select

from reg_agent.core.db.models import FileRecord

log = structlog.get_logger()


class FileRepository:
    """Handles database operations for FileRecord objects."""

    def __init__(self, session: Session):
        """
        Initializes the repository with a database session.

        Args:
            session: The SQLModel session to use for database operations.
        """
        self.session = session
        log.debug("FileRepository initialized with session.")

    def add(self, record: FileRecord) -> None:
        """
        Adds a FileRecord to the session (does not commit).

        Args:
            record: The FileRecord instance to add.
        """
        log.info("Adding FileRecord to session", source_path=record.source_path)
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
            statement = select(FileRecord).where(FileRecord.source_path == source_path)
            # Use select(1) or select(FileRecord.id) for efficiency if only existence is needed
            # statement = select(1).where(FileRecord.source_path == source_path).limit(1)
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

    # Add other necessary methods here later, e.g.:
    # def get_by_id(self, record_id: uuid.UUID) -> Optional[FileRecord]:
    #     ...
    # def get_by_source_path(self, source_path: str) -> Optional[FileRecord]:
    #     ...
    # def list_all(self) -> List[FileRecord]:
    #     ...
