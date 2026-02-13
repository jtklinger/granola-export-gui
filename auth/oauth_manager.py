"""OAuth 2.0 + PKCE flow with dynamic client registration for Granola"""
import hashlib
import base64
import json
import secrets
import socket
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, parse_qs, urlparse
from typing import Optional, Dict
import threading
import logging
import requests

from .credential_store import CredentialStore

logger = logging.getLogger(__name__)

# Granola OAuth discovery URL
OAUTH_DISCOVERY_URL = "https://mcp-auth.granola.ai/.well-known/oauth-authorization-server"

# Resource identifier for token scoping
GRANOLA_RESOURCE = "https://mcp.granola.ai/"


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback"""

    auth_code: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        """Handle OAuth callback"""
        query = parse_qs(urlparse(self.path).query)

        if 'code' in query:
            CallbackHandler.auth_code = query['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1>Authentication Successful!</h1>
                    <p>You can close this window and return to the application.</p>
                </body>
                </html>
            """)
        elif 'error' in query:
            CallbackHandler.error = query['error'][0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_msg = CallbackHandler.error
            self.wfile.write(f"""
                <html>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1>Authentication Failed</h1>
                    <p>Error: {error_msg}</p>
                    <p>You can close this window.</p>
                </body>
                </html>
            """.encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress log messages"""
        pass


class OAuthManager:
    """Manages OAuth 2.0 authentication with PKCE and dynamic client registration"""

    APP_NAME = "Granola Export GUI"
    # Fixed callback port so redirect URI is consistent with registered client
    CALLBACK_PORT = 19872

    def __init__(self):
        """Initialize OAuth manager. Endpoints and client_id are discovered/registered automatically."""
        self.credential_store = CredentialStore()

        # These are populated by _discover_endpoints()
        self.authorize_url = None
        self.token_url = None
        self.registration_url = None
        self.client_id = None

    def _get_callback_port(self) -> int:
        """Get the callback port, using fixed port if available or finding a free one.

        If the fixed port is in use, clears the stored client_id so the client
        will be re-registered with the new port's redirect URI.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', self.CALLBACK_PORT))
            return self.CALLBACK_PORT
        except OSError:
            logger.warning(
                f"Fixed callback port {self.CALLBACK_PORT} is in use, "
                "finding a free port and re-registering client"
            )
            # Clear stored client_id since it's bound to the old port
            self.credential_store.save_config('granola_client_id', '')
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', 0))
                return s.getsockname()[1]

    def _discover_endpoints(self) -> None:
        """Fetch OAuth server metadata from Granola's discovery endpoint"""
        logger.info(f"Fetching OAuth metadata from {OAUTH_DISCOVERY_URL}")

        response = requests.get(OAUTH_DISCOVERY_URL)
        response.raise_for_status()

        metadata = response.json()

        self.authorize_url = metadata['authorization_endpoint']
        self.token_url = metadata['token_endpoint']
        self.registration_url = metadata.get('registration_endpoint')

        logger.info(f"OAuth endpoints discovered:")
        logger.info(f"  authorize: {self.authorize_url}")
        logger.info(f"  token: {self.token_url}")
        logger.info(f"  register: {self.registration_url}")

    def _register_client(self, redirect_uri: str) -> str:
        """
        Dynamically register this application as an OAuth client (RFC 7591)

        Args:
            redirect_uri: The callback URI to register

        Returns:
            The dynamically assigned client_id
        """
        # Check if we already have a registered client_id and stored redirect URI matches
        stored_client_id = self.credential_store.get_config('granola_client_id')
        stored_redirect_uri = self.credential_store.get_config('granola_redirect_uri')
        if stored_client_id and stored_redirect_uri == redirect_uri:
            logger.info(f"Using stored client_id: {stored_client_id}")
            return stored_client_id
        elif stored_client_id and stored_redirect_uri != redirect_uri:
            logger.info(f"Stored redirect URI mismatch (stored={stored_redirect_uri}, "
                        f"current={redirect_uri}), re-registering client")

        if not self.registration_url:
            raise Exception(
                "Granola's OAuth server does not support dynamic client registration. "
                "Cannot proceed without a client ID."
            )

        logger.info(f"Registering new OAuth client at {self.registration_url}")

        registration_data = {
            'client_name': self.APP_NAME,
            'redirect_uris': [redirect_uri],
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
            'token_endpoint_auth_method': 'none',  # Public client (no secret)
        }

        response = requests.post(
            self.registration_url,
            json=registration_data
        )
        response.raise_for_status()

        result = response.json()
        client_id = result['client_id']

        # Persist for future use
        self.credential_store.save_config('granola_client_id', client_id)
        self.credential_store.save_config('granola_redirect_uri', redirect_uri)
        logger.info(f"Client registered successfully: {client_id} with redirect_uri: {redirect_uri}")

        return client_id

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """
        Generate PKCE code verifier and challenge

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode('utf-8').rstrip('=')

        challenge_bytes = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

        return code_verifier, code_challenge

    def authenticate(self) -> Dict[str, str]:
        """
        Perform full OAuth authentication:
        1. Discover endpoints
        2. Register client (if needed)
        3. PKCE authorization flow
        4. Exchange code for tokens

        Returns:
            Dictionary containing access_token, refresh_token, etc.

        Raises:
            Exception: If authentication fails
        """
        # Step 1: Discover endpoints
        self._discover_endpoints()

        # Step 2: Get callback port and build redirect URI
        port = self._get_callback_port()
        redirect_uri = f"http://localhost:{port}/callback"

        # Step 3: Register client (or use cached registration)
        self.client_id = self._register_client(redirect_uri)

        # Step 4: Generate PKCE pair
        code_verifier, code_challenge = self._generate_pkce_pair()

        # Reset callback handler state
        CallbackHandler.auth_code = None
        CallbackHandler.error = None

        # Step 5: Start local callback server
        server = HTTPServer(('localhost', port), CallbackHandler)
        server_thread = threading.Thread(target=lambda: server.handle_request())
        server_thread.daemon = True
        server_thread.start()

        # Step 6: Build authorization URL
        auth_params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'scope': 'email offline_access openid profile',
            'prompt': 'consent',
            'resource': GRANOLA_RESOURCE,
        }

        auth_url = f"{self.authorize_url}?{urlencode(auth_params)}"

        logger.info("Opening browser for authentication...")
        logger.info(f"If browser doesn't open, visit: {auth_url}")
        webbrowser.open(auth_url)

        # Step 7: Wait for callback
        server_thread.join(timeout=300)  # 5 minute timeout

        if CallbackHandler.error:
            raise Exception(f"OAuth error: {CallbackHandler.error}")

        if not CallbackHandler.auth_code:
            raise Exception("Authentication timeout or cancelled")

        # Step 8: Exchange code for tokens
        return self._exchange_code_for_tokens(
            CallbackHandler.auth_code, code_verifier, redirect_uri
        )

    def _exchange_code_for_tokens(
        self, auth_code: str, code_verifier: str, redirect_uri: str
    ) -> Dict[str, str]:
        """
        Exchange authorization code for access/refresh tokens

        Args:
            auth_code: Authorization code from callback
            code_verifier: PKCE code verifier
            redirect_uri: Redirect URI used in authorization request

        Returns:
            Token dictionary
        """
        token_data = {
            'client_id': self.client_id,
            'code': auth_code,
            'code_verifier': code_verifier,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri
        }

        logger.info(f"Exchanging authorization code for tokens at {self.token_url}")

        response = requests.post(self.token_url, data=token_data)
        response.raise_for_status()

        tokens = response.json()
        logger.info(f"Token exchange successful. Expires in: {tokens.get('expires_in', 'unknown')}s")

        return tokens

    def get_client_id(self) -> Optional[str]:
        """Get the current or stored client_id"""
        if self.client_id:
            return self.client_id
        return self.credential_store.get_config('granola_client_id')


def decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload without verification (for display purposes only)"""
    try:
        payload = token.split('.')[1]
        # Add padding for base64
        padding = 4 - len(payload) % 4
        payload += '=' * padding
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}
