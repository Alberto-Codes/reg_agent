# import sys # No longer using unittest, sys import likely unnecessary
# import unittest # No longer using unittest
import pytest  # Using pytest now
from pathlib import Path
from unittest.mock import MagicMock # Can keep MagicMock if needed for complex mocks, but try to avoid.
import requests # Need this for exception testing
import pandas as pd
from io import StringIO
import csv
from bs4 import BeautifulSoup
# Import the logger used within the module under test
from reg_agent.utils.downloader import logger as downloader_logger
import structlog # Add import

# Ensure src directory is in the path to find reg_agent during testing
# This might be necessary depending on how tests are run. Adjust if needed.
# Alternatively, configure pytest paths in pyproject.toml or pytest.ini
# Example using sys.path:
# import os
# current_dir = os.path.dirname(os.path.abspath(__file__))
# src_path = os.path.abspath(os.path.join(current_dir, '..', '..', 'src'))
# if src_path not in sys.path:
#    sys.path.insert(0, src_path)

# Since we used absolute imports in __init__.py, we need to import like this
from reg_agent.utils.downloader import ConsentOrderDownloader


# Replaced unittest.TestCase with pytest functions and mocker fixture

def test_init_default_output_dir(mocker):
    """Test initialization with the default output directory using pytest-mock."""
    mock_mkdir = mocker.patch("pathlib.Path.mkdir") # Use mocker fixture
    
    downloader = ConsentOrderDownloader()

    assert downloader.output_dir == Path("data")
    mock_mkdir.assert_called_once_with(exist_ok=True)
    assert downloader.log is not None # Use standard assert
    assert "CFPB" in downloader.regulatory_sites # Use standard assert
    assert "Wells Fargo" in downloader.search_terms # Use standard assert
    assert "User-Agent" in downloader.headers # Use standard assert

def test_init_custom_output_dir(mocker):
    """Test initialization with a custom output directory using pytest-mock."""
    mock_mkdir = mocker.patch("pathlib.Path.mkdir")
    custom_dir = "custom_test_data"
    
    downloader = ConsentOrderDownloader(output_dir=custom_dir)

    assert downloader.output_dir == Path(custom_dir)
    mock_mkdir.assert_called_once_with(exist_ok=True)


# --- Tests for download_file ---

@pytest.fixture
def downloader_instance(mocker):
    """Fixture to create a ConsentOrderDownloader instance with mocked mkdir."""
    mocker.patch("pathlib.Path.mkdir")
    downloader = ConsentOrderDownloader()
    return downloader # Return only downloader

def test_download_file_success(mocker, downloader_instance):
    """Test successful file download."""
    # Arrange
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
    mock_requests_get = mocker.patch("requests.get", return_value=mock_response)
    
    # Mock file operations
    mock_file_handle = mocker.mock_open()
    mock_open = mocker.patch("builtins.open", mock_file_handle)
    
    test_url = "http://example.com/file.pdf"
    test_filename = "test_file.pdf"
    downloader = downloader_instance
    expected_filepath = downloader.output_dir / test_filename

    # Act
    result = downloader.download_file(test_url, test_filename)

    # Assert
    assert result is True
    mock_requests_get.assert_called_once_with(test_url, stream=True, headers=downloader.headers)
    mock_response.raise_for_status.assert_called_once()
    mock_open.assert_called_once_with(expected_filepath, "wb")
    mock_file_handle().write.assert_any_call(b"chunk1")
    mock_file_handle().write.assert_any_call(b"chunk2")

def test_download_file_request_exception(mocker, downloader_instance):
    """Test file download failure due to requests exception."""
    # Arrange
    mock_requests_get = mocker.patch("requests.get", side_effect=requests.exceptions.RequestException("Test Error"))
    mock_open = mocker.patch("builtins.open") # Mock open to ensure it's not called

    test_url = "http://example.com/badfile.pdf"
    test_filename = "bad_file.pdf"
    downloader = downloader_instance

    # Act
    result = downloader.download_file(test_url, test_filename)

    # Assert
    assert result is False
    mock_requests_get.assert_called_once_with(test_url, stream=True, headers=downloader.headers)
    mock_open.assert_not_called() # Ensure file was not opened on error

