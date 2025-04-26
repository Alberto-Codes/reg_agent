# import sys # No longer using unittest, sys import likely unnecessary
# import unittest # No longer using unittest
import pytest  # Using pytest now
from pathlib import Path
from unittest.mock import MagicMock # Can keep MagicMock if needed for complex mocks, but try to avoid.
import requests # Need this for exception testing
import pandas as pd
from io import StringIO
import csv

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
    return ConsentOrderDownloader()

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
    expected_filepath = downloader_instance.output_dir / test_filename

    # Act
    result = downloader_instance.download_file(test_url, test_filename)

    # Assert
    assert result is True
    mock_requests_get.assert_called_once_with(test_url, stream=True, headers=downloader_instance.headers)
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

    # Act
    result = downloader_instance.download_file(test_url, test_filename)

    # Assert
    assert result is False
    mock_requests_get.assert_called_once_with(test_url, stream=True, headers=downloader_instance.headers)
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
    """Test search_cfpb finds a matching action and calls download_file."""
    # Arrange
    mock_search_response = MagicMock()
    mock_search_response.raise_for_status.return_value = None
    mock_search_response.text = MOCK_CFPB_SEARCH_HTML

    mock_detail_response = MagicMock()
    mock_detail_response.raise_for_status.return_value = None
    mock_detail_response.text = MOCK_CFPB_ACTION_DETAIL_HTML

    # Mock requests.get to return different responses based on URL
    def mock_get(*args, **kwargs):
        url = args[0]
        if "consumerfinance.gov/enforcement/actions/?title=Wells+Fargo" in url:
            return mock_search_response
        elif "consumerfinance.gov/actions/details/wells-fargo-action-1/" in url:
            return mock_detail_response
        else:
            raise requests.exceptions.RequestException(f"Unexpected URL: {url}")

    mock_requests_get = mocker.patch("requests.get", side_effect=mock_get)
    
    # Mock the instance's download_file method
    mock_download = mocker.patch.object(downloader_instance, 'download_file', return_value=True)

    # Expected URLs and filenames
    expected_detail_url = "https://www.consumerfinance.gov/actions/details/wells-fargo-action-1/"
    expected_pdf_url_1 = "https://www.consumerfinance.gov/documents/consent-order-1.pdf"
    expected_pdf_url_2 = "https://www.consumerfinance.gov/actions/details/documents/consent-order-2.pdf"
    expected_pdf_url_3 = "http://external.com/doc.pdf"
    expected_filename_1 = "CFPB_consent-order-1.pdf"
    expected_filename_2 = "CFPB_consent-order-2.pdf"
    expected_filename_3 = "CFPB_doc.pdf"

    # Act
    downloader_instance.search_cfpb()

    # Assert
    # Check requests.get calls
    assert mock_requests_get.call_count == 2
    mock_requests_get.assert_any_call(
        "https://www.consumerfinance.gov/enforcement/actions/?title=Wells+Fargo&from_date=&to_date=", 
        headers=downloader_instance.headers
    )
    mock_requests_get.assert_any_call(expected_detail_url, headers=downloader_instance.headers)

    # Check download_file calls
    assert mock_download.call_count == 3
    mock_download.assert_any_call(expected_pdf_url_1, expected_filename_1)
    mock_download.assert_any_call(expected_pdf_url_2, expected_filename_2)
    mock_download.assert_any_call(expected_pdf_url_3, expected_filename_3)


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
    """Test search_occ finds a matching action and calls download_file."""
    # Arrange
    mock_search_response = MagicMock()
    mock_search_response.raise_for_status.return_value = None
    mock_search_response.text = MOCK_OCC_SEARCH_HTML

    mock_detail_response = MagicMock()
    mock_detail_response.raise_for_status.return_value = None
    mock_detail_response.text = MOCK_OCC_ACTION_DETAIL_HTML

    # Mock requests.get
    def mock_get(*args, **kwargs):
        url = args[0]
        if "occ.gov/search/index.html?q=wells+fargo+enforcement+action" in url:
            return mock_search_response
        elif "occ.gov/topics/enforcement-actions/ea2023-050.html" in url:
            return mock_detail_response
        else:
            raise requests.exceptions.RequestException(f"Unexpected OCC URL: {url}")

    mock_requests_get = mocker.patch("requests.get", side_effect=mock_get)
    
    # Mock download_file
    mock_download = mocker.patch.object(downloader_instance, 'download_file', return_value=True)

    # Expected URLs and filenames
    expected_detail_url = "https://occ.gov/topics/enforcement-actions/ea2023-050.html"
    expected_pdf_url = "https://occ.gov/static/publications/ea2023-050.pdf"
    expected_filename = "OCC_ea2023-050.pdf"

    # Act
    downloader_instance.search_occ()

    # Assert
    # Check requests.get calls
    assert mock_requests_get.call_count == 2
    mock_requests_get.assert_any_call(downloader_instance.regulatory_sites["OCC"], headers=downloader_instance.headers)
    mock_requests_get.assert_any_call(expected_detail_url, headers=downloader_instance.headers)

    # Check download_file call
    mock_download.assert_called_once_with(expected_pdf_url, expected_filename)


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
    mock_csv_response = MagicMock()
    mock_csv_response.raise_for_status.return_value = None
    # Set the text attribute directly
    mock_csv_response.text = MOCK_FRB_CSV_DATA 

    # Mock requests.get for the CSV URL
    expected_csv_url = "https://www.federalreserve.gov/supervisionreg/files/enforcementactions.csv"
    mock_requests_get = mocker.patch("requests.get", return_value=mock_csv_response)

    # Mock download_file
    mock_download = mocker.patch.object(downloader_instance, 'download_file', return_value=True)

    # Expected downloads based on mock data and "Wells Fargo" search term
    expected_pdf_url_1 = "https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230115a1.pdf"
    expected_filename_1 = "FRB_FRB-23-001_2023-01-15_Consent_Order.pdf" # Filename uses docket, date, type
    expected_pdf_url_2 = "https://www.federalreserve.gov/newsevents/pressreleases/files/enf20230310a1.pdf"
    expected_filename_2 = "FRB_FRB-23-003_2023-03-10_Written_Agreement.pdf"

    # Act
    downloader_instance.search_frb("Wells Fargo")

    # Assert
    # Check requests.get call
    mock_requests_get.assert_called_once_with(expected_csv_url, headers=downloader_instance.headers)

    # Check download_file calls
    assert mock_download.call_count == 2
    mock_download.assert_any_call(expected_pdf_url_1, expected_filename_1)
    mock_download.assert_any_call(expected_pdf_url_2, expected_filename_2)

# Add more tests for search_frb (e.g., empty CSV, errors)

# Remove the old unittest main guard
# if __name__ == '__main__':
#     unittest.main() 
# // ... potentially remove old class definition ... 