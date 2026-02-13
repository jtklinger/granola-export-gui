"""Test mode with mock data - no authentication required"""
import flet as ft
from datetime import datetime, timedelta
from pathlib import Path
import time
import threading
import base64
import json

# Mock meetings data
MOCK_MEETINGS = [
    {
        'id': 'mock-001',
        'title': 'Q4 Planning Meeting',
        'date': (datetime.now() - timedelta(days=2)).isoformat(),
        'participants': ['John Doe', 'Jane Smith', 'Bob Johnson'],
        'summary': 'Discussed Q4 goals and objectives. Key focus areas: product launch, team expansion, and budget allocation.',
    },
    {
        'id': 'mock-002',
        'title': 'Technical Architecture Review',
        'date': (datetime.now() - timedelta(days=5)).isoformat(),
        'participants': ['Alice Chen', 'David Lee', 'Sarah Wilson'],
        'summary': 'Reviewed current system architecture and proposed improvements for scalability and performance.',
    },
    {
        'id': 'mock-003',
        'title': 'Client Presentation',
        'date': (datetime.now() - timedelta(days=10)).isoformat(),
        'participants': ['Emily Brown', 'Michael Davis'],
        'summary': 'Presented project timeline and deliverables to client. Received positive feedback and approval to proceed.',
    },
    {
        'id': 'mock-004',
        'title': 'Team Retrospective',
        'date': (datetime.now() - timedelta(days=15)).isoformat(),
        'participants': ['Team Lead', 'Developer 1', 'Developer 2', 'Designer'],
        'summary': 'Reflected on last sprint. Identified areas for improvement in communication and process efficiency.',
    },
    {
        'id': 'mock-005',
        'title': 'Budget Review Session',
        'date': (datetime.now() - timedelta(days=20)).isoformat(),
        'participants': ['CFO', 'Department Heads'],
        'summary': 'Analyzed current budget allocation and made adjustments for upcoming quarter.',
    },
]

MOCK_TRANSCRIPT = """Speaker 1: Good morning everyone, thank you for joining today's meeting.

Speaker 2: Happy to be here. Should we dive right into the agenda?

Speaker 1: Yes, let's start with the first item. As you can see from the slides, we've made significant progress on the project timeline.

Speaker 3: The progress looks great. I have a few questions about the implementation details though.

Speaker 1: Of course, feel free to ask anything.

Speaker 3: How are we handling the data migration? That seemed to be a concern last week.

Speaker 2: We've developed a comprehensive migration strategy. Let me walk you through it...

[Continued discussion about technical details and project planning]

Speaker 1: Before we wrap up, are there any other concerns or questions?

Speaker 3: No, I think we covered everything. This was really helpful.

Speaker 2: Agreed. Thanks for organizing this.

Speaker 1: Great, thanks everyone. Let's touch base again next week. Have a great day!

Speaker 2: You too, goodbye!

Speaker 3: Goodbye everyone!"""


class MockAPIClient:
    """Mock API client for test mode"""

    def list_meetings(self, date_range=None, start_date=None, end_date=None):
        """Return mock meetings"""
        time.sleep(0.5)  # Simulate API delay
        return MOCK_MEETINGS.copy()

    def get_meeting_summary(self, meeting_id):
        """Return mock meeting details"""
        time.sleep(0.3)
        for meeting in MOCK_MEETINGS:
            if meeting['id'] == meeting_id:
                return meeting
        return None

    def get_meeting_transcript(self, meeting_id):
        """Return mock transcript"""
        time.sleep(1)  # Simulate longer API delay
        return MOCK_TRANSCRIPT


class MockExportManager:
    """Mock export manager for test mode"""

    def __init__(self, api_client):
        self.api_client = api_client

    def export_single_meeting(self, meeting, output_dir, max_retries=2):
        """Mock export single meeting"""
        time.sleep(2)  # Simulate export time

        # Create file
        filepath = Path(output_dir) / f"{meeting['id']}.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        content = f"""# {meeting['title']}

**Date:** {meeting['date']}
**Meeting ID:** {meeting['id']}
**Participants:** {', '.join(meeting.get('participants', []))}

---

## Summary

{meeting.get('summary', 'No summary available')}

---

## Full Verbatim Transcript

{MOCK_TRANSCRIPT}
"""

        filepath.write_text(content, encoding='utf-8')

        return {
            'meeting_id': meeting['id'],
            'title': meeting['title'],
            'complete': True,
            'filename': filepath.name,
            'error': None,
            'verification': {'complete': True, 'checks': [], 'failures': []}
        }

    def export_meetings(self, meetings, output_dir, progress_callback=None):
        """Mock export multiple meetings"""
        completed = []

        for i, meeting in enumerate(meetings):
            if progress_callback:
                progress_callback(i + 1, len(meetings), f"Exporting: {meeting['title']}")

            result = self.export_single_meeting(meeting, output_dir)
            completed.append(result)

        return {
            'success': True,
            'total': len(meetings),
            'completed': len(completed),
            'failed': 0,
            'failed_meetings': [],
            'output_dir': output_dir
        }


def create_test_app(page: ft.Page):
    """Create test mode app with mock data"""
    from .main_window import GranolaExportApp

    # Build a fake JWT with email claim for display
    _header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b'=').decode()
    _payload = base64.urlsafe_b64encode(json.dumps({
        "email": "test.user@example.com",
        "sub": "test-user-id"
    }).encode()).rstrip(b'=').decode()
    _mock_jwt = f"{_header}.{_payload}.sig"

    # Create mock credential store that returns test email
    mock_credential_store = type('MockCredentialStore', (), {
        'get_config': lambda self, key: 'test.user@example.com' if key == 'user_email' else None,
        'save_config': lambda self, key, value: None,
    })()

    # Create mock components
    mock_oauth = type('MockOAuth', (), {'authenticate': lambda self: None})()
    mock_token_manager = type('MockTokenManager', (), {
        'has_valid_tokens': lambda self: True,
        'get_valid_access_token': lambda self: _mock_jwt,
        'clear_tokens': lambda self: None,
        'credential_store': mock_credential_store,
    })()

    mock_api_client = MockAPIClient()
    mock_export_manager = MockExportManager(mock_api_client)

    # Add test mode banner
    page.overlay.append(
        ft.Container(
            content=ft.Text(
                "[TEST MODE] Using mock data - No real API calls",
                size=14,
                weight=ft.FontWeight.BOLD,
                text_align=ft.TextAlign.CENTER,
                color="orange"
            ),
            bgcolor="rgba(255, 165, 0, 0.2)",
            padding=10,
            border=ft.border.all(2, "orange"),
        )
    )

    # Create main app with mock components
    app = GranolaExportApp(
        page,
        oauth_manager=mock_oauth,
        token_manager=mock_token_manager,
        api_client=mock_api_client,
        export_manager=mock_export_manager
    )

    # Override auth display with test mode indicator
    app.auth_screen.set_authenticated("test.user@example.com [TEST MODE]")
    app.fetch_button.disabled = False
    page.update()
