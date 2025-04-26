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

## Logging

This project uses [structlog](https://www.structlog.org/) for structured logging. Log messages are output to the console by default.

- Log messages are emitted at the INFO level and above.
- You will see log output when running the application, e.g.:

```
uv run reg-agent
```

Example output:

```
event='Module loaded: reg_agent.__init__' timestamp='...' level='info'
event='main function called (info)' timestamp='...' level='info'
Hello from reg-agent!
```

To change the log level, adjust the `logging.basicConfig` call in `src/reg_agent/__init__.py`.
