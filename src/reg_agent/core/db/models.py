"""
Defines the SQLModel ORM models for the database.
"""

import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class FileRecord(SQLModel, table=True):
    """Represents a file record in the database."""

    # Use Field(primary_key=True) for the primary key
    # Make index=True for potential lookup speed improvements if needed later
    source_path: str = Field(primary_key=True, index=True)
    filename: str
    # SQLModel handles BLOB type via bytes
    blob: bytes
    # Allow extracted_text to be None if OCR fails or not applicable
    extracted_text: Optional[str] = Field(default=None)
    size_bytes: int
    # SQLModel/SQLAlchemy handle timezone-aware datetime
    last_modified_ts: datetime.datetime

    # Future potential fields (examples):
    # vector_embedding: Optional[List[float]] = Field(default=None)
    # metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
