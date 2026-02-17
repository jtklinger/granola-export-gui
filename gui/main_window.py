"""Main application window integrating all components"""
import flet as ft
from datetime import datetime, timedelta
import os
from pathlib import Path
from tkinter import filedialog
import tkinter as tk
import logging

from .auth_screen import AuthScreen
from .export_progress import ExportProgress
from auth.oauth_manager import decode_jwt_claims
from api.client import CancelledError, RateLimitError

logger = logging.getLogger(__name__)

class GranolaExportApp:
    """Main application class"""

    def __init__(self, page: ft.Page, oauth_manager, token_manager, api_client, export_manager):
        """
        Initialize application

        Args:
            page: Flet page instance
            oauth_manager: OAuthManager instance
            token_manager: TokenManager instance
            api_client: GranolaAPIClient instance
            export_manager: ExportManager instance
        """
        self.page = page
        self.oauth_manager = oauth_manager
        self.token_manager = token_manager
        self.api_client = api_client
        self.export_manager = export_manager

        # Page configuration
        self.page.title = "Granola Export Tool"
        self.page.window.width = 900
        self.page.window.height = 800
        self.page.padding = 25
        self.page.scroll = ft.ScrollMode.AUTO

        # State
        self.export_path = str(Path.home() / "granola_exports")
        self.date_range = "last_30_days"
        self.custom_start = None
        self.custom_end = None
        self.meetings = []
        self.selected_meetings = set()
        self.is_exporting = False

        # Build UI
        self.build_ui()

        # Check if already authenticated
        self.check_existing_auth()

    def build_ui(self):
        """Build the main UI"""
        # Header with exit button
        header = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text("Granola Meeting Export", size=28, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Export your meeting transcripts with summaries and verification",
                        size=14,
                        color="grey600"
                    ),
                ], spacing=4, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    tooltip="Exit application",
                    on_click=lambda e: self.page.run_task(self.page.window.close),
                ),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            margin=ft.margin.only(bottom=24)
        )

        # Authentication section
        self.auth_screen = AuthScreen(
            self.page,
            on_auth_success=self.handle_authentication,
            on_logout=self.handle_logout
        )

        # Date Range Selection
        date_range_section = self.build_date_range_section()

        # Export Location
        export_location_section = self.build_export_location_section()

        # Meeting List
        self.meeting_list_section = self.build_meeting_list_section()

        # Action Buttons
        self.action_buttons = self.build_action_buttons()

        # Progress Display
        self.progress_display = ExportProgress(self.page)

        # Wire up rate limit indicator from API client to progress display
        self.api_client.on_rate_limit = self.progress_display.show_rate_limit

        # Wire up cooldown indicator from export manager to progress display
        self.export_manager.on_cooldown = self.progress_display.show_cooldown

        # Wire up cancel button
        self.progress_display.on_cancel = self._cancel_export

        # Wrap everything in a scrollable column
        main_column = ft.Column(
            [
                header,
                self.auth_screen.get_container(),
                ft.Container(height=24),
                ft.Divider(height=1, color="grey300"),
                ft.Container(height=16),
                date_range_section,
                ft.Container(height=24),
                export_location_section,
                ft.Container(height=24),
                ft.Divider(height=1, color="grey300"),
                ft.Container(height=16),
                self.meeting_list_section,
                ft.Container(height=24),
                self.action_buttons,
                ft.Container(height=8),
                self.progress_display.get_container(),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            expand=True
        )

        # Add main column to page
        self.page.add(main_column)
        self.page.update()

    def build_date_range_section(self):
        """Date range selection"""
        # Date labels for showing selected custom dates
        self.start_date_label = ft.Text("No start date selected", size=12, color="grey600")
        self.end_date_label = ft.Text("No end date selected", size=12, color="grey600")

        def on_start_date_picked(e):
            picked = e.control.value
            if picked:
                self.custom_start = picked
                self.start_date_label.value = f"Start: {picked.strftime('%Y-%m-%d')}"
                self.start_date_label.color = "black"
                self.page.update()

        def on_end_date_picked(e):
            picked = e.control.value
            if picked:
                self.custom_end = picked
                self.end_date_label.value = f"End: {picked.strftime('%Y-%m-%d')}"
                self.end_date_label.color = "black"
                self.page.update()

        self.start_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime.now(),
            on_change=on_start_date_picked,
        )
        self.end_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime.now(),
            on_change=on_end_date_picked,
        )

        # Add pickers to page overlay so show_dialog can find them
        self.page.overlay.append(self.start_date_picker)
        self.page.overlay.append(self.end_date_picker)

        # Custom date pickers (initially hidden)
        self.start_date_button = ft.ElevatedButton(
            "Pick start date",
            icon="calendar_today",
            on_click=lambda e: self.page.show_dialog(self.start_date_picker)
        )
        self.end_date_button = ft.ElevatedButton(
            "Pick end date",
            icon="calendar_today",
            on_click=lambda e: self.page.show_dialog(self.end_date_picker)
        )

        self.custom_date_row = ft.Column(
            [
                ft.Row([self.start_date_button, self.start_date_label], spacing=10),
                ft.Row([self.end_date_button, self.end_date_label], spacing=10),
            ],
            spacing=8,
            visible=False
        )

        def on_date_range_change(e):
            self.date_range = e.control.value
            self.custom_date_row.visible = (self.date_range == "custom")
            self.page.update()

        self.date_range_group = ft.RadioGroup(
            value="last_30_days",
            on_change=on_date_range_change,
            content=ft.Column([
                ft.Radio(value="last_week", label="Last 7 days"),
                ft.Radio(value="last_30_days", label="Last 30 days (recommended)"),
                ft.Radio(value="this_month", label="This month"),
                ft.Radio(value="last_month", label="Last month"),
                ft.Radio(value="this_year", label="This year"),
                ft.Radio(value="last_year", label="Last year"),
                ft.Radio(value="custom", label="Custom range"),
            ], spacing=8)
        )

        return ft.Column([
            ft.Text("Date Range", size=16, weight=ft.FontWeight.BOLD),
            self.date_range_group,
            self.custom_date_row,
        ], spacing=8)

    def build_export_location_section(self):
        """Export location selector"""
        self.location_text = ft.Text(
            self.export_path,
            size=12,
            color="grey700",
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
            tooltip=self.export_path
        )

        def pick_folder(e):
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes('-topmost', 1)

            folder = filedialog.askdirectory(
                title="Select Export Folder",
                initialdir=self.export_path
            )

            if folder:
                self.export_path = folder
                self.location_text.value = folder
                self.location_text.tooltip = folder
                self.page.update()

        self.browse_button = ft.TextButton("Browse...", on_click=pick_folder)

        return ft.Column([
            ft.Row([
                ft.Text("Export Location", size=16, weight=ft.FontWeight.BOLD),
                self.browse_button,
            ]),
            ft.Container(
                content=self.location_text,
                padding=10,
                border=ft.border.all(1, "grey300"),
                border_radius=8,
            )
        ], spacing=8)

    def build_meeting_list_section(self):
        """Meeting list with checkboxes"""
        self.meeting_list_container = ft.Column(
            [ft.Text(
                "Please authenticate and click 'Fetch Meetings' to load your meetings",
                color="grey600",
                italic=True
            )],
            spacing=4,
            scroll=ft.ScrollMode.AUTO
        )

        self.select_all_button = ft.TextButton(
            "Select All",
            on_click=lambda e: self.select_all_meetings(True)
        )
        self.deselect_all_button = ft.TextButton(
            "Deselect All",
            on_click=lambda e: self.select_all_meetings(False)
        )

        return ft.Column([
            ft.Row([
                ft.Text("Meetings", size=16, weight=ft.FontWeight.BOLD),
                self.select_all_button,
                self.deselect_all_button,
            ], spacing=8),
            ft.Container(
                content=self.meeting_list_container,
                border=ft.border.all(1, "grey300"),
                border_radius=8,
                padding=15,
                expand=True,
            )
        ], spacing=8)

    def build_action_buttons(self):
        """Main action buttons"""
        self.fetch_button = ft.ElevatedButton(
            "Fetch Meetings",
            icon="download",
            on_click=self.fetch_meetings,
            disabled=True  # Enable after authentication
        )

        self.export_button = ft.ElevatedButton(
            "Export Selected",
            icon="upload",
            on_click=self.export_meetings,
            disabled=True  # Enable after fetching
        )

        def on_verbose_change(e):
            root = logging.getLogger()
            if e.control.value:
                root.setLevel(logging.DEBUG)
                self.debug_checkbox.value = False
                logger.info("Logging set to VERBOSE (DEBUG)")
            else:
                root.setLevel(logging.WARNING)
                logger.info("Logging set to WARNING")
            self.page.update()

        def on_debug_change(e):
            root = logging.getLogger()
            if e.control.value:
                root.setLevel(logging.DEBUG)
                self.verbose_checkbox.value = False
                for handler in root.handlers:
                    handler.setLevel(logging.DEBUG)
                logger.debug("Logging set to DEBUG (all messages)")
            else:
                root.setLevel(logging.INFO)
                logger.info("Logging set to INFO")
            self.page.update()

        self.verbose_checkbox = ft.Checkbox(
            label="Verbose",
            value=False,
            on_change=on_verbose_change,
        )
        self.debug_checkbox = ft.Checkbox(
            label="Debug",
            value=False,
            on_change=on_debug_change,
        )

        return ft.Row([
            self.fetch_button,
            self.export_button,
            ft.Container(expand=True),
            ft.Row([
                ft.Icon(ft.Icons.BUG_REPORT, size=16, color="grey500"),
                self.verbose_checkbox,
                self.debug_checkbox,
            ], spacing=4),
        ], spacing=10)

    def _extract_email_from_tokens(self, tokens: dict) -> str:
        """Extract user email from token response (tries id_token, then access_token)"""
        # OIDC id_token contains user claims (email, name, sub)
        for token_key in ('id_token', 'access_token'):
            token = tokens.get(token_key)
            if token:
                claims = decode_jwt_claims(token)
                email = claims.get('email')
                if email:
                    return email
        return claims.get('sub', 'Authenticated User') if claims else 'Authenticated User'

    def check_existing_auth(self):
        """Check if user already has valid tokens"""
        if self.token_manager.has_valid_tokens():
            # Try stored email first, fall back to token decode
            stored_email = self.token_manager.credential_store.get_config('user_email')
            if stored_email:
                email = stored_email
            else:
                try:
                    token = self.token_manager.get_valid_access_token()
                    claims = decode_jwt_claims(token)
                    email = claims.get('email') or claims.get('sub', 'Authenticated User')
                except Exception:
                    email = "Authenticated User"
            self.auth_screen.set_authenticated(email)
            self.fetch_button.disabled = False
            self.page.update()

    def handle_authentication(self):
        """Handle authentication flow"""
        def auth_thread():
            try:
                # Perform OAuth flow (discovery + registration + PKCE)
                tokens = self.oauth_manager.authenticate()

                # Update token manager with client_id from registration
                self.token_manager.client_id = self.oauth_manager.client_id

                # Extract email from token response (id_token has OIDC claims)
                email = self._extract_email_from_tokens(tokens)

                # Set tokens in token manager
                self.token_manager.set_initial_tokens(tokens)

                # Persist email for future sessions
                self.token_manager.credential_store.save_config('user_email', email)

                # Update UI
                self.auth_screen.set_authenticated(email)
                self.fetch_button.disabled = False
                self.page.update()

            except Exception as e:
                logger.error(f"Authentication failed: {str(e)}")
                self.auth_screen.auth_status.value = f"Authentication failed: {self._friendly_error(e)}"
                self.auth_screen.auth_status.color = "red"
                self.auth_screen.login_button.disabled = False
                self.page.update()

        self.page.run_thread(auth_thread)

    def handle_logout(self):
        """Handle logout"""
        self.token_manager.clear_tokens()
        self.meetings = []
        self.selected_meetings.clear()
        self.update_meeting_list()
        self.fetch_button.disabled = True
        self.export_button.disabled = True
        self.page.update()

    def _friendly_error(self, ex: Exception) -> str:
        """Map common exceptions to user-friendly messages"""
        msg = str(ex).lower()
        if "rate limit" in msg:
            return "Rate limited by Granola API. Please wait a few minutes and try again."
        if "connection" in msg or "timeout" in msg:
            return "Could not connect to Granola. Check your internet connection."
        if "401" in msg or "unauthorized" in msg:
            return "Authentication expired. Please log out and log back in."
        raw = str(ex)
        return raw[:150] if len(raw) > 150 else raw

    def _set_controls_enabled(self, enabled: bool):
        """Enable or disable interactive controls during fetch/export operations"""
        disabled = not enabled
        self.date_range_group.disabled = disabled
        self.browse_button.disabled = disabled
        self.select_all_button.disabled = disabled
        self.deselect_all_button.disabled = disabled
        for entry in getattr(self, 'meeting_rows', {}).values():
            entry['checkbox'].disabled = disabled

    def _cancel_export(self):
        """Cancel the current export/fetch operation"""
        self.api_client.cancelled = True
        logger.info("User requested cancellation")

    def select_all_meetings(self, select: bool):
        """Select or deselect all meetings"""
        if select:
            self.selected_meetings = set(m['id'] for m in self.meetings)
        else:
            self.selected_meetings.clear()
        self.update_meeting_list()

    def fetch_meetings(self, e):
        """Fetch meetings from Granola API"""
        if self.date_range == "custom":
            if not self.custom_start or not self.custom_end:
                self.progress_display.status_text.value = "Please select both start and end dates"
                self.progress_display.status_text.color = "red"
                self.page.update()
                return
            if self.custom_start > self.custom_end:
                self.progress_display.status_text.value = "Start date must be before end date"
                self.progress_display.status_text.color = "red"
                self.page.update()
                return

        def fetch_thread():
            try:
                self.api_client.cancelled = False
                self._set_controls_enabled(False)
                self.progress_display.start_fetch()
                self.fetch_button.disabled = True
                self.page.update()

                # Fetch meetings with custom dates if applicable
                if self.date_range == "custom" and self.custom_start and self.custom_end:
                    self.meetings = self.api_client.list_meetings(
                        date_range="custom",
                        start_date=self.custom_start.isoformat(),
                        end_date=self.custom_end.isoformat()
                    )
                else:
                    self.meetings = self.api_client.list_meetings(self.date_range)

                # Update UI
                self.update_meeting_list()

                self.progress_display.status_text.value = (
                    f"Found {len(self.meetings)} meetings"
                )
                self.progress_display.status_text.color = "green"
                self.export_button.disabled = len(self.meetings) == 0

            except CancelledError:
                logger.info("Fetch cancelled by user")
                self.progress_display.show_cancelled()

            except Exception as ex:
                logger.error(f"Error fetching meetings: {str(ex)}")
                self.progress_display.status_text.value = self._friendly_error(ex)
                self.progress_display.status_text.color = "red"

            finally:
                self.progress_display.end_fetch()
                self._set_controls_enabled(True)
                self.fetch_button.disabled = False
                self.page.update()

        self.page.run_thread(fetch_thread)

    def update_meeting_list(self):
        """Update the meeting list display"""
        self.meeting_rows = {}  # meeting_id -> Row control for status updates

        if not self.meetings:
            self.meeting_list_container.controls = [
                ft.Text("No meetings found", color="grey600", italic=True)
            ]
        else:
            rows = []
            for meeting in self.meetings:
                meeting_id = meeting.get('id')
                title = meeting.get('title', 'Untitled')
                date = meeting.get('date', 'Unknown date')

                # Format date
                try:
                    date_obj = datetime.fromisoformat(date.replace('Z', '+00:00'))
                    date_str = date_obj.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = date

                def make_handler(mid):
                    def handler(e):
                        if e.control.value:
                            self.selected_meetings.add(mid)
                        else:
                            self.selected_meetings.discard(mid)
                    return handler

                checkbox = ft.Checkbox(
                    label=f"{title} ({date_str})",
                    value=meeting_id in self.selected_meetings,
                    on_change=make_handler(meeting_id)
                )

                status_icon = ft.Icon(
                    ft.Icons.CIRCLE_OUTLINED,
                    size=14,
                    color="grey400",
                    visible=False
                )

                row = ft.Row([checkbox, status_icon], spacing=4)
                self.meeting_rows[meeting_id] = {
                    'row': row,
                    'checkbox': checkbox,
                    'status_icon': status_icon,
                }
                rows.append(row)

            self.meeting_list_container.controls = rows

        self.page.update()

    def _mark_meeting_status(self, meeting_id: str, success: bool, char_count: int = 0):
        """Update a meeting row to show export result (green check or red X) and char count"""
        entry = self.meeting_rows.get(meeting_id)
        if not entry:
            return
        icon = entry['status_icon']
        checkbox = entry['checkbox']
        if success:
            icon.icon = ft.Icons.CHECK_CIRCLE
            icon.color = "green"
            checkbox.label_style = ft.TextStyle(color="green")
        else:
            icon.icon = ft.Icons.CANCEL
            icon.color = "red"
            checkbox.label_style = ft.TextStyle(color="red")
        icon.visible = True

        # Append character count to the label
        if char_count > 0:
            char_color = "amber" if char_count < 10000 else "green"
            label_base = checkbox.label
            checkbox.label = f"{label_base} \u2014 {char_count:,} chars"
            # Add a char count text next to the row
            char_text = ft.Text(
                f"{char_count:,} chars",
                size=12,
                color=char_color,
                weight=ft.FontWeight.W_500,
            )
            entry['row'].controls.append(char_text)

        self.progress_display._push_update()

    def export_meetings(self, e):
        """Export selected meetings"""
        if not self.selected_meetings:
            self.progress_display.status_text.value = "No meetings selected!"
            self.progress_display.status_text.color = "red"
            self.page.update()
            return

        if self.is_exporting:
            return

        self.is_exporting = True

        def export_thread():
            try:
                self.api_client.cancelled = False
                self._set_controls_enabled(False)

                # Get selected meetings
                selected = [m for m in self.meetings if m['id'] in self.selected_meetings]

                # Start progress
                self.progress_display.start_export(len(selected))
                self.fetch_button.disabled = True
                self.export_button.disabled = True
                self.page.update()

                # Progress callback
                def progress_callback(current, total, status_msg):
                    meeting_title = status_msg.replace("Exporting: ", "")
                    self.progress_display.update_progress(current, total, meeting_title)

                # Export meetings
                result = self.export_manager.export_meetings(
                    selected,
                    self.export_path,
                    progress_callback=progress_callback,
                    result_callback=self._mark_meeting_status
                )

                # Show results
                if result['success']:
                    self.progress_display.complete_success(
                        result['total'],
                        result['output_dir']
                    )
                else:
                    self.progress_display.complete_failure(
                        result['failed'],
                        result['total'],
                        result['failed_meetings']
                    )

            except CancelledError:
                logger.info("Export cancelled by user")
                self.progress_display.show_cancelled()

            except Exception as ex:
                logger.error(f"Export error: {str(ex)}")
                self.progress_display.status_text.value = self._friendly_error(ex)
                self.progress_display.status_text.color = "red"
                self.page.update()

            finally:
                self.is_exporting = False
                self._set_controls_enabled(True)
                self.fetch_button.disabled = False
                self.export_button.disabled = False
                self.page.update()

        self.page.run_thread(export_thread)
