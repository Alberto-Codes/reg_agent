"""Reg Agent package.

This package provides functionality for registration and agent management.
"""

import logging
import structlog

logging.basicConfig(
    format="%(message)s",
    stream=None,
    level=logging.INFO,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.KeyValueRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

logger.info("Module loaded: reg_agent.__init__")

def main() -> str:
    """Entry point for the reg-agent application.

    Returns:
        str: A greeting message from the reg-agent.
    """
    logger.debug("main function called (debug)")
    logger.info("main function called (info)")
    print("[DEBUG] If you see this, print works!")
    return "Hello from reg-agent!"
