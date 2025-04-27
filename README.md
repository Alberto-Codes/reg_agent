# reg-agent

A Python agent framework designed to manage and interact with a knowledge base of documents, initially focused on regulatory enforcement actions.

The core functionality involves ingesting files into a DuckDB database, extracting text content (especially from PDFs using Docling), and providing tools for an LLM agent to query and reason about the stored information.

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Core Features

*   **Database:** Uses DuckDB via SQLModel ORM and the Repository pattern (`FileRepository`).
*   **Schema:** Stores file metadata and content in the `filerecord` table, including `source_path`, `filename`, `blob`, `size_bytes`, `last_modified_ts` (timezone-aware), and `extracted_text`.
*   **Ingestion:** Provides a CLI (`reg-agent ingest run`) to scan directories, ingest files, and skip duplicates.
*   **OCR Extraction:** Integrates with the `docling` library (`OcrService`) to automatically extract Markdown text from PDF files during ingestion and store it in the `extracted_text` field.
*   **Hardware Acceleration:** The `OcrService` attempts to auto-detect CPU cores and CUDA availability to configure Docling accelerator options for potentially faster processing.
*   **CLI Utilities:** Includes flags like `--recreate-db` for easier database management during development/testing.

## Project Structure

```
reg_agent/
├── data/                   # Sample data for ingestion (ignored by git)
├── db/                     # Stores the DuckDB database file(s) (ignored by git)
├── src/
│   └── reg_agent/
│       ├── __init__.py
│       ├── core/           # Foundational components (SQLModel, Repository, etc.)
│       │   └── db/         # Database connection, models, repositories
│       ├── pipelines/      # Data processing workflows
│       │   └── ingestion/  # File ingestion logic (loader.py)
│       ├── services/       # Business logic services (e.g., OcrService)
│       ├── agents/         # LLM Agent implementations and tools (Future)
│       ├── commands/       # CLI command implementations (ingest_cmd.py)
│       ├── cli.py          # Main CLI entry point (using Typer)
│       └── utils/          # Shared utility functions (e.g., downloader)
├── tests/
│   ├── __init__.py
│   ├── core/
│   │   └── db/         # Unit tests for DB components
│   ├── integration/      # Integration tests (marked with @pytest.mark.integration)
│   │   └── test_db_integration.py
│   ├── pipelines/
│   │   └── ingestion/  # Unit tests for ingestion pipeline
│   ├── services/       # Unit tests for services
│   ├── conftest.py        # Pytest configuration (fixtures, logging setup)
│   └── utils/             # Tests for utilities
├── .gitignore
├── .python-version      # Specifies Python version
├── .ruff.toml           # Ruff configuration
├── LICENSE
├── pyproject.toml       # Project metadata and dependencies (uv)
├── README.md            # This file
└── uv.lock              # uv lock file
```

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd reg_agent
    ```

2.  **Create and activate a virtual environment (optional but recommended):**
    ```bash
    uv venv
    source .venv/bin/activate  # Linux/macOS
    # or
    .venv\Scripts\activate    # Windows
    ```

3.  **Install dependencies using uv:**
    Make sure you have `uv` installed (`pipx install uv` or `pip install uv`).
    ```bash
    uv sync
    ```
    This command installs main and development dependencies listed in `pyproject.toml` based on `uv.lock`. Key dependencies include `sqlmodel`, `duckdb-engine`, `docling`, and `torch` (for optional CUDA acceleration).

4.  **[Optional] Setup for OCR / GPU Acceleration:**
    *   The `docling` library relies on external tools for OCR, primarily **Tesseract OCR**. Ensure Tesseract is installed and accessible in your system's PATH.
    *   For **GPU acceleration** (CUDA), you need:
        *   A compatible NVIDIA GPU.
        *   Appropriate NVIDIA drivers installed.
        *   The correct version of the NVIDIA CUDA Toolkit installed.
        *   The CUDA-enabled version of PyTorch installed (see PyTorch website for specific `pip install` commands if `uv sync` installed the CPU version).

## Usage

The primary interaction is through the `reg-agent` CLI command.

### File Ingestion

To ingest files from a source directory into the database, extracting text from PDFs:

```bash
reg-agent ingest run <SOURCE_DIRECTORY> [--db-path <PATH>] [--recreate-db]
```

*   `<SOURCE_DIRECTORY>`: (Required) The path to the directory containing files to ingest (e.g., `./data`).
*   `--db-path PATH` (Optional): The path to the DuckDB database file. Defaults to `./db/regulations.db`. The file and its parent directory (`./db/`) will be created if they don't exist.
*   `--recreate-db` (Optional Flag): If present, deletes the existing database file at `--db-path` before starting ingestion. Useful for ensuring a clean slate during testing or development.

**Examples:**

```bash
# Ingest files from ./data into the default ./db/regulations.db
# This will extract text from any PDFs found.
reg-agent ingest run ./data

# Ingest files into a specific database, deleting it first if it exists
reg-agent ingest run ./other_files --db-path ./other_archive.db --recreate-db
```

The ingestion process scans the source directory recursively. For each file:
1.  It checks if the file's absolute path (`source_path`) already exists in the `filerecord` table.
2.  If it exists, the file is skipped.
3.  If it does not exist, metadata (filename, size, timestamp) and the binary content (`blob`) are read.
4.  If the file is a PDF, the `OcrService` attempts to extract its text content as Markdown using `docling`.
5.  A new record is inserted into the `filerecord` table with all gathered data, including the extracted text (or `NULL` if not a PDF or if extraction failed).

## Development

### Running Tests

Tests are written using `pytest` and located in the `tests/` directory.

*   **Run all tests:**
    ```bash
    uv run pytest
    ```
*   **Run only unit tests (exclude integration tests):**
    ```bash
    uv run pytest -m "not integration"
    ```
*   **Run only integration tests:**
    ```bash
    uv run pytest -m integration
    ```
*   **Run tests with coverage:**
    ```bash
    uv run pytest --cov=src/reg_agent --cov-report term-missing
    ```

### Linting and Formatting

This project uses `ruff` for linting and formatting.

*   **Check and fix:** `uv run ruff check --fix .`
*   **Format:** `uv run ruff format .`

### Logging

Structured logging is implemented using `structlog`. During ingestion or testing, logs provide detailed information about the process, including OCR status and database operations.