# --- Tests for search_cfpb ---

MOCK_CFPB_SEARCH_HTML = """
<html><body>
    <div class="o-post-preview">
        <h3><a href="/actions/details/wells-fargo-action-1/">Wells Fargo Action One</a></h3>
    </div>
    <div class="o-post-preview">
        <h3><a href="/actions/details/other-bank-action/">Other Bank Action</a></h3>
    </div>
</body></html>
"""

MOCK_CFPB_ACTION_DETAIL_HTML = """
<html><body>
    <h1>Details Page</h1>
    <a href="/documents/consent-order-1.pdf">Download PDF 1</a>
    <a href="../documents/consent-order-2.pdf">Download PDF 2</a>
    <a href="http://external.com/doc.pdf">External PDF</a>
</body></html>
"""

def test_search_cfpb_success(mocker, downloader_instance):
    """Test search_cfpb finds a matching action (refactored)."""
    # Arrange
    # Mock _fetch_and_parse to return different soups based on URL
    mock_search_soup = BeautifulSoup(MOCK_CFPB_SEARCH_HTML, "html.parser")
    mock_detail_soup = BeautifulSoup(MOCK_CFPB_ACTION_DETAIL_HTML, "html.parser")

    def mock_fetch(*args, **kwargs):
        url = args[0] # url is the first positional arg
        if "consumerfinance.gov/enforcement/actions/?title=Wells+Fargo" in url:
            return mock_search_soup
        elif "consumerfinance.gov/actions/details/wells-fargo-action-1/" in url:
            return mock_detail_soup
        else:
            return None # Simulate fetch failure for unexpected URLs

    downloader = downloader_instance
    mock_fetch_parse = mocker.patch.object(downloader, '_fetch_and_parse', side_effect=mock_fetch)
    mock_find_download = mocker.patch.object(downloader, '_find_and_download_pdfs')
    
    # Expected detail URL to be passed to helpers
    expected_detail_url = "https://www.consumerfinance.gov/actions/details/wells-fargo-action-1/"
    expected_search_url = "https://www.consumerfinance.gov/enforcement/actions/?title=Wells+Fargo&from_date=&to_date="

    # Act
    downloader.search_cfpb()

    # Assert
    # Check _fetch_and_parse calls (search page + matching detail page)
    assert mock_fetch_parse.call_count == 2
    mock_fetch_parse.assert_any_call(expected_search_url)
    mock_fetch_parse.assert_any_call(expected_detail_url)

    # Check _find_and_download_pdfs call (only for the successful detail page parse)
    mock_find_download.assert_called_once_with(mock_detail_soup, expected_detail_url, "CFPB")


# Add more tests for search_cfpb (e.g., no results found, request errors)

# --- Tests for search_occ ---

MOCK_OCC_SEARCH_HTML = """
<html><body>
    <div class="search-result">
        <h3><a href="/topics/enforcement-actions/ea2023-050.html">OCC Action Against Wells Fargo Bank</a></h3>
        <p>Some description...</p>
    </div>
    <div class="search-result">
        <h3><a href="/topics/enforcement-actions/ea2023-051.html">OCC Action Against Other Bank</a></h3>
        <p>Description for other bank...</p>
    </div>
</body></html>
"""

MOCK_OCC_ACTION_DETAIL_HTML = """
<html><body>
    <h1>OCC Action Page</h1>
    <a href="/static/publications/ea2023-050.pdf">Download Consent Order PDF</a>
</body></html>
"""

