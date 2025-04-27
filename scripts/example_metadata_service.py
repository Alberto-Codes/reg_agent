# scripts/example_metadata_service.py
import asyncio
import logging
import structlog

# Add src to path if running directly might be needed depending on execution context
# import sys
# from pathlib import Path
# script_dir = Path(__file__).parent
# project_root = script_dir.parent
# sys.path.append(str(project_root / 'src'))

from reg_agent.services.metadata_service import MetadataExtractionService


# --- Example Runner --- Only for standalone execution
async def main_example():
    """Basic example function to run the service."""
    log = structlog.get_logger()
    log.info("Starting metadata service example from script...")
    service = None  # Initialize service to None for finally block
    try:
        # Initialize using global config imported by the service
        service = MetadataExtractionService()

        # Sample text simulating a Consent Order snippet
        sample_text = """
        UNITED STATES OF AMERICA
        DEPARTMENT OF THE TREASURY
        OFFICE OF THE COMPTROLLER OF THE CURRENCY

        In the Matter of:
        Example Bank, N.A.
        City, State

        AA-EC-2024-123

        CONSENT ORDER

        The Office of the Comptroller of the Currency of the United States of America ("OCC"),
        through its authorized representative, has supervisory authority over Example Bank, N.A., City, State ("Bank").

        The OCC has found unsafe or unsound practices relating to the Bank's Bank Secrecy Act/Anti-Money Laundering ("BSA/AML") compliance program...

        NOW, THEREFORE, the Bank, by and through its duly elected and acting Board of Directors ("Board"), hereby stipulates and consents to the following:

        ARTICLE III
        BSA/AML COMPLIANCE PROGRAM
        (1) Within 90 days, the Board shall submit to the Assistant Deputy Comptroller a revised, acceptable written BSA/AML program for the Bank.
        (2) The program shall ensure adequate staffing and resources for BSA compliance.

        ARTICLE X
        CIVIL MONEY PENALTY
        (1) The Bank shall pay a civil money penalty of $2,500,000.

        Effective Date: April 27, 2025
        """
        log.info(
            "Running extraction example...", text_snippet=sample_text[:200] + "..."
        )
        metadata_result = await service.extract_metadata(sample_text)

        if metadata_result:
            # Log the full model dump
            log.info(
                "Example extraction successful:",
                result=metadata_result.model_dump_json(indent=2),
            )
        else:
            log.error("Example extraction failed.")

    except Exception as e:
        log.error("Example run failed.", error=str(e), exc_info=True)
    finally:
        # Ensure client is closed if service was initialized
        if service and hasattr(service, "close"):
            await service.close()


if __name__ == "__main__":
    # Configure structlog for basic console output when run directly from this script
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # Use ConsoleRenderer for prettier output
        processor=structlog.dev.ConsoleRenderer(),
        # foreign_pre_chain tells ProcessorFormatter to add its own processors
        # before the ConsoleRenderer, ensuring timestamps etc. are included.
        foreign_pre_chain=[
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.PATHNAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()  # Get root logger
    # Clear existing handlers to avoid duplication if script is reloaded or run multiple times
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)  # Set level on root logger

    log = structlog.get_logger()  # Re-get logger after configuration
    log.info("Running metadata service example script.")
    asyncio.run(main_example())
