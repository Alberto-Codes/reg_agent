# src/reg_agent/core/db/unit_of_work.py
import abc
from types import TracebackType
from typing import Callable, Optional, Type

import structlog
from sqlmodel import Session

# Assuming get_session context manager is in connection.py
from reg_agent.core.db.connection import get_session
from reg_agent.core.db.repositories import (
    AbstractDocumentRepository,
    DocumentRepository,
)

log = structlog.get_logger()


class AbstractUnitOfWork(abc.ABC):
    """Abstract base class for the Unit of Work pattern."""

    documents: AbstractDocumentRepository

    def __enter__(self) -> "AbstractUnitOfWork":
        log.debug("Entering Unit of Work context.")
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        try:  # Wrap commit/rollback logic
            if exc_type:
                log.error(
                    "Unit of Work exiting with exception from 'with' block, rolling back.",  # Clarified log
                    exc_type=exc_type.__name__,
                    exc_value=str(exc_value),
                )
                self.rollback()
            else:
                log.debug(
                    "Unit of Work exiting normally, attempting commit."
                )  # Clarified log
                self.commit()  # Can still raise here
        finally:  # Ensure close is always called
            log.debug("Ensuring Unit of Work resources are closed.")
            self.close()

    @abc.abstractmethod
    def commit(self) -> None:
        """Commits the current transaction."""
        raise NotImplementedError

    @abc.abstractmethod
    def rollback(self) -> None:
        """Rolls back the current transaction."""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """Closes the session or releases resources."""
        raise NotImplementedError


class SqlModelUnitOfWork(AbstractUnitOfWork):
    """Concrete Unit of Work implementation using SQLModel Session."""

    def __init__(self, session_factory: Callable[[], Session] = Session):
        """
        Initializes the Unit of Work.

        Args:
            session_factory: A callable that returns a new SQLModel Session.
                             Defaults to SQLModel's Session constructor, assuming
                             an engine is globally configured or passed later.
                             In practice, use a configured session maker.
        """
        # This session factory setup might need refinement based on how
        # get_session or engine is managed globally/passed around.
        # For now, let's assume get_session handles engine management.
        # A more robust way might be to pass the engine or get_session directly.
        self._session_context = get_session()  # Get the context manager
        self.session: Optional[Session] = None

    def __enter__(self) -> "SqlModelUnitOfWork":
        """Enters the runtime context related to this object."""
        super().__enter__()  # Log entry
        # Enter the session context manager to get the actual session
        self.session = self._session_context.__enter__()
        if self.session is None:
            # Should not happen if get_session works correctly
            raise RuntimeError("Failed to acquire database session.")
        self.documents = DocumentRepository(self.session)
        return self

    def commit(self) -> None:
        """Commits changes in the current session."""
        if self.session:
            try:
                self.session.commit()
                log.debug("Unit of Work committed.")
            except Exception as e:
                log.exception(
                    "Exception during UoW commit, attempting rollback.", error=str(e)
                )
                self.rollback()  # Attempt rollback on commit failure
                raise  # Re-raise the exception
        else:
            log.warning("Commit called but session is not active.")

    def rollback(self) -> None:
        """Rolls back changes in the current session."""
        if self.session:
            try:
                self.session.rollback()
                log.debug("Unit of Work rolled back.")
            except Exception as e:
                # Log rollback error, but don't typically re-raise within rollback itself
                log.exception("Exception during UoW rollback.", error=str(e))
        else:
            log.warning("Rollback called but session is not active.")

    def close(self) -> None:
        """Calls the exit method of the underlying session context manager."""
        if hasattr(self._session_context, "__exit__"):
            # Pass None to indicate normal exit for commit/rollback logic
            # The actual exception handling is done in AbstractUnitOfWork.__exit__
            try:
                self._session_context.__exit__(None, None, None)
                log.debug("Unit of Work underlying session context closed.")
            except Exception as e:
                # Log error during context closing if needed, but usually handled by get_session
                log.exception(
                    "Exception during UoW session context close.", error=str(e)
                )
        self.session = None  # Ensure session is cleared

    # Explicit __exit__ to ensure AbstractUnitOfWork.__exit__ is called
    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        super().__exit__(exc_type, exc_value, traceback)