def test_search_occ_success(mocker, downloader_instance):
    """Test search_occ finds a matching action (refactored)."""
    # Arrange
    mock_search_soup = BeautifulSoup(MOCK_OCC_SEARCH_HTML, "html.parser")
    mock_detail_soup = BeautifulSoup(MOCK_OCC_ACTION_DETAIL_HTML, "html.parser")

    def mock_fetch(*args, **kwargs):
        url = args[0]
        if "occ.gov/search/index.html?q=wells+fargo+enforcement+action" in url:
            return mock_search_soup
        elif "occ.gov/topics/enforcement-actions/ea2023-050.html" in url:
            return mock_detail_soup
        else:
            return None

    downloader = downloader_instance
    mock_fetch_parse = mocker.patch.object(downloader, '_fetch_and_parse', side_effect=mock_fetch)
    mock_find_download = mocker.patch.object(downloader, '_find_and_download_pdfs')

    # Expected URLs
    expected_search_url = downloader.regulatory_sites["OCC"]
    expected_detail_url = "https://occ.gov/topics/enforcement-actions/ea2023-050.html"

    # Act
    downloader.search_occ()

    # Assert
    # Check _fetch_and_parse calls
    assert mock_fetch_parse.call_count == 2
    mock_fetch_parse.assert_any_call(expected_search_url)
    mock_fetch_parse.assert_any_call(expected_detail_url)

    # Check _find_and_download_pdfs call
    mock_find_download.assert_called_once_with(mock_detail_soup, expected_detail_url, "OCC")


# Add more tests for search_occ (e.g., no results, request errors)

# --- Tests for search_frb ---

# Sample CSV data matching actual expected FRB structure (ensure no leading/trailing internal newlines)
MOCK_FRB_CSV_DATA = ("Institution Name,Docket Number,Action Type,Action Date,URL\n"
                     "\"Wells Fargo Bank, N.A.\",\"FRB-23-001\",\"Consent Order\",\"2023-01-15\",\"https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230115a1.pdf\"\n"
                     "\"Other Bank\",\"FRB-23-002\",\"Fine\",\"2023-02-20\",\"https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230220a1.pdf\"\n"
                     "\"Wells Fargo & Company\",\"FRB-23-003\",\"Written Agreement\",\"2023-03-10\",\"https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230310a1.pdf\"")

def test_search_frb_success(mocker, downloader_instance):
    """Test search_frb finds matching actions and calls download_file."""
    # Arrange
    downloader = downloader_instance
    mock_csv_response = MagicMock()
    mock_csv_response.raise_for_status.return_value = None
    mock_csv_response.text = MOCK_FRB_CSV_DATA 
    expected_csv_url = "https://www.federalreserve.gov/supervisionreg/files/enforcementactions.csv"
    mock_requests_get = mocker.patch("requests.get", return_value=mock_csv_response)
    mock_download = mocker.patch.object(downloader, 'download_file', return_value=True)
    # Expected downloads based on mock data and "Wells Fargo" search term
    expected_pdf_url_1 = "https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230115a1.pdf"
    expected_filename_1 = "FRB_FRB-23-001_2023-01-15_Consent_Order.pdf" # Filename uses docket, date, type
    expected_pdf_url_2 = "https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230310a1.pdf"
    expected_filename_2 = "FRB_FRB-23-003_2023-03-10_Written_Agreement.pdf"

    # Act
    downloader.search_frb("Wells Fargo")
    # Assert
    mock_requests_get.assert_called_once_with(expected_csv_url, headers=downloader.headers)
    assert mock_download.call_count == 2
    mock_download.assert_any_call(expected_pdf_url_1, expected_filename_1)
    mock_download.assert_any_call(expected_pdf_url_2, expected_filename_2)

# Add more tests for search_frb (e.g., empty CSV, errors)
def test_search_frb_csv_fetch_error(mocker, downloader_instance, caplog):
    """Test search_frb handles RequestException when fetching CSV."""
    # Arrange
    expected_csv_url = "https://www.federalreserve.gov/supervisionreg/files/enforcementactions.csv"
    mock_requests_get = mocker.patch("requests.get", side_effect=requests.exceptions.RequestException("CSV Fetch Failed"))
    mock_download = mocker.patch.object(downloader_instance, 'download_file')

    # Act
    downloader_instance.search_frb("Wells Fargo")

    # Assert
    mock_requests_get.assert_called_once_with(expected_csv_url, headers=downloader_instance.headers)
    mock_download.assert_not_called()
    # Assert log message using caplog - check specifically for the ERROR record
    error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_logs) == 1, f"Expected 1 ERROR log, found {len(error_logs)}"
    record = error_logs[0]
    # Check if event name is in the formatted message
    assert "csv_fetch_failed" in record.message
    # Optional: Check context fields if they become available/necessary
    # assert record.url == expected_csv_url
    # assert "CSV Fetch Failed" in record.error_str # Assuming error string is logged


