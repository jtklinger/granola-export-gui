"""Export progress display components"""
import asyncio
import flet as ft

class ExportProgress:
    """Manages export progress display"""

    def __init__(self, page: ft.Page):
        """
        Initialize progress display

        Args:
            page: Flet page instance
        """
        self.page = page
        self.build_ui()

    def _push_update(self):
        """Schedule a UI update on the Flet event loop.

        Calling page.update() from a background thread sets control state
        but doesn't wake the Flutter renderer on Windows. Scheduling via
        run_task ensures the event loop processes a frame and repaints.
        """
        async def _do():
            self.page.update()
        try:
            self.page.run_task(_do)
        except Exception:
            # Fallback to sync update if event loop unavailable
            self.page.update()

    def build_ui(self):
        """Build progress UI"""
        # Progress bar
        self.progress_bar = ft.ProgressBar(
            value=0,
            visible=False,
            expand=True
        )

        # Status text
        self.status_text = ft.Text(
            "Ready to export",
            size=12,
            color="grey600"
        )

        # Current meeting text
        self.current_meeting_text = ft.Text(
            "",
            size=12,
            color="grey700",
            visible=False
        )

        # Rate limit indicator
        self.rate_limit_text = ft.Text(
            "",
            size=12,
            color="amber",
            visible=False
        )

        # Cancel button (shown during rate limit waits)
        self.cancel_button = ft.ElevatedButton(
            "Cancel Export",
            icon=ft.Icons.CANCEL,
            color="red",
            on_click=self._on_cancel_click,
            visible=False
        )
        self.on_cancel = None  # callback set by main_window

        # Verification status
        self.verification_text = ft.Text(
            "",
            size=12,
            visible=False
        )

    def start_export(self, total: int):
        """
        Start export progress display

        Args:
            total: Total number of meetings
        """
        self.progress_bar.value = 0
        self.progress_bar.visible = True
        self.current_meeting_text.visible = True
        self.verification_text.visible = True
        self.cancel_button.visible = True
        self.cancel_button.disabled = False
        self.cancel_button.text = "Cancel Export"
        self.status_text.value = f"Starting export of {total} meetings..."
        self.status_text.color = "blue"
        self._push_update()

    def update_progress(self, current: int, total: int, meeting_title: str):
        """
        Update progress display

        Args:
            current: Current meeting number
            total: Total meetings
            meeting_title: Title of current meeting
        """
        progress = current / total if total > 0 else 0
        self.progress_bar.value = progress

        self.current_meeting_text.value = (
            f"Exporting meeting {current} of {total}: {meeting_title}"
        )

        self.verification_text.value = "⏳ Fetching and verifying..."
        self.verification_text.color = "blue"

        self._push_update()

    def update_verification(self, status: str, color: str = "grey700"):
        """
        Update verification status

        Args:
            status: Verification status message
            color: Text color
        """
        self.verification_text.value = status
        self.verification_text.color = color
        self._push_update()

    def complete_success(self, total: int, output_dir: str):
        """
        Show successful completion

        Args:
            total: Total meetings exported
            output_dir: Output directory path
        """
        self.progress_bar.value = 1.0
        self.status_text.value = (
            f"✓ Export SUCCESSFUL: All {total} meetings exported to {output_dir}"
        )
        self.status_text.color = "green"
        self.verification_text.value = "✓ All transcripts verified complete"
        self.verification_text.color = "green"
        self.rate_limit_text.visible = False
        self.cancel_button.visible = False
        self._push_update()

    def complete_failure(self, failed_count: int, total: int, failures: list):
        """
        Show failure completion

        Args:
            failed_count: Number of failed meetings
            total: Total meetings attempted
            failures: List of failure dictionaries
        """
        self.status_text.value = (
            f"✗ Export FAILED: {failed_count} of {total} meetings incomplete"
        )
        self.status_text.color = "red"

        # Build failure details
        failure_details = []
        for failure in failures:
            title = failure.get('title', 'Unknown')
            error = failure.get('error', 'Unknown error')
            verification = failure.get('verification', {})

            if verification:
                failures_list = verification.get('failures', [])
                failure_details.append(f"• {title}: {', '.join(failures_list)}")
            else:
                failure_details.append(f"• {title}: {error}")

        self.verification_text.value = "\n".join(failure_details[:5])  # Show first 5
        self.verification_text.color = "red"
        self.rate_limit_text.visible = False
        self.cancel_button.visible = False
        self._push_update()

    def _on_cancel_click(self, e):
        """Handle cancel button click"""
        if self.on_cancel:
            self.on_cancel()
        self.cancel_button.disabled = True
        self.cancel_button.text = "Cancelling..."
        self._push_update()

    def show_rate_limit(self, seconds_remaining: int, total_wait: int,
                        attempt: int = 1, max_attempts: int = 3):
        """Show rate limit countdown with attempt info"""
        if seconds_remaining > 0:
            self.rate_limit_text.value = (
                f"⚠ Rate limited by API — waiting {seconds_remaining}s "
                f"(attempt {attempt}/{max_attempts}, {total_wait}s backoff)"
            )
            self.rate_limit_text.visible = True
            self.cancel_button.visible = True
        else:
            self.rate_limit_text.value = f"⚠ Retrying (attempt {attempt}/{max_attempts})..."
            self.rate_limit_text.visible = True
        self._push_update()

    def show_cooldown(self, seconds_remaining: int, total_wait: int):
        """Show cooldown countdown between meetings"""
        if seconds_remaining > 0:
            self.rate_limit_text.value = (
                f"Cooldown between fetches — {seconds_remaining}s remaining"
            )
            self.rate_limit_text.visible = True
            self.rate_limit_text.color = "blue"
        else:
            self.rate_limit_text.value = "Fetching next meeting..."
            self.rate_limit_text.color = "blue"
        self._push_update()

    def hide_rate_limit(self):
        """Hide rate limit indicator and cancel button"""
        self.rate_limit_text.visible = False
        self.rate_limit_text.color = "amber"
        self.cancel_button.visible = False
        self.cancel_button.disabled = False
        self.cancel_button.text = "Cancel Export"
        self._push_update()

    def start_fetch(self):
        """Show indeterminate progress for meeting fetch"""
        self.progress_bar.value = None  # indeterminate
        self.progress_bar.visible = True
        self.status_text.value = "Fetching meetings..."
        self.status_text.color = "blue"
        self.rate_limit_text.visible = False
        self._push_update()

    def end_fetch(self):
        """Hide fetch progress"""
        self.progress_bar.visible = False
        self.rate_limit_text.visible = False
        self._push_update()

    def show_cancelled(self):
        """Show cancellation status"""
        self.status_text.value = "Export cancelled by user"
        self.status_text.color = "orange"
        self.rate_limit_text.visible = False
        self.cancel_button.visible = False
        self.cancel_button.disabled = False
        self.cancel_button.text = "Cancel Export"
        self._push_update()

    def hide(self):
        """Hide progress display"""
        self.progress_bar.visible = False
        self.current_meeting_text.visible = False
        self.verification_text.visible = False
        self.rate_limit_text.visible = False
        self.cancel_button.visible = False
        self.cancel_button.disabled = False
        self.cancel_button.text = "Cancel Export"
        self.status_text.value = "Ready to export"
        self.status_text.color = "grey600"
        self._push_update()

    def get_container(self) -> ft.Column:
        """
        Get progress container

        Returns:
            Flet column with progress UI
        """
        return ft.Column([
            self.progress_bar,
            self.current_meeting_text,
            ft.Row([self.rate_limit_text, self.cancel_button], spacing=10),
            self.verification_text,
            self.status_text,
        ], spacing=5)
