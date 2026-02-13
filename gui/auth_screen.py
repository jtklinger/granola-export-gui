"""Authentication screen components"""
import flet as ft
import logging

logger = logging.getLogger(__name__)

class AuthScreen:
    """Manages authentication UI"""

    def __init__(self, page: ft.Page, on_auth_success, on_logout):
        """
        Initialize auth screen

        Args:
            page: Flet page instance
            on_auth_success: Callback when authentication succeeds
            on_logout: Callback when user logs out
        """
        self.page = page
        self.on_auth_success = on_auth_success
        self.on_logout = on_logout

        self.user_email = None
        self.is_authenticated = False

        # Build UI components
        self.build_ui()

    def build_ui(self):
        """Build authentication UI"""
        # Login button
        self.login_button = ft.ElevatedButton(
            "Login with Granola",
            icon="login",
            on_click=self._handle_login,
            width=200,
            height=40
        )

        # Status text
        self.auth_status = ft.Text(
            "Not authenticated",
            size=12,
            color="grey600"
        )

        # Logout button (initially hidden)
        self.logout_button = ft.TextButton(
            "Logout",
            icon="logout",
            on_click=self._handle_logout,
            visible=False
        )

    def _handle_login(self, e):
        """Handle login button click"""
        self.auth_status.value = "Opening browser for authentication..."
        self.login_button.disabled = True
        self.page.update()

        try:
            # Trigger authentication (handled by parent)
            self.on_auth_success()
        except Exception as ex:
            logger.error(f"Login failed: {str(ex)}")
            self.auth_status.value = f"Login failed: {str(ex)}"
            self.auth_status.color = "red"
            self.login_button.disabled = False
            self.page.update()

    def _handle_logout(self, e):
        """Handle logout button click"""
        self.on_logout()
        self.set_unauthenticated()

    def set_authenticated(self, user_email: str):
        """
        Update UI for authenticated state

        Args:
            user_email: User's email address
        """
        self.user_email = user_email
        self.is_authenticated = True

        self.auth_status.value = f"✓ Authenticated as {user_email}"
        self.auth_status.color = "green"
        self.login_button.visible = False
        self.logout_button.visible = True

        self.page.update()

    def set_unauthenticated(self):
        """Update UI for unauthenticated state"""
        self.user_email = None
        self.is_authenticated = False

        self.auth_status.value = "Not authenticated"
        self.auth_status.color = "grey600"
        self.login_button.visible = True
        self.login_button.disabled = False
        self.logout_button.visible = False

        self.page.update()

    def get_container(self) -> ft.Container:
        """
        Get auth screen container

        Returns:
            Flet container with auth UI
        """
        return ft.Container(
            content=ft.Column([
                ft.Text("Authentication", size=16, weight=ft.FontWeight.BOLD),
                ft.Row([
                    self.login_button,
                    self.logout_button,
                ], spacing=10),
                self.auth_status,
            ], spacing=8),
            padding=10,
            border=ft.border.all(1, "grey300"),
            border_radius=8
        )
