"""Token refresh management with rotation support"""
import threading
import time
from typing import Optional, Dict
import logging
import requests
from .credential_store import CredentialStore

logger = logging.getLogger(__name__)

# Granola OAuth token endpoint
TOKEN_URL = "https://mcp-auth.granola.ai/oauth2/token"


class TokenManager:
    """Manages OAuth token lifecycle with rotation support"""

    def __init__(self, client_id: Optional[str] = None):
        """
        Initialize token manager

        Args:
            client_id: OAuth client ID (from dynamic registration)
        """
        self.client_id = client_id
        self.credential_store = CredentialStore()

        # Thread safety for refresh
        self._refresh_lock = threading.Lock()

        # Token state
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at: float = 0

        # Load existing tokens
        self._load_tokens()

    def _load_tokens(self) -> None:
        """Load tokens from credential store"""
        tokens = self.credential_store.get_tokens("granola_user")
        if tokens:
            self._access_token = tokens.get('access_token')
            self._refresh_token = tokens.get('refresh_token')
            self._expires_at = tokens.get('expires_at', 0)
            logger.info("Loaded existing tokens from credential store")

    def _save_tokens(self, tokens: Dict[str, any]) -> None:
        """
        Save tokens to credential store

        CRITICAL: Must save new refresh token immediately.
        Granola may use single-use refresh tokens.

        Args:
            tokens: Token dictionary from OAuth response
        """
        expires_in = tokens.get('expires_in', 3600)
        expires_at = time.time() + expires_in

        token_data = {
            'access_token': tokens['access_token'],
            'refresh_token': tokens.get('refresh_token', self._refresh_token),
            'expires_at': expires_at,
            'token_type': tokens.get('token_type', 'Bearer')
        }

        self._access_token = token_data['access_token']
        self._refresh_token = token_data['refresh_token']
        self._expires_at = token_data['expires_at']

        self.credential_store.save_tokens("granola_user", token_data)
        logger.info(f"Tokens saved. Expires in {expires_in}s")

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or will expire within 60s"""
        return time.time() >= (self._expires_at - 60)

    def _refresh_tokens(self) -> None:
        """
        Refresh access token using refresh token

        CRITICAL: Save new refresh token immediately before using access token.
        """
        if not self._refresh_token:
            raise ValueError("No refresh token available. User must re-authenticate.")

        if not self.client_id:
            # Try loading from credential store
            self.client_id = self.credential_store.get_config('granola_client_id')
            if not self.client_id:
                raise ValueError("No client_id available for token refresh.")

        data = {
            'client_id': self.client_id,
            'grant_type': 'refresh_token',
            'refresh_token': self._refresh_token
        }

        logger.info("Refreshing access token...")
        response = requests.post(TOKEN_URL, data=data)
        response.raise_for_status()

        tokens = response.json()

        # Save immediately before using
        self._save_tokens(tokens)
        logger.info("Token refresh successful")

    def get_valid_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary

        Returns:
            Valid access token

        Raises:
            ValueError: If no tokens available
            requests.HTTPError: If refresh fails
        """
        if not self._access_token:
            raise ValueError("No access token available. User must authenticate.")

        if self._is_token_expired():
            with self._refresh_lock:
                # Double-check after acquiring lock
                if self._is_token_expired():
                    self._refresh_tokens()

        return self._access_token

    def set_initial_tokens(self, tokens: Dict[str, any]) -> None:
        """
        Set initial tokens from OAuth flow

        Args:
            tokens: Token dictionary from OAuth response
        """
        self._save_tokens(tokens)

    def clear_tokens(self) -> None:
        """Clear all tokens (logout)"""
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0
        self.credential_store.delete_tokens("granola_user")
        logger.info("Tokens cleared")

    def has_valid_tokens(self) -> bool:
        """Check if valid tokens exist"""
        return bool(self._refresh_token)
