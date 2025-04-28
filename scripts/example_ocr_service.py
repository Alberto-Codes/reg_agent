"""
Example script for using OcrService to extract Markdown from a PDF file.
"""

import logging
from pathlib import Path
import structlog
import random

from reg_agent.services.ocr_service import OcrService


def main() -> None:
    """Run an example of extracting Markdown from a PDF using OcrService."""
    # Basic logging setup for direct script execution
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    # Minimal structlog setup for this block
    structlog.configure(
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    log = structlog.get_logger()
    log.info("Running OcrService example...")

    try:
        # More robust way to find project root
        PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT_DIR / "data"
        # Pick a random PDF file from the data directory
        pdf_files = list(DATA_DIR.glob("*.pdf"))
        if not pdf_files:
            log.error("No PDF files found in data directory.", path=str(DATA_DIR))
            return
        sample_pdf_path = random.choice(pdf_files)
        log.info("Randomly selected PDF file.", path=str(sample_pdf_path))

        if not sample_pdf_path.is_file():
            log.error("Sample PDF not found.", path=str(sample_pdf_path))
            return

        log.info("Creating OcrService instance...")
        ocr_service = OcrService()

        if ocr_service.converter:
            log.info("Attempting extraction...", path=str(sample_pdf_path))
            extracted_markdown = ocr_service.extract_markdown_from_file(
                sample_pdf_path
            )

            if extracted_markdown:
                log.info(
                    "Markdown extracted successfully.",
                    length=len(extracted_markdown),
                )
                output_file_path = PROJECT_ROOT_DIR / "temp_extracted_text.md"
                try:
                    output_file_path.write_text(
                        extracted_markdown, encoding="utf-8"
                    )
                    log.info("Full text saved.", path=str(output_file_path))
                except IOError as io_err:
                    log.error(
                        "Failed to write output file.",
                        path=str(output_file_path),
                        error=str(io_err),
                    )
            else:
                log.warning("Failed to extract Markdown from sample PDF.")
        else:
            log.error("OcrService failed to initialize DocumentConverter.")

    except Exception as main_err:
        log.exception(
            "Error in OcrService example script.", error=str(main_err)
        )

    log.info("OcrService example finished.")


if __name__ == "__main__":
    main() 