"""
Unit tests for the database models.
"""

import datetime

from sqlmodel import SQLModel

# Assuming models are defined in src/reg_agent/core/db/models.py
from reg_agent.core.db.models import FileRecord


def test_file_record_instantiation():
    """Tests basic instantiation and default values of FileRecord."""
    now = datetime.datetime.now(datetime.timezone.utc)
    source_path = "/path/to/my/file.pdf"
    filename = "file.pdf"
    blob_content = b"dummy blob content"
    size = 12345
    extracted_md = "# Markdown Content"

    # Test instantiation with all fields
    record1 = FileRecord(
        source_path=source_path,
        filename=filename,
        blob=blob_content,
        extracted_text=extracted_md,
        size_bytes=size,
        last_modified_ts=now,
    )

    assert record1.source_path == source_path
    assert record1.filename == filename
    assert record1.blob == blob_content
    assert record1.extracted_text == extracted_md
    assert record1.size_bytes == size
    assert record1.last_modified_ts == now

    # Test instantiation with default extracted_text (None)
    record2 = FileRecord(
        source_path="/path/to/another.txt",
        filename="another.txt",
        blob=b"other content",
        # extracted_text is omitted, should default to None
        size_bytes=500,
        last_modified_ts=now,
    )

    assert record2.extracted_text is None

    # Verify it's a SQLModel instance
    assert isinstance(record1, SQLModel)
    assert isinstance(record2, SQLModel)


# Add more tests here later if needed (e.g., validation logic if added)
