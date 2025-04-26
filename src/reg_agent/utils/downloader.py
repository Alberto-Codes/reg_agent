import csv
import os
import re
from io import StringIO
from pathlib import Path
from typing import List
from urllib.parse import urljoin

import pandas as pd
import requests
import structlog
from bs4 import BeautifulSoup
from tqdm import tqdm

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
        try:
            # Use the specific Wells Fargo search URL
            search_url = "https://www.consumerfinance.gov/enforcement/actions/?title=Wells+Fargo&from_date=&to_date="
            response = requests.get(search_url, headers=self.headers)
            response.raise_for_status()
            log.debug("got_response", status_code=response.status_code)

            soup = BeautifulSoup(response.text, "html.parser")

            # Debug: Print the HTML structure
            log.debug("page_content", content=soup.prettify()[:1000])

            # Try different selectors
            actions = []

            # Try list items
            list_items = soup.find_all("li", class_="m-list_item")
            if list_items:
                actions.extend(list_items)
                log.debug("found_list_items", count=len(list_items))

            # Try article elements
            articles = soup.find_all("article")
            if articles:
                actions.extend(articles)
                log.debug("found_articles", count=len(articles))

            # Try div elements with specific classes
            divs = soup.find_all("div", class_=["o-post-preview", "content-l_col"])
            if divs:
                actions.extend(divs)
                log.debug("found_divs", count=len(divs))

            log.info("found_actions", count=len(actions))

            for action in actions:
                # Try different ways to get the title
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

                if any(term in title_text for term in self.search_terms):
                    log.info("found_matching_action", title=title_text)

                    # Get the action detail page URL - try different approaches
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
                        self.regulatory_sites["CFPB"], action_link["href"]
                    )
                    log.debug("fetching_action_page", url=action_url)

                    # Get the specific action page
                    action_response = requests.get(action_url, headers=self.headers)
                    action_soup = BeautifulSoup(action_response.text, "html.parser")

                    # Look for PDF links in the action page
                    pdf_links = action_soup.find_all(
                        "a", href=lambda x: x and x.endswith(".pdf")
                    )
                    log.debug("found_pdf_links", count=len(pdf_links))

                    for link in pdf_links:
                        pdf_url = urljoin(action_url, link["href"])
                        filename = f"CFPB_{os.path.basename(pdf_url)}"
                        if self.download_file(pdf_url, filename):
                            log.info("successfully_downloaded", filename=filename)
                        else:
                            log.error("failed_to_download", filename=filename)

        except Exception as e:
            log.error("search_failed", error=str(e), error_type=type(e).__name__)

    def search_occ(self):
        """Search OCC enforcement actions for Wells Fargo consent orders."""
        log = self.log.bind(agency="OCC")
        log.info("searching_agency")
        try:
            response = requests.get(self.regulatory_sites["OCC"], headers=self.headers)
            response.raise_for_status()
            log.debug("got_response", status_code=response.status_code)

            soup = BeautifulSoup(response.text, "html.parser")
            # Look for search results
            results = soup.find_all("div", class_="search-result")
            log.info("found_results", count=len(results))

            for result in results:
                title = result.find("h3").text.strip() if result.find("h3") else ""
                log.debug("checking_result", title=title)

                if any(term in title for term in self.search_terms):
                    log.info("found_matching_action", title=title)
                    # Find the link to the enforcement action
                    link = result.find("a")
                    if link:
                        action_url = urljoin(self.regulatory_sites["OCC"], link["href"])
                        try:
                            # Get the enforcement action page
                            action_response = requests.get(
                                action_url, headers=self.headers
                            )
                            action_soup = BeautifulSoup(
                                action_response.text, "html.parser"
                            )
                            # Look for PDF links
                            pdf_links = action_soup.find_all(
                                "a", href=lambda x: x and x.endswith(".pdf")
                            )
                            log.debug("found_pdf_links", count=len(pdf_links))

                            for pdf_link in pdf_links:
                                pdf_url = urljoin(action_url, pdf_link["href"])
                                filename = f"OCC_{os.path.basename(pdf_url)}"
                                self.download_file(pdf_url, filename)
                        except Exception as e:
                            log.error(
                                "action_page_failed", error=str(e), url=action_url
                            )
        except Exception as e:
            log.error("search_failed", error=str(e), error_type=type(e).__name__)

    def search_frb(self, search_term):
        """
        Search for enforcement actions from the Federal Reserve Board using their CSV data.

        Args:
            search_term (str): The term to search for in enforcement actions
        """
        log = self.log.bind(agency="FRB")
        log.info("searching_agency", search_term=search_term)

        try:
            # CSV endpoint for enforcement actions
            csv_url = "https://www.federalreserve.gov/supervisionreg/files/enforcementactions.csv"

            # Download and read the CSV data
            response = requests.get(csv_url, headers=self.headers)
            response.raise_for_status()

            # Parse CSV data
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
                            # Generate a clean filename
                            filename = f"FRB_{docket.replace('/', '_')}_{action_date}_{action_type}.pdf"
                            filename = re.sub(
                                r"[^\w\-_\.]", "_", filename
                            )  # Remove invalid chars

                            if self.download_file(doc_url, filename):
                                log.info("successfully_downloaded", filename=filename)
                            else:
                                log.error("failed_to_download", filename=filename)
                        except Exception as e:
                            log.error(
                                "document_download_failed",
                                error=str(e),
                                error_type=type(e).__name__,
                                url=doc_url,
                            )

        except requests.exceptions.RequestException as e:
            log.error("search_failed", error=str(e), error_type=type(e).__name__)
        except Exception as e:
            log.error("search_failed", error=str(e), error_type=type(e).__name__)

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
