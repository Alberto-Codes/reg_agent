# src/reg_agent/auth/http_auth.py
import httpx

from reg_agent.auth.token_manager import ImpersonatedTokenManager


# --- Dynamic Bearer Token Authentication for httpx ---
class DynamicBearerAuth(httpx.Auth):
    """Custom httpx Auth class to fetch a token dynamically before requests."""

    def __init__(self, token_manager: ImpersonatedTokenManager):
        self._token_manager = token_manager

    def auth_flow(self, request: httpx.Request):
        token = self._token_manager.get_token()  # Get fresh token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