# --- Tests for run method ---

def test_run_calls_search_methods(mocker, downloader_instance):
    """Test that the run method calls all search methods."""
    # Arrange
    downloader = downloader_instance
    mock_cfpb = mocker.patch.object(downloader, 'search_cfpb') 
    mock_occ = mocker.patch.object(downloader, 'search_occ')   
    mock_frb = mocker.patch.object(downloader, 'search_frb')   

    # Act
    downloader.run() 

    # Assert
    mock_cfpb.assert_called_once()
    mock_occ.assert_called_once()
    mock_frb.assert_called_once_with("Wells Fargo") 


# --- Tests for Helper Methods ---

def test_fetch_and_parse_success(mocker, downloader_instance):
    """Test _fetch_and_parse successfully returns soup."""
    # Arrange
    downloader = downloader_instance
    mock_html = "<html><body>Test</body></html>"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = mock_html
    mock_get = mocker.patch("requests.get", return_value=mock_response)
    test_url = "http://example.com"
    
    # Act
    soup = downloader._fetch_and_parse(test_url)

    # Assert
    assert soup is not None
    assert soup.find("body").text == "Test"
    mock_get.assert_called_once_with(test_url, headers=downloader.headers)

def test_fetch_and_parse_failure(mocker, downloader_instance, caplog):
    """Test _fetch_and_parse returns None on request exception."""
    # Arrange
    mock_get = mocker.patch("requests.get", side_effect=requests.exceptions.RequestException("Failed"))
    test_url = "http://bad-example.com"

    # Act
    soup = downloader_instance._fetch_and_parse(test_url)

    # Assert
    assert soup is None
    mock_get.assert_called_once_with(test_url, headers=downloader_instance.headers)
    # Assert log message using caplog - check specifically for the ERROR record
    error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_logs) == 1, f"Expected 1 ERROR log, found {len(error_logs)}"
    record = error_logs[0]
    assert "fetch_failed" in record.message

def test_find_and_download_pdfs_success(mocker, downloader_instance):
    """Test _find_and_download_pdfs finds links and calls download_file."""
    # Arrange
    downloader = downloader_instance
    mock_soup = BeautifulSoup(MOCK_CFPB_ACTION_DETAIL_HTML, "html.parser") # Reuse some html
    base_url = "https://www.consumerfinance.gov/actions/details/wells-fargo-action-1/"
    agency_prefix = "TEST"
    
    mock_download = mocker.patch.object(downloader, 'download_file', return_value=True)
    # Expected calls derived from MOCK_CFPB_ACTION_DETAIL_HTML
    expected_calls = [
        mocker.call("https://www.consumerfinance.gov/documents/consent-order-1.pdf", "TEST_consent-order-1.pdf"),
        mocker.call("https://www.consumerfinance.gov/actions/details/documents/consent-order-2.pdf", "TEST_consent-order-2.pdf"),
        mocker.call("http://external.com/doc.pdf", "TEST_doc.pdf")
    ]

    # Act
    downloader._find_and_download_pdfs(mock_soup, base_url, agency_prefix)

    # Assert
    assert mock_download.call_count == 3
    mock_download.assert_has_calls(expected_calls, any_order=True)

def test_find_and_download_pdfs_no_soup(mocker, downloader_instance):
    """Test _find_and_download_pdfs handles None soup input."""
    # Arrange
    downloader = downloader_instance
    mock_download = mocker.patch.object(downloader, 'download_file')

    # Act
    downloader._find_and_download_pdfs(None, "http://base.url", "TEST")

    # Assert
    mock_download.assert_not_called()


# Remove the old unittest main guard
# if __name__ == '__main__':
#     unittest.main() 
# // ... potentially remove old class definition ... 