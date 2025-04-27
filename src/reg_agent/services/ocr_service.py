"""
Service for extracting text from documents using the Docling library.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import structlog
from docling.datamodel.base_models import ConversionStatus

# Removed unused DoclingDocument import for now
# from docling.datamodel.document import DoclingDocument
from docling.document_converter import DocumentConverter

# Configure logger
log = structlog.get_logger()


class OcrService:
    """A service class to handle text extraction from documents using Docling."""

    def __init__(self) -> None:
        """Initializes the OcrService and the Docling DocumentConverter."""
        self.converter: Optional[DocumentConverter] = None
        try:
            self.converter = DocumentConverter()
            log.debug("OcrService: DocumentConverter initialized successfully.")
        except Exception as e:
            # Log the specific exception
            log.exception(
                "OcrService: Failed to initialize DocumentConverter.", error=str(e)
            )

    def extract_markdown_from_file(self, file_path: Path) -> Optional[str]:
        """
        Extracts text content as Markdown from a given file using Docling.

        Only attempts extraction for files with a .pdf extension.

        Args:
            file_path: The Path object pointing to the input file.

        Returns:
            The extracted text as a Markdown string, or None if extraction fails,
            the service is not initialized, the file doesn't exist,
            or the file is not a PDF.
        """
        if not self.converter:
            log.error("OcrService: DocumentConverter not available.")
            return None

        if not file_path.is_file():
            log.error("OcrService: Input path is not a file.", path=str(file_path))
            return None

        # Only process PDF files for now
        if file_path.suffix.lower() != ".pdf":
            log.debug("OcrService: Skipping non-PDF file.", path=str(file_path))
            return None

        log.info("OcrService: Starting text extraction.", path=str(file_path))
        start_time = time.time()
        markdown_text: Optional[str] = None

        try:
            results = self.converter.convert_all([file_path], raises_on_error=False)

            if not results:
                log.error(
                    "OcrService: No conversion result from Docling.",
                    path=str(file_path),
                )
                return None

            conv_result = results[0]

            if conv_result.status == ConversionStatus.SUCCESS and conv_result.document:
                markdown_text = conv_result.document.export_to_markdown()
                log_msg = "OcrService: Text extraction successful."
            elif conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
                log_msg = "OcrService: Partial text extraction success."
                # Try to get text even on partial success
                if conv_result.document:
                    markdown_text = conv_result.document.export_to_markdown()
            else:
                # FAILURE or SKIPPED
                log_msg = "OcrService: Text extraction failed or skipped."

            # Log outcome
            end_time = time.time()
            log_details = {
                "path": str(file_path),
                "status": conv_result.status.name,  # Use enum name
                "duration_sec": round(end_time - start_time, 2),
                "text_length": len(markdown_text) if markdown_text else 0,
                "errors": [e.error_message for e in conv_result.errors],
            }
            if conv_result.status == ConversionStatus.SUCCESS:
                log.info(log_msg, **log_details)
            else:
                log.warning(log_msg, **log_details)

        except Exception as e:
            log.exception(
                "OcrService: Unexpected error during extraction.",
                path=str(file_path),
                error=str(e),
            )
            return None  # Ensure None is returned on unexpected error

        return markdown_text


# Example usage for debugging
if __name__ == "__main__":  # pragma: no cover
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

    log.info("Running OcrService example...")

    try:
        # More robust way to find project root
        PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
        DATA_DIR = PROJECT_ROOT_DIR / "data"
        # Sample PDF file
        sample_pdf_path = DATA_DIR / "NRSRO_SEC_Letter_to_DBRS_Inc_02032011.pdf"

        if not sample_pdf_path.is_file():
            log.error("Sample PDF not found.", path=str(sample_pdf_path))
        else:
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
            "Error in OcrService example __main__ block.", error=str(main_err)
        )

    log.info("OcrService example finished.")
