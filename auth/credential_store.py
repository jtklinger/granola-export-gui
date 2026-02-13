"""Secure credential storage using OS keyring"""
import keyring
import json
from typing import Optional, Dict

SERVICE_NAME = "granola_export_gui"

class CredentialStore:
    """Manages secure storage of OAuth tokens using OS keyring"""

    @staticmethod
    def save_tokens(user_email: str, tokens: Dict[str, str]) -> None:
        """
        Save tokens to OS keyring

        Args:
            user_email: User's email (used as username)
            tokens: Dictionary containing access_token, refresh_token, etc.
        """
        keyring.set_password(
            SERVICE_NAME,
            user_email,
            json.dumps(tokens)
        )

    @staticmethod
    def get_tokens(user_email: str) -> Optional[Dict[str, str]]:
        """
        Retrieve tokens from OS keyring

        Args:
            user_email: User's email

        Returns:
            Dictionary of tokens or None if not found
        """
        try:
            token_json = keyring.get_password(SERVICE_NAME, user_email)
            if token_json:
                return json.loads(token_json)
        except Exception:
            pass
        return None

    @staticmethod
    def delete_tokens(user_email: str) -> None:
        """
        Delete tokens from OS keyring

        Args:
            user_email: User's email
        """
        try:
            keyring.delete_password(SERVICE_NAME, user_email)
        except Exception:
            pass

    @staticmethod
    def save_config(key: str, value: str) -> None:
        """
        Save configuration value

        Args:
            key: Config key
            value: Config value
        """
        keyring.set_password(SERVICE_NAME, f"config_{key}", value)

    @staticmethod
    def get_config(key: str) -> Optional[str]:
        """
        Get configuration value

        Args:
            key: Config key

        Returns:
            Config value or None
        """
        try:
            return keyring.get_password(SERVICE_NAME, f"config_{key}")
        except Exception:
            return None
