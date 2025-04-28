# reg-agent

A Python agent framework designed to manage and interact with a knowledge base of documents, initially focused on regulatory enforcement actions.

The core functionality involves:
*   Ingesting files into a DuckDB database.
*   Extracting text content (especially from PDFs using Docling).
*   Generating structured metadata using LLMs via Vertex AI.
*   Providing a Query-CAG (Content Augmented Generation) pipeline where an agent first searches metadata, retrieves document IDs, fetches the corresponding text, and then generates an answer grounded in the document content.
*   Providing tools for agents to query and reason about the stored information.

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Core Features

*   **Database:** Uses DuckDB via SQLModel ORM. Data access is managed using the **Repository pattern** (specifically `DocumentRepository` inheriting from `AbstractDocumentRepository`) and the **Unit of Work pattern** (`SqlModelUnitOfWork`) to ensure decoupled, testable, and transactional database interactions.
*   **Schema:** Stores file metadata and content in the `filerecord` table, including `source_path`, `filename`, `blob`, `size_bytes`, `last_modified_ts`, `extracted_text` (Markdown), `status` (tracking processing stage), and `meta_data` (JSON). The repository provides methods for querying based on standard fields and generic JSON `meta_data` fields.
*   **Ingestion Pipeline:** Provides a CLI (`reg-agent ingest run`) to execute a multi-stage ingestion pipeline:
    1.  **Record Creation:** Scans directories, reads file metadata, and creates initial `FileRecord` entries, skipping duplicates based on `source_path`.
    2.  **OCR Extraction:** Integrates with the `docling` library (`OcrService`) to automatically extract Markdown text from PDF files and store it in `extracted_text`.
    3.  **LLM Metadata Extraction:** Uses `pydantic-ai` (`MetadataExtractionService`) with Google Vertex AI (via its OpenAI-compatible endpoint) to analyze `extracted_text` and generate structured metadata (e.g., `document_type`, `issuing_agency`, `summary`), storing it in the `meta_data` JSON field.
*   **Query Pipeline (Query-CAG):** Provides a CLI (`reg-agent query <USER_QUERY>`) to execute a query pipeline using `pydantic-graph` orchestration:
    1.  **Query Agent:** Analyzes the user query, uses metadata tools (`explore_metadata`, `query_metadata`) to find relevant document IDs based on metadata filters.
    2.  **CAG Agent (Conditional):** If document IDs are found, fetches the `extracted_text` for those documents (using `fetch_text_by_ids` tool) and generates an answer based on the retrieved content and the original user query.
    3.  **Formatting:** Prepares the final output string for the user, either the CAG result or the Query Agent's summary/error.
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
├── scripts/                # Example/utility scripts (e.g., example_metadata_service.py, example_run_query_agent.py)
├── src/
│   └── reg_agent/
│       │   cli.py          # Main CLI entry point (Typer)
│       │   config.py       # Configuration loading and logging setup
│       │   py.typed
│       │   __init__.py
│       │
│       ├───agents          # Agent implementations (pydantic-ai)
│       │   │   cag_agent.py
│       │   │   query_agent.py
│       │   │   __init__.py
│       │
│       ├───auth            # Authentication helpers (GCP ADC, Impersonation)
│       │   │   http_auth.py
│       │   │   token_manager.py
│       │   │   __init__.py
│       │
│       ├───commands        # CLI command modules (e.g., for ingest, query)
│       │   │   query_cmd.py
│       │   │   ingest_cmd.py
│       │   │   __init__.py
│       │
│       ├───core            # Core data models, DB interactions, abstractions
│       │   │   __init__.py
│       │   │
│       │   └───db
│       │       │   connection.py       # DB engine setup
│       │       │   models.py           # SQLModel table definitions
│       │       │   repositories.py     # Data access logic (Repository pattern)
│       │       │   repository_abc.py   # Abstract base class for repository
│       │       │   unit_of_work.py     # Unit of Work pattern implementation
│       │       │   __init__.py
│       │
│       ├───pipelines       # Pipeline orchestration logic
│       │   │   query_and_cag_graph.py # Query->CAG graph definition (pydantic-graph)
│       │   │   __init__.py
│       │   │
│       │   └───ingestion     # Ingestion pipeline graph and tasks
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
│       ├───schemas         # Pydantic schemas (e.g., for metadata)
│       │   │   metadata.py
│       │   │   __init__.py
│       │
│       ├───services        # Business logic services (OCR, Metadata Extraction)
│       │   │   metadata_service.py
│       │   │   ocr_service.py
│       │   │   __init__.py
│       │
│       ├───tools           # Tools for agents (e.g., DB interaction tools)
│       │   │   duckdb_tool.py
│       │   │   __init__.py
│       │
│       └───utils           # Utility functions (downloading, timing)
│           │   downloader.py
│           │   timing.py
│           │   __init__.py
│
├── tests/                  # Pytest tests mirroring src structure
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

The primary interaction is through the `reg-agent` CLI command, run via `uv`.

**Note:** Scripts in the `scripts/` directory (e.g., `example_run_query_agent.py`) are primarily for reference, debugging, or demonstrating specific components. Use the CLI commands below for standard operations.

### CLI Commands

#### File Ingestion Pipeline

To run the full ingestion pipeline (record creation, OCR, metadata extraction) on files from a source directory:

```bash
# Ensure you are in the project root directory
uv run python src/reg_agent/cli.py ingest run <SOURCE_DIRECTORY> [--db-path <PATH>] [--recreate-db]
```

