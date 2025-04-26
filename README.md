# reg-agent

A Python agent framework designed to manage and interact with a knowledge base of documents, initially focused on regulatory enforcement actions.

The core functionality involves ingesting files into a DuckDB database and providing tools for an LLM agent to query and reason about the stored information.

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Current Status

The initial MVP (Minimum Viable Product) focusing on file ingestion into a local DuckDB database is complete.

*   **Functionality:**
    *   Connects to or creates a DuckDB database file (`.db`).
    *   Ensures the `files` table exists with the required schema (`source_path`, `filename`, `blob`, `size_bytes`, `last_modified_ts`).
    *   Provides a CLI command (`reg-agent ingest run`) to scan a directory and ingest files into the database, skipping duplicates based on `source_path`.
*   **Next Steps:** Implement agent functionalities to query and interact with the ingested data.

## Project Structure

```
reg_agent/
├── data/                   # Sample data for ingestion (ignored by git)
├── db/                     # Stores the DuckDB database file(s) (ignored by git)
├── src/
│   └── reg_agent/
│       ├── __init__.py
│       ├── core/           # Foundational components
│       │   └── db/         # DuckDB connection, schema, operations
│       ├── pipelines/      # Data processing workflows
│       │   └── ingestion/  # File ingestion logic
│       ├── agents/         # LLM Agent implementations and tools (Future)
│       ├── commands/       # CLI command implementations (ingest)
│       ├── cli.py          # Main CLI entry point (using Typer)
│       └── utils/          # Shared utility functions
├── tests/
│   ├── __init__.py
│   ├── core/
│   │   └── db/
│   │       └── test_connection.py # Tests for DB connection
│   │       └── test_loader.py     # Tests for file ingestion
│   ├── conftest.py        # Pytest configuration (incl. structlog setup)
│   └── utils/             # Tests for utilities
├── .gitignore
├── .python-version      # Specifies Python version
├── .ruff.toml           # Ruff configuration
├── LICENSE
├── pyproject.toml       # Project metadata and dependencies
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
    This command installs both main and development dependencies listed in `pyproject.toml` based on `uv.lock`.

## Usage

The primary interaction is through the `reg-agent` CLI command.

### File Ingestion

To ingest files from a source directory into the database:

```bash
reg-agent ingest run <SOURCE_DIRECTORY> [--db-path <DATABASE_FILE_PATH>]
```

*   `<SOURCE_DIRECTORY>`: The path to the directory containing files to ingest (e.g., `./data`).
*   `--db-path` (optional): The path to the DuckDB database file. Defaults to `./db/regulations.db`. The file and its parent directory (`./db/`) will be created if they don't exist. The `.db` file is ignored by git.

**Example:**

```bash
# Ingest files from the ./data directory into the default ./db/regulations.db
reg-agent ingest run ./data

# Ingest files into a specific database file
reg-agent ingest run ./path/to/your/files --db-path ./my_archive.db
```

The ingestion process scans the source directory recursively, reads file metadata and content, and inserts records into the `files` table. It skips files whose `source_path` already exists in the database.

## Development

### Running Tests

Tests are written using `pytest`.

To run all tests:
```bash
uv run pytest
```

To run tests with coverage reporting:
```bash
uv run pytest --cov=src/reg_agent --cov-report term-missing
```

### Linting and Formatting

This project uses `ruff` for linting and formatting. Configuration is in `.ruff.toml`.

To check for issues and apply automatic fixes:
```bash
uv run ruff check --fix .
```

To format code:
```bash
uv run ruff format .
```

You can run both checks sequentially:
```bash
uv run ruff check --fix . && uv run ruff format .
```

### Logging

Structured logging is implemented using `structlog`. Logs are configured to output simple key-value pairs during development and testing.
