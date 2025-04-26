# reg-agent

A simple Python package managed with uv.

## Usage

To run the package:

```bash
uv run reg-agent
```

This will print "Hello from reg-agent!" to the console.

## Running Tests

To run all tests:

```bash
uv run pytest tests
```

To run tests with coverage and generate an HTML report:

```bash
uv run pytest --cov=src/reg_agent --cov-report=html tests
```

The coverage report will be available in the `htmlcov/` directory. The `.coverage` file and `htmlcov/` directory are ignored by git.