*   `<SOURCE_DIRECTORY>`: (Required) The path to the directory containing files to ingest (e.g., `./data`).
*   `--db-path PATH` (Optional): The path to the DuckDB database file. Defaults to `./db/regulations.db`. The file and its parent directory (`./db/`) will be created if they don't exist.
*   `--recreate-db` (Optional Flag): If present, deletes the existing database file at `--db-path` before starting ingestion. Useful for ensuring a clean slate.

**Examples:**

```bash
# Run full ingestion pipeline on ./data into the default ./db/regulations.db
# This will create records, extract text from PDFs, and extract metadata via LLM.
uv run python src/reg_agent/cli.py ingest run ./data

# Ingest files into a specific database, deleting it first if it exists
uv run python src/reg_agent/cli.py ingest run ./other_files --db-path ./other_archive.db --recreate-db
```

*(See Core Features section for details on the ingestion task stages)*

#### Query Documents (Query-CAG Pipeline)

To ask questions about the ingested documents using the Query-CAG pipeline:

```bash
# Ensure you are in the project root directory
uv run python src/reg_agent/cli.py query "<YOUR_QUERY_HERE>" [--db-path <PATH>]
```

*   `<YOUR_QUERY_HERE>`: (Required) Your natural language query about the documents, enclosed in quotes.
*   `--db-path PATH` (Optional): The path to the DuckDB database file. Defaults to `./db/regulations.db`.

**Workflow:**
1.  The `QueryAgent` analyzes your query and uses tools to search the database **metadata**.
2.  If relevant document IDs are found, the `CAGAgent` fetches the **text content** of those documents.
3.  The `CAGAgent` then generates an answer based on the **document content** and your original query.
4.  If no documents are found via metadata search, or if an error occurs, a summary or error message is returned.

**Examples:**

```bash
# Ask about documents related to a specific institution
uv run python src/reg_agent/cli.py query "Find Consent Orders issued by the CFPB for Wells Fargo"

# Ask a question that might require exploring metadata first
uv run python src/reg_agent/cli.py query "Which agencies have issued orders?"
```

### DuckDB Query Tools (`src/reg_agent/tools/duckdb_tool.py`)

This module provides tools designed for use by `pydantic-ai` agents to interact with the document metadata and text stored in the DuckDB database. These tools rely on the `DocumentRepository` provided via dependency injection (`DuckDBToolDeps`).

*   **`explore_metadata(field: Optional[str]) -> ExploreMetadataOutput`**
    *   **Purpose:** Allows the agent to discover queryable metadata fields or the distinct values within a specific field.
    *   **Behavior:**
        *   If `field` is `None`, returns a list of all queryable top-level metadata field names (e.g., `['document_type', 'issuing_agency', 'subject_institution']`).
        *   If `field` is provided, returns a list of distinct values found for that metadata field in the database.
    *   **Output Model (`ExploreMetadataOutput`):** Contains either `queryable_fields` or `distinct_values`, or an `error` message.

*   **`query_metadata(filters: Dict[str, Union[str, int, float, bool]], limit: Optional[int]) -> QueryMetadataOutput`**
    *   **Purpose:** Allows the agent to query for documents matching specific, exact metadata criteria.
    *   **Behavior:** Takes a dictionary of `filters` (e.g., `{'issuing_agency': 'CFPB', 'document_type': 'Consent Order'}`). It finds documents where the metadata matches *all* provided filters. An optional `limit` can cap the number of IDs returned (though the tool itself currently retrieves all matches from the DB before potentially limiting).
    *   **Output Model (`QueryMetadataOutput`):** Contains `matching_doc_ids` (list of UUIDs), `count` (total number of matching documents found), or an `error` message.

*   **`fetch_text_by_ids(doc_ids: List[str]) -> FetchTextByIdsOutput`**
    *   **Purpose:** Allows the agent (specifically the CAG agent) to retrieve the extracted text content for a list of document IDs.
    *   **Behavior:** Takes a list of document UUIDs (as strings) and returns a dictionary mapping each found ID to its `extracted_text`.
    *   **Output Model (`FetchTextByIdsOutput`):** Contains `texts` (a `Dict[str, str]` mapping UUID string to text) or an `error` message.

### Query Agent (`src/reg_agent/agents/query_agent.py`)

This agent is designed to answer user questions by querying the document knowledge base using the DuckDB tools.

*   **Framework:** Implemented using `pydantic-ai`.
*   **Initialization:** Created using the `create_query_agent()` factory function. This function handles setting up the LLM (configured via `.env` for Vertex AI) and injecting the tools.
*   **Core Logic (Guided by System Prompt):**
    1.  Analyzes the user's natural language query to understand intent.
    2.  Determines if the query provides specific filters.
    3.  **If ambiguous:** Uses `explore_metadata` (first to find relevant fields, then potentially again to find distinct values for those fields) to help formulate specific query criteria.
    4.  **If specific (or after exploration):** Uses `query_metadata` with the identified exact filters.
    5.  **Handles Results:** Based on the `count` from `query_metadata`:
        *   If `count > 10`, it informs the user how many results were found and suggests adding more filters (it does *not* return the list of IDs).
        *   If `count == 0`, it informs the user that no matching documents were found.
        *   If `1 <= count <= 10`, the LLM is expected to summarize the findings (the exact format depends on the LLM, but it might list the IDs or provide a brief summary).
*   **Output:** The agent returns a natural language string response to the user.
*   **Usage Example:** See the `scripts/run_query_agent.py` script for an example of how to instantiate and run the agent.

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
