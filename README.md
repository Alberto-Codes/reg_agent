# reg-agent

A Python agent framework designed to manage and interact with a knowledge base of documents, initially focused on regulatory enforcement actions.

The core functionality involves ingesting files into a DuckDB database and providing tools for an LLM agent to query and reason about the stored information.

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Current Status (MVP 1)

*   **Goal:** Establish a local, reproducible DuckDB database to store files and basic metadata.
*   **Progress:**
    *   Project structure defined.
    *   `duckdb` dependency added.
    *   Core database connection (`src/reg_agent/core/db/connection.py`) implemented.
        *   Creates `./db/file_archive.db` if it doesn't exist.
        *   Creates the `files` table with the initial schema.
    *   Testing framework (`pytest`, `pytest-cov`) configured.
    *   Unit test for database connection (`tests/core/db/test_connection.py`) passes.
*   **Next Steps:** Implement the file ingestion pipeline.

## Project Structure

```
reg_agent/
├── db/                     # Stores the DuckDB database file(s)
├── src/
│   └── reg_agent/
│       ├── __init__.py
│       ├── core/           # Foundational components
│       │   └── db/         # DuckDB connection, schema, operations
│       ├── pipelines/      # Data processing workflows
│       │   └── ingestion/  # File ingestion logic
│       ├── agents/         # LLM Agent implementations and tools
│       ├── commands/       # CLI command implementations
│       ├── cli.py          # Main CLI entry point (using Typer/Click - TBD)
│       └── utils/          # Shared utility functions
├── tests/
│   ├── __init__.py
│   ├── core/
│   │   └── db/
│   │       └── test_connection.py # Tests for DB connection
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
    cd reg-agent
    ```

2.  **Install dependencies using uv:**
    Make sure you have `uv` installed (`pipx install uv`).
    ```bash
    uv sync
    ```
    This command installs both main and development dependencies listed in `pyproject.toml` based on `uv.lock`.

## Usage

(Currently under development. A CLI will be added to trigger ingestion and interact with the agent.)

The core database connection can be tested programmatically:

```python
# Example: Ensure DB connection and table creation works
from reg_agent.core.db.connection import connect_db

try:
    con = connect_db() # Uses ./db/file_archive.db by default
    print("Connection successful, 'files' table ensured.")
    # Check table structure
    print(con.execute("DESCRIBE files;").fetchall())
    con.close()
except Exception as e:
    print(f"An error occurred: {e}")
```

## Development

### Running Tests

Tests are written using `pytest`.

To run all tests:
```bash
uv run pytest
```

To run tests with coverage reporting (targeting the `src/reg_agent` package):
```bash
uv run pytest --cov=src/reg_agent --cov-report term-missing
```

### Linting and Formatting

This project uses `ruff` for linting and formatting. Configuration is in `.ruff.toml`.

To check for linting errors:
```bash
uv run ruff check .
```

To automatically format code:
```bash
uv run ruff format .
```

### Logging

Structured logging is implemented using `structlog`. See `src/reg_agent/utils/downloader.py` for example usage and `tests/conftest.py` for how it's configured for testing.
