# reg-agent

A Python agent framework designed to manage and interact with a knowledge base of documents, initially focused on regulatory enforcement actions.

The core functionality involves ingesting files into a DuckDB database, extracting text content (especially from PDFs using Docling), generating structured metadata using LLMs via Vertex AI, and providing tools for future agents to query and reason about the stored information.

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Core Features

*   **Database:** Uses DuckDB via SQLModel ORM. Data access is managed using the **Repository pattern** (specifically `DocumentRepository` inheriting from `AbstractDocumentRepository`) and the **Unit of Work pattern** (`SqlModelUnitOfWork`) to ensure decoupled, testable, and transactional database interactions.
*   **Schema:** Stores file metadata and content in the `filerecord` table, including `source_path`, `filename`, `blob`, `size_bytes`, `last_modified_ts`, `extracted_text` (Markdown), `status` (tracking processing stage), and `meta_data` (JSON). The repository provides methods for querying based on standard fields and generic JSON `meta_data` fields.
*   **Ingestion Pipeline:** Provides a CLI (`reg-agent ingest run`) to execute a multi-stage ingestion pipeline:
    1.  **Record Creation:** Scans directories, reads file metadata, and creates initial `FileRecord` entries, skipping duplicates based on `source_path`.
    2.  **OCR Extraction:** Integrates with the `docling` library (`OcrService`) to automatically extract Markdown text from PDF files and store it in `extracted_text`.
    3.  **LLM Metadata Extraction:** Uses `pydantic-ai` (`MetadataExtractionService`) with Google Vertex AI (via its OpenAI-compatible endpoint) to analyze `extracted_text` and generate structured metadata (e.g., `document_type`, `issuing_agency`, `summary`), storing it in the `meta_data` JSON field.
*   **Flexible Authentication:** Supports multiple Google Cloud authentication methods for the LLM service:
    *   **Direct ADC:** Uses Application Default Credentials found in the environment.
    *   **Impersonated ADC:** Uses the caller's ADC to impersonate a target service account (`TARGET_SA_NAME_OR_EMAIL`), generating short-lived tokens automatically via `ImpersonatedTokenManager`.
*   **Hardware Acceleration:** The `OcrService` attempts to auto-detect CPU cores and CUDA availability to configure Docling accelerator options for potentially faster processing.
*   **CLI Utilities:** Includes flags like `--recreate-db` for easier database management during development/testing.

## Project Structure

```
reg_agent/
├── data/                   # Sample data for ingestion (not checked into git)
├── db/                     # Stores the DuckDB database file(s) (ignored by git)
├── logs/                   # Stores timestamped log files from runs (ignored by git)
├── scripts/                # Example/utility scripts (e.g., example_metadata_service.py)
├── src/
│   └── reg_agent/
│       │   cli.py
│       │   config.py
│       │   py.typed
│       │   __init__.py
│       │
│       ├───agents
│       │   │   query_agent.py
│       │   │   __init__.py
│       │
│       ├───auth
│       │   │   http_auth.py
│       │   │   token_manager.py
│       │   │   __init__.py
│       │
│       ├───commands
│       │   │   __init__.py # Note: ingest_cmd.py was deleted
│       │
│       ├───core
│       │   │   __init__.py
│       │   │
│       │   └───db
│       │       │   connection.py
│       │       │   models.py
│       │       │   repositories.py
│       │       │   repository_abc.py
│       │       │   unit_of_work.py
│       │       │   __init__.py
│       │
│       ├───pipelines
│       │   │   __init__.py
│       │   │
│       │   └───ingestion
│       │       │   graph.py
│       │       │   run.py
│       │       │   __init__.py
│       │       │
│       │       └───tasks
│       │           │   task_1_create_records.py
│       │           │   task_2_ocr.py
│       │           │   task_3_metadata.py
│       │           │   __init__.py
│       │
│       ├───schemas
│       │   │   metadata.py
│       │   │   __init__.py
│       │
│       ├───services
│       │   │   metadata_service.py
│       │   │   ocr_service.py
│       │   │   __init__.py
│       │
│       ├───tools
│       │   │   duckdb_tool.py
│       │   │   __init__.py
│       │
│       └───utils
│           │   downloader.py
│           │   timing.py
│           │   __init__.py
│
├── tests/
│   ├── __init__.py
│   ├── core/
│   │   └── db/         # Unit tests for DB components
│   ├── integration/      # Integration tests (marked with @pytest.mark.integration)
│   ├── pipelines/
│   │   └── ingestion/  # Unit tests for ingestion pipeline & tasks
│   ├── services/       # Unit tests for services
│   ├── commands/       # Test directory exists, but test file was deleted
│   ├── auth/           # Unit tests for auth components
│   ├── utils/          # Tests for utilities
│   └── conftest.py     # Pytest configuration (fixtures, logging setup)
├── .env.sample          # Sample environment variables file
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
    This command installs main and development dependencies listed in `pyproject.toml` based on `uv.lock`. Key dependencies include `sqlmodel`, `duckdb-engine`, `docling`, `pydantic-ai`, `google-auth`, `httpx`, and `torch` (for optional CUDA acceleration).

4.  **Configuration (Environment Variables):**
    *   Copy the `.env.sample` file to `.env` (`cp .env.sample .env`).
    *   Edit the `.env` file and provide values for the required variables, especially for the metadata extraction service:
        *   `VERTEX_OPENAI_ENDPOINT_URL`: The regional Vertex AI OpenAI-compatible API endpoint URL (e.g., `https://us-central1-aiplatform.googleapis.com/v1beta1/projects/your-gcp-project-id/locations/us-central1/publishers/google/models`).
        *   `MODEL_NAME`: The specific model to use (e.g., `gemini-1.5-flash-001`).
        *   `TARGET_SA_NAME_OR_EMAIL` (Optional): If you want to use Service Account Impersonation, provide the email address or unique name of the target service account here. If left blank, direct ADC will be used.
    *   The application uses `python-dotenv` to automatically load these variables from the `.env` file.

5.  **Google Cloud Authentication:**
    *   **Direct ADC:** If *not* using impersonation, ensure you are authenticated with Application Default Credentials that have permission to access the Vertex AI API. Run:
        ```bash
        gcloud auth application-default login
        ```
    *   **Impersonated ADC:** If using `TARGET_SA_NAME_OR_EMAIL`, the account authenticated via `gcloud auth application-default login` needs the `roles/iam.serviceAccountTokenCreator` role on the *target* service account. The target service account itself needs permissions for Vertex AI.

6.  **[Optional] Setup for OCR / GPU Acceleration:**
    *   The `docling` library relies on external tools for OCR, primarily **Tesseract OCR**. Ensure Tesseract is installed and accessible in your system's PATH.
    *   For **GPU acceleration** (CUDA), you need:
        *   A compatible NVIDIA GPU.
        *   Appropriate NVIDIA drivers installed.
        *   The correct version of the NVIDIA CUDA Toolkit installed.
        *   The CUDA-enabled version of PyTorch installed (see PyTorch website for specific `pip install` commands if `uv sync` installed the CPU version).

## Usage

The primary interaction is through the `reg-agent` CLI command.

### File Ingestion Pipeline

To run the full ingestion pipeline (record creation, OCR, metadata extraction) on files from a source directory:

```bash
reg-agent ingest run <SOURCE_DIRECTORY> [--db-path <PATH>] [--recreate-db]
```

*   `<SOURCE_DIRECTORY>`: (Required) The path to the directory containing files to ingest (e.g., `./data`).
*   `--db-path PATH` (Optional): The path to the DuckDB database file. Defaults to `./db/regulations.db`. The file and its parent directory (`./db/`) will be created if they don't exist.
*   `--recreate-db` (Optional Flag): If present, deletes the existing database file at `--db-path` before starting ingestion. Useful for ensuring a clean slate.

**Examples:**

```bash
# Run full pipeline on ./data into the default ./db/regulations.db
# This will create records, extract text from PDFs, and extract metadata via LLM.
reg-agent ingest run ./data

# Ingest files into a specific database, deleting it first if it exists
reg-agent ingest run ./other_files --db-path ./other_archive.db --recreate-db
```

The pipeline executes the following tasks sequentially:
1.  **Task 1 (Create Records):** Scans the source directory recursively. For each file, it checks if the file's `source_path` exists in the DB. If not, it reads metadata and blob content, inserting a new `FileRecord` with status `PENDING_PROCESS`.
2.  **Task 2 (OCR):** Finds records with status `PENDING_PROCESS`. If the file is a PDF, it attempts OCR using `OcrService`. On success, updates the record with `extracted_text` (Markdown) and sets status to `PENDING_METADATA`. On failure or if not a PDF, sets status to `FAILED_OCR` or `SKIPPED_OCR`.
3.  **Task 3 (Metadata):** Finds records with status `PENDING_METADATA`. It calls the `MetadataExtractionService` to generate structured metadata from the `extracted_text`. On success, updates the `meta_data` field (JSON) and sets status to `COMPLETED`. On failure, sets status to `FAILED_METADATA`. Records without `extracted_text` at this stage are marked `FAILED_UNKNOWN`.

## Development

### Running Tests

Tests are written using `pytest` and located in the `tests/` directory. Fixtures (like DB setup) are managed in `tests/conftest.py`.

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

This project uses `ruff` for linting and formatting. Configuration is in `.ruff.toml`.

*   **Check and fix:** `uv run ruff check --fix .`
*   **Format:** `uv run ruff format .`

### Type Checking

MyPy is used for static type checking. Configuration is in `pyproject.toml`.

*   **Run MyPy:**
    ```bash
    uv run mypy src tests scripts
    ```

### Logging

Structured logging is implemented using `structlog`. During ingestion or testing, logs provide detailed information about the pipeline tasks, service operations, and database interactions. By default, logs are written to timestamped files in the `./logs/` directory. Configuration in `tests/conftest.py` ensures logs are also captured by pytest during test runs.

### Direct Database Querying

While the application uses SQLModel and the Repository pattern, you can also query the DuckDB database directly for quick inspection or analysis.

A utility script `scripts/query_metadata.py` is provided for this purpose. It connects to the default database (`./db/regulations.db`) and prints the `id`, `filename`, `status`, and pretty-printed `meta_data` (JSON) for all records in the `filerecord` table.

To run it:

```bash
python scripts/query_metadata.py
# Or using uv:
# uv run python scripts/query_metadata.py
```

You can modify this script to perform different queries as needed.
