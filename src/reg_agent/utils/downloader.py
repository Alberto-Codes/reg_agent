import csv
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
import structlog
from bs4 import BeautifulSoup

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
)
logger = structlog.get_logger()


class ConsentOrderDownloader:
    def __init__(self, output_dir="data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.log = logger.bind(component="downloader")

        # Wells Fargo specific URLs and identifiers
        self.regulatory_sites = {
            "CFPB": "https://www.consumerfinance.gov/enforcement/actions/",
            "OCC": "https://occ.gov/search/index.html?q=wells+fargo+enforcement+action",
            "FRB": "https://www.federalreserve.gov/apps/enforcementactions/",
        }

        self.search_terms = ["Wells Fargo", "Wells Fargo Bank", "Wells Fargo & Company"]

        # Add headers to mimic a browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    # --- NEW HELPER METHODS ---
    def _fetch_and_parse(self, url):
        """Fetches a URL, checks status, and returns a BeautifulSoup object."""
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()  # Check for HTTP errors
            return BeautifulSoup(response.text, "html.parser")
        except requests.exceptions.RequestException as e:
            self.log.error(
                "fetch_failed", url=url, error=str(e), error_type=type(e).__name__
            )
            return None  # Return None on failure

    def _find_and_download_pdfs(self, soup, base_url, agency_prefix):
        """Finds PDF links in a BeautifulSoup object and downloads them."""
        if not soup:
            return  # Don't proceed if parsing failed

        pdf_links = soup.find_all("a", href=lambda x: x and x.lower().endswith(".pdf"))
        self.log.debug("found_pdf_links", count=len(pdf_links), base_url=base_url)

        for link in pdf_links:
            pdf_url = urljoin(base_url, link["href"])
            # Basic filename cleaning (can be expanded)
            base_filename = os.path.basename(pdf_url)
            safe_filename = re.sub(r"[^\w\-_\.]", "_", base_filename)
            filename = f"{agency_prefix}_{safe_filename}"

            if self.download_file(pdf_url, filename):
                self.log.info(
                    "successfully_downloaded", filename=filename, source_url=pdf_url
                )
            else:
                self.log.error(
                    "failed_to_download_pdf", filename=filename, pdf_url=pdf_url
                )

    # --- END NEW HELPER METHODS ---

    def download_file(self, url, filename):
        """Download a file from a URL and save it to the output directory."""
        log = self.log.bind(url=url, filename=filename)
        try:
            log.info("attempting_download")
            response = requests.get(url, stream=True, headers=self.headers)
            response.raise_for_status()

            file_path = self.output_dir / filename
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            log.info("download_successful")
            return True
        except requests.exceptions.RequestException as e:
            log.error("download_failed", error=str(e), error_type=type(e).__name__)
            return False

    def search_cfpb(self):
        """Search CFPB enforcement actions for Wells Fargo consent orders."""
        log = self.log.bind(agency="CFPB")
        log.info("searching_agency")
        # Use the specific Wells Fargo search URL
        search_url = "https://www.consumerfinance.gov/enforcement/actions/?title=Wells+Fargo&from_date=&to_date="

        soup = self._fetch_and_parse(search_url)
        if not soup:
            return  # Exit if initial fetch failed

        # Try different selectors
        actions = []
        list_items = soup.find_all("li", class_="m-list_item")
        if list_items:
            actions.extend(list_items)
        articles = soup.find_all("article")
        if articles:
            actions.extend(articles)
        divs = soup.find_all("div", class_=["o-post-preview", "content-l_col"])
        if divs:
            actions.extend(divs)

        log.info("found_potential_actions", count=len(actions))

        for action in actions:
            title = None
            title_candidates = [
                action.find("h3"),
                action.find("h3", class_="o-post-preview__title"),
                action.find("a", class_="m-list_link"),
            ]
            for candidate in title_candidates:
                if candidate and candidate.text.strip():
                    title = candidate
                    break
            if not title:
                continue

            title_text = title.text.strip()
            log.debug("checking_action", title=title_text)

            if any(term.lower() in title_text.lower() for term in self.search_terms):
                log.info("found_matching_action", title=title_text)
                action_link = None
                link_candidates = [
                    title.find("a"),
                    action.find("a"),
                    title if title.name == "a" else None,
                ]
                for candidate in link_candidates:
                    if candidate and candidate.get("href"):
                        action_link = candidate
                        break
                if not action_link:
                    continue

                action_url = urljoin(
                    search_url, action_link["href"]
                )  # Use search_url as base
                log.debug("fetching_action_page", url=action_url)

                # Fetch detail page and download PDFs using helpers
                action_soup = self._fetch_and_parse(action_url)
                self._find_and_download_pdfs(action_soup, action_url, "CFPB")

    def search_occ(self):
        """Search OCC enforcement actions for Wells Fargo consent orders."""
        log = self.log.bind(agency="OCC")
        log.info("searching_agency")
        search_url = self.regulatory_sites["OCC"]

        soup = self._fetch_and_parse(search_url)
        if not soup:
            return  # Exit if initial fetch failed

        results = soup.find_all("div", class_="search-result")
        log.info("found_results", count=len(results))

        for result in results:
            title_tag = result.find("h3")
            title = title_tag.text.strip() if title_tag else ""
            log.debug("checking_result", title=title)

            if any(term.lower() in title.lower() for term in self.search_terms):
                log.info("found_matching_action", title=title)
                link = result.find("a")
                if link and link.get("href"):
                    action_url = urljoin(
                        search_url, link["href"]
                    )  # Use search_url as base
                    log.debug("fetching_action_page", url=action_url)

                    # Fetch detail page and download PDFs using helpers
                    action_soup = self._fetch_and_parse(action_url)
                    self._find_and_download_pdfs(action_soup, action_url, "OCC")

    def search_frb(self, search_term):
        """Search FRB enforcement actions using their CSV data."""
        log = self.log.bind(agency="FRB")
        log.info("searching_agency", search_term=search_term)

        try:
            csv_url = "https://www.federalreserve.gov/supervisionreg/files/enforcementactions.csv"
            response = requests.get(
                csv_url, headers=self.headers
            )  # Keep direct request here for now
            response.raise_for_status()
            csv_data = response.text.splitlines()
            reader = csv.DictReader(csv_data)
            actions = list(reader)
            log.info("found_actions", count=len(actions))

            for action in actions:
                title = action.get("Institution Name", "")
                docket = action.get("Docket Number", "")
                action_type = action.get("Action Type", "")
                action_date = action.get("Action Date", "")
                doc_url = action.get("URL", "")

                log.debug(
                    "checking_action",
                    title=title,
                    docket=docket,
                    action_type=action_type,
                )

                if any(term.lower() in title.lower() for term in self.search_terms):
                    log.info(
                        "found_matching_action",
                        title=title,
                        docket=docket,
                        action_type=action_type,
                        action_date=action_date,
                    )

                    if doc_url and doc_url.lower().endswith(".pdf"):
                        try:
                            # Keep FRB specific filename logic for now
                            filename = f"FRB_{docket.replace('/', '_')}_{action_date}_{action_type}.pdf"
                            filename = re.sub(r"[^\w\-_\.]", "_", filename)
                            if self.download_file(doc_url, filename):
                                log.info("successfully_downloaded", filename=filename)
                            else:
                                log.error(
                                    "failed_to_download", filename=filename, url=doc_url
                                )  # Add URL
                        except Exception as e:
                            log.error(
                                "document_download_failed",
                                error=str(e),
                                error_type=type(e).__name__,
                                url=doc_url,
                            )
        except requests.exceptions.RequestException as e:
            log.error(
                "csv_fetch_failed",
                url=csv_url,
                error=str(e),
                error_type=type(e).__name__,
            )
        except Exception as e:
            # Catch potential CSV parsing errors etc.
            log.error(
                "frb_search_processing_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    def run(self):
        """Run the downloader to search and download enforcement actions."""
        self.log.info("starting_search")

        # Search each agency
        self.search_cfpb()
        self.search_occ()
        self.search_frb("Wells Fargo")  # Pass the institution name

        self.log.info("finished_search")


def main():
    downloader = ConsentOrderDownloader()
    downloader.run()


if __name__ == "__main__":
    main()
