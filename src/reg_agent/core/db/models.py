"""
Defines the SQLModel ORM models for the database.
"""

import uuid
from datetime import datetime  # Import datetime object directly
from enum import Enum  # Import Enum
from typing import Any, Dict, Optional  # Import Dict

from sqlalchemy import Column, LargeBinary  # Import TIMESTAMP, Column, LargeBinary
from sqlalchemy.types import JSON  # Import JSON
from sqlmodel import Field, SQLModel

# Remove unused imports
# from sqlalchemy import Integer, Column, MetaData


# --- Status Enum --- #
class FileStatus(str, Enum):
    PENDING_PROCESS = "pending_process"  # Initial state after creation
    PROCESSING_OCR = "processing_ocr"  # Currently undergoing OCR
    PENDING_METADATA = "pending_metadata"  # OCR done, waiting for metadata
    PROCESSING_METADATA = (
        "processing_metadata"  # Currently undergoing metadata extraction
    )
    COMPLETED = "completed"  # All steps successful
    SKIPPED_OCR = "skipped_ocr"  # OCR skipped (e.g., not a PDF)
    FAILED_OCR = "failed_ocr"  # OCR step failed
    FAILED_METADATA = "failed_metadata"  # Metadata step failed
    FAILED_UNKNOWN = "failed_unknown"  # Generic failure state


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
    # Store file content as blob
    blob: bytes = Field(sa_column=Column(LargeBinary))
    # Allow extracted_text to be None if OCR fails or not applicable
    extracted_text: Optional[str] = Field(default=None)
    # Store extracted metadata as JSON
    meta_data: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    # Track file size and modification time
    size_bytes: Optional[int] = Field(default=None)
    # Explicitly use timezone-aware TIMESTAMP via sa_column
    last_modified_ts: Optional[datetime] = Field(default=None)
    # Processing status
    status: FileStatus = Field(default=FileStatus.PENDING_PROCESS, index=True)
    # Timestamps for tracking
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    # Future potential fields (examples):
    # vector_embedding: Optional[List[float]] = Field(default=None)
    # metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
