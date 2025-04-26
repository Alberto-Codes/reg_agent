# reg-agent

A Python agent designed to download and process regulatory enforcement action data from various sources (e.g., FRB, OCC).

This project is managed using `uv` for dependency management and `ruff` for linting/formatting.

## Project Structure

```
reg_agent/
├── src/
│   └── reg_agent/
│       ├── __init__.py
│       └── utils/
│           ├── __init__.py
│           └── downloader.py  # Handles downloading data
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # Pytest configuration (incl. structlog setup)
│   └── utils/
│       ├── __init__.py
│       └── test_downloader.py # Tests for the downloader
├── .gitignore
├── .ruff.toml           # Ruff configuration
├── LICENSE
├── pyproject.toml       # Project metadata and dependencies
└── README.md
```

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd reg-agent
    ```

2.  **Install dependencies using uv:**
    ```bash
    uv sync
    ```
    This command installs both main and development dependencies listed in `pyproject.toml`.

## Usage

(Currently, the primary functionality is within the `Downloader` class in `src/reg_agent/utils/downloader.py`. Add instructions here as a CLI or main entry point is developed.)

Example (programmatic):
```python
from reg_agent.utils.downloader import Downloader

# Initialize the downloader
downloader = Downloader()

# Example: Search FRB enforcement actions
# Note: Actual implementation might vary
try:
    frb_results = downloader.search_frb("search term")
    print(f"Found {len(frb_results)} FRB results.")
except Exception as e:
    print(f"An error occurred: {e}")

# Example: Search OCC enforcement actions
# try:
#     occ_results = downloader.search_occ("search term")
#     print(f"Found {len(occ_results)} OCC results.")
# except Exception as e:
#     print(f"An error occurred: {e}")
```

## Development

### Running Tests

Tests are written using `pytest`. The test suite includes configuration in `tests/conftest.py` to ensure `structlog` logs are correctly captured during testing.

To run all tests:
```bash
uv run pytest
```

To run specific tests:
```bash
uv run pytest tests/utils/test_downloader.py
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
