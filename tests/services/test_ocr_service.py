"""
Unit tests for the OcrService.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.document import ConversionResult, DoclingDocument
from docling.document_converter import DocumentConverter

# Assuming OcrService is in src/reg_agent/services/ocr_service.py
from reg_agent.services.ocr_service import OcrService


# --- Fixtures ---


@pytest.fixture
def mock_docling_converter(mocker):  # Renamed for clarity
    """Fixture to provide a mock DocumentConverter instance."""
    mock_converter = mocker.MagicMock(spec=DocumentConverter)
    return mock_converter


@pytest.fixture
def mock_conversion_result(mocker):
    """Factory fixture to create mock ConversionResult objects."""

    def _create_mock_result(
        status=ConversionStatus.SUCCESS,
        mock_doc=None,
        errors=None,  # Accepts a list of mock errors or None
        input_file=Path("dummy/input.pdf"),
    ):
        result = mocker.MagicMock(spec=ConversionResult)
        result.status = status
        result.document = mock_doc
        # Assign the provided mock errors list or an empty list
        result.errors = errors if errors is not None else []
        # Mock the input attribute and its file attribute
        result.input = mocker.MagicMock()
        result.input.file = input_file
        return result

    return _create_mock_result


@pytest.fixture
def mock_docling_document(mocker):
    """Factory fixture to create mock DoclingDocument objects."""

    def _create_mock_doc(markdown_output="Extracted Markdown Text"):
        mock_doc = mocker.MagicMock(spec=DoclingDocument)
        mock_doc.export_to_markdown.return_value = markdown_output
        return mock_doc

    return _create_mock_doc


# --- Test Cases ---


def test_ocr_service_init_success(mocker):
    """Test successful initialization of OcrService."""
    mock_converter_instance = mocker.patch(
        "reg_agent.services.ocr_service.DocumentConverter", autospec=True
    )
    service = OcrService()
    assert service.converter is not None
    mock_converter_instance.assert_called_once()


def test_ocr_service_init_failure(mocker):
    """Test handling of DocumentConverter initialization failure."""
    mocker.patch(
        "reg_agent.services.ocr_service.DocumentConverter",
        side_effect=RuntimeError("Init failed"),
    )
    service = OcrService()
    assert service.converter is None


def test_extract_markdown_success(
    mocker, mock_conversion_result, mock_docling_document
):
    """Test successful markdown extraction from a PDF."""
    mock_pdf_path = Path("test.pdf")
    mocker.patch.object(Path, "is_file", return_value=True)

    expected_markdown = "Test Markdown Content"
    mock_doc = mock_docling_document(markdown_output=expected_markdown)
    mock_result = mock_conversion_result(
        status=ConversionStatus.SUCCESS, mock_doc=mock_doc
    )

    # Patch DocumentConverter within the OcrService instance
    mocker.patch.object(OcrService, "__init__", return_value=None)  # Skip real __init__
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)
    service.converter.convert_all.return_value = [mock_result]

    result = service.extract_markdown_from_file(mock_pdf_path)

    assert result == expected_markdown
    service.converter.convert_all.assert_called_once_with(
        [mock_pdf_path], raises_on_error=False
    )


def test_extract_markdown_non_pdf(mocker):
    """Test that non-PDF files are skipped."""
    mock_txt_path = Path("test.txt")
    mocker.patch.object(Path, "is_file", return_value=True)

    mocker.patch.object(OcrService, "__init__", return_value=None)  # Skip real __init__
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)

    result = service.extract_markdown_from_file(mock_txt_path)

    assert result is None
    service.converter.convert_all.assert_not_called()


def test_extract_markdown_file_not_found(mocker):
    """Test handling when the input file does not exist or is not a file."""
    mock_nonexistent_path = Path("nonexistent.pdf")
    mocker.patch.object(Path, "is_file", return_value=False)

    mocker.patch.object(OcrService, "__init__", return_value=None)
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)

    result = service.extract_markdown_from_file(mock_nonexistent_path)

    assert result is None
    service.converter.convert_all.assert_not_called()


def test_extract_markdown_converter_not_initialized():
    """Test attempting extraction when converter failed to initialize."""
    with patch.object(
        OcrService, "__init__", lambda self: setattr(self, "converter", None)
    ):
        service = OcrService()
        assert service.converter is None  # Verify assumption

        mock_pdf_path = Path("test.pdf")
        with patch.object(Path, "is_file", return_value=True):
            result = service.extract_markdown_from_file(mock_pdf_path)
            assert result is None


def test_extract_markdown_conversion_failure(mocker, mock_conversion_result):
    """Test handling when Docling conversion fails."""
    mock_pdf_path = Path("failed.pdf")
    mocker.patch.object(Path, "is_file", return_value=True)
    mock_error = mocker.MagicMock()
    mock_error.error_message = "Test failure"
    mock_result = mock_conversion_result(
        status=ConversionStatus.FAILURE, errors=[mock_error]
    )

    mocker.patch.object(OcrService, "__init__", return_value=None)
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)
    service.converter.convert_all.return_value = [mock_result]

    result = service.extract_markdown_from_file(mock_pdf_path)

    assert result is None
    service.converter.convert_all.assert_called_once_with(
        [mock_pdf_path], raises_on_error=False
    )


def test_extract_markdown_partial_success_with_doc(
    mocker, mock_conversion_result, mock_docling_document
):
    """Test partial success where a document is still returned."""
    mock_pdf_path = Path("partial.pdf")
    mocker.patch.object(Path, "is_file", return_value=True)
    expected_markdown = "Partial Content"
    mock_doc = mock_docling_document(markdown_output=expected_markdown)
    mock_error = mocker.MagicMock()
    mock_error.error_message = "Partial error"
    mock_result = mock_conversion_result(
        status=ConversionStatus.PARTIAL_SUCCESS, mock_doc=mock_doc, errors=[mock_error]
    )

    mocker.patch.object(OcrService, "__init__", return_value=None)
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)
    service.converter.convert_all.return_value = [mock_result]

    result = service.extract_markdown_from_file(mock_pdf_path)

    assert (
        result == expected_markdown
    )  # Expect markdown even on partial success if doc exists
    service.converter.convert_all.assert_called_once_with(
        [mock_pdf_path], raises_on_error=False
    )


def test_extract_markdown_partial_success_no_doc(mocker, mock_conversion_result):
    """Test partial success where no document is returned."""
    mock_pdf_path = Path("partial_nodoc.pdf")
    mocker.patch.object(Path, "is_file", return_value=True)
    mock_error = mocker.MagicMock()
    mock_error.error_message = "Partial error"
    mock_result = mock_conversion_result(
        status=ConversionStatus.PARTIAL_SUCCESS, mock_doc=None, errors=[mock_error]
    )

    mocker.patch.object(OcrService, "__init__", return_value=None)
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)
    service.converter.convert_all.return_value = [mock_result]

    result = service.extract_markdown_from_file(mock_pdf_path)

    assert result is None
    service.converter.convert_all.assert_called_once_with(
        [mock_pdf_path], raises_on_error=False
    )


def test_extract_markdown_unexpected_exception(mocker):
    """Test handling of unexpected exceptions during convert_all."""
    mock_pdf_path = Path("exception.pdf")
    mocker.patch.object(Path, "is_file", return_value=True)

    mocker.patch.object(OcrService, "__init__", return_value=None)
    service = OcrService()
    service.converter = mocker.MagicMock(spec=DocumentConverter)
    service.converter.convert_all.side_effect = ValueError("Unexpected Docling Error")

    result = service.extract_markdown_from_file(mock_pdf_path)

    assert result is None
    service.converter.convert_all.assert_called_once_with(
        [mock_pdf_path], raises_on_error=False
    )
