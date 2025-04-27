# src/reg_agent/auth/token_manager.py
import datetime
from typing import Optional, Tuple

import google.auth
import google.auth.impersonated_credentials
import google.auth.transport.requests
import google.oauth2.service_account
import structlog

log = structlog.get_logger()

# Default token lifetime (slightly less than 1 hour default)
DEFAULT_LIFETIME_SECONDS = 3300  # 55 minutes
# Refresh buffer (refresh if token expires within this time)
REFRESH_BUFFER = datetime.timedelta(minutes=5)


class ImpersonatedTokenManager:
    """
    Manages short-lived impersonated access tokens for a target service account.

    Uses the caller's ADC to generate tokens for the target SA.
    Requires the caller to have 'roles/iam.serviceAccountTokenCreator' on the target SA.
    Can accept either the target SA's name or full email address.
    """

    def __init__(
        self,
        target_service_account_name_or_email: str,  # Renamed parameter
        scopes: Optional[list[str]] = None,
        lifetime_seconds: int = DEFAULT_LIFETIME_SECONDS,
    ):
        """
        Initializes the manager.

        Args:
            target_service_account_name_or_email: Name (e.g., 'my-sa') or full email
                address (e.g., 'my-sa@project.iam.gserviceaccount.com') of the
                service account to impersonate.
            scopes: List of OAuth 2.0 scopes for the generated token. Defaults to cloud-platform.
            lifetime_seconds: Requested lifetime for the generated token. Max is 3600.
        """
        if not target_service_account_name_or_email:
            raise ValueError("target_service_account_name_or_email cannot be empty.")

        # Get source credentials and project ID first
        self._source_credentials, self._project_id = google.auth.default(
            scopes=scopes or ["https://www.googleapis.com/auth/cloud-platform"]
        )

        # Determine the full target service account email
        if "@" in target_service_account_name_or_email:
            self.target_service_account = target_service_account_name_or_email
        else:
            # Construct email from name and project ID
            if not self._project_id:
                log.error(
                    "Could not determine project ID from source credentials to construct target SA email."
                )
                raise ValueError(
                    "Cannot construct target SA email: Project ID unknown and only SA name provided."
                )
            self.target_service_account = f"{target_service_account_name_or_email}@{self._project_id}.iam.gserviceaccount.com"
            log.info(
                "Constructed target SA email from name and project ID",
                provided_name=target_service_account_name_or_email,
                project_id=self._project_id,
                constructed_email=self.target_service_account,
            )

        self.scopes = scopes or ["https://www.googleapis.com/auth/cloud-platform"]
        self.lifetime_seconds = min(lifetime_seconds, 3600)
        self._cached_token: Optional[str] = None
        self._token_expiry: Optional[datetime.datetime] = None

        log.info(
            "ImpersonatedTokenManager initialized",
            target_sa=self.target_service_account,
            caller_sa=getattr(
                self._source_credentials, "service_account_email", "user_credentials"
            ),
            caller_project_id=self._project_id,
            lifetime_sec=self.lifetime_seconds,
            scopes=self.scopes,
        )

    def _is_token_valid(self) -> bool:
        """Checks if the cached token exists and is not expired (with buffer)."""
        if not self._cached_token or not self._token_expiry:
            return False
        # Check if expiry is beyond the current time plus buffer
        return (self._token_expiry - REFRESH_BUFFER) > datetime.datetime.now(
            datetime.timezone.utc
        )

    def _generate_new_token(self) -> Tuple[str, datetime.datetime]:
        """Generates a new impersonated access token."""
        log.info(
            "Generating new impersonated access token",
            target_sa=self.target_service_account,
        )
        try:
            # Create impersonated credentials
            impersonated_creds = google.auth.impersonated_credentials.Credentials(
                source_credentials=self._source_credentials,
                target_principal=self.target_service_account,
                target_scopes=self.scopes,
                lifetime=self.lifetime_seconds,
            )
            # Refresh the impersonated credentials to get the token
            request = google.auth.transport.requests.Request()
            impersonated_creds.refresh(request)

            if not impersonated_creds.token or not impersonated_creds.expiry:
                log.error(
                    "Failed to obtain token/expiry from impersonated credentials."
                )
                raise RuntimeError("Could not generate impersonated token.")

            log.info(
                "Successfully generated new impersonated token",
                expiry=impersonated_creds.expiry,
            )
            return impersonated_creds.token, impersonated_creds.expiry
        except Exception as e:
            log.error(
                "Failed to generate impersonated token. "
                "Ensure caller has 'Service Account Token Creator' role on target SA.",
                target_sa=self.target_service_account,
                caller_sa=getattr(
                    self._source_credentials,
                    "service_account_email",
                    "user_credentials",
                ),
                error=str(e),
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to generate token for {self.target_service_account}"
            ) from e

    def get_token(self) -> str:
        """
        Returns a valid access token, refreshing if necessary.

        Returns:
            A valid OAuth 2.0 access token string.

        Raises:
            RuntimeError: If token generation fails.
        """
        if self._is_token_valid() and self._cached_token:
            log.debug("Using cached impersonated token.")
            return self._cached_token
        else:
            log.info("Cached token invalid or missing, generating new token.")
            self._cached_token, self._token_expiry = self._generate_new_token()
            return self._cached_token


# Example usage (for testing if run directly)
async def _test_token_manager():
    import asyncio

    load_dotenv()  # Load .env for TARGET_SA_NAME_OR_EMAIL
    target_sa_input = os.getenv("TARGET_SA_NAME_OR_EMAIL")  # Updated env var name
    if not target_sa_input:
        print("Skipping test: TARGET_SA_NAME_OR_EMAIL environment variable not set.")
        return

    # Basic logging setup
    import logging

    structlog.configure(
        processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    # Clear existing handlers to avoid duplication if script is reloaded
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    log.info("Testing ImpersonatedTokenManager...")
    try:
        # Use the updated parameter name
        manager = ImpersonatedTokenManager(
            target_service_account_name_or_email=target_sa_input, lifetime_seconds=60
        )
        token1 = manager.get_token()
        print(
            f"Got token 1 targeting {manager.target_service_account}: {token1[:10]}...{token1[-10:]}"
        )
        print("Waiting for 30 seconds...")
        await asyncio.sleep(30)
        token2 = manager.get_token()
        print(
            f"Got token 2 targeting {manager.target_service_account}: {token2[:10]}...{token2[-10:]}"
        )
        print(f"Token 1 == Token 2: {token1 == token2}")  # Should be True

        print("Waiting for 40 seconds (should exceed lifetime + buffer)...")
        await asyncio.sleep(40)
        token3 = manager.get_token()
        print(
            f"Got token 3 targeting {manager.target_service_account}: {token3[:10]}...{token3[-10:]}"
        )
        print(f"Token 1 == Token 3: {token1 == token3}")  # Should be False

        log.info("ImpersonatedTokenManager test successful.")

    except Exception:
        log.error("ImpersonatedTokenManager test failed.", exc_info=True)


if __name__ == "__main__":
    import asyncio
    import os

    from dotenv import load_dotenv

    asyncio.run(_test_token_manager())
