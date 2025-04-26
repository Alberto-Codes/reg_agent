from reg_agent.utils.downloader import ConsentOrderDownloader

__version__ = "0.1.0"
__all__ = ["ConsentOrderDownloader"]

def main() -> None:
    downloader = ConsentOrderDownloader()
    downloader.run()