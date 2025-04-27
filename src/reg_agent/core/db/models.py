"""
Defines the SQLModel ORM models for the database.
"""

import datetime
from typing import Optional
import uuid  # Import uuid
from sqlalchemy import TIMESTAMP, Column  # Import TIMESTAMP and Column

from sqlmodel import Field, SQLModel
# Remove unused imports
# from sqlalchemy import Integer, Column, MetaData


class FileRecord(SQLModel, table=True):
    """Represents a file record in the database."""

    # Change primary key to UUID
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        index=True,
        nullable=False,
    )

    # Keep source_path indexed and unique, but not primary key
    source_path: str = Field(index=True, unique=True)
    filename: str
    # SQLModel handles BLOB type via bytes
    blob: bytes
    # Allow extracted_text to be None if OCR fails or not applicable
    extracted_text: Optional[str] = Field(default=None)
    size_bytes: int
    # Explicitly use timezone-aware TIMESTAMP via sa_column
    last_modified_ts: datetime.datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True))
    )

    # Future potential fields (examples):
    # vector_embedding: Optional[List[float]] = Field(default=None)
    # metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
