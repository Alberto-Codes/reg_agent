import logging

import pytest
import structlog


@pytest.fixture(autouse=True)
def configure_structlog_for_pytest():
    """
    Fixture to automatically configure structlog for each test.

    This ensures structlog uses standard library logging handlers,
    allowing pytest's caplog fixture to capture the logs correctly.
    """
    # Reset structlog configuration before each test to avoid interference
    structlog.reset_defaults()

    # Configure structlog processors for standard library compatibility
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # Use the standard library logger factory.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure a basic formatter for the standard library handler
    # This makes logs visible when running pytest with -s, for example
    formatter = structlog.stdlib.ProcessorFormatter(
        # These run ONLY FOR stdlib logging, not structlog levels.
        # Add a timestamp and level name to the output.
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
        ],
        processor=structlog.dev.ConsoleRenderer(),  # Or use JSONRenderer etc.
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Get the root logger and remove existing handlers to avoid duplicates
    # Be careful with this if other parts of the test setup add handlers.
    root_logger = logging.getLogger()
    # Remove existing handlers added by structlog in downloader.py if it was imported
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)  # Or set level as needed

    # Yield control to the test
    yield

    # Optional: Clean up handlers after the test if necessary
    # structlog.reset_defaults() # Reset again if needed
    # root_logger.removeHandler(handler) # Remove the handler we added
