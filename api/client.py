"""Granola API client using MCP protocol"""
import re
import json
import time
import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised when the user cancels an operation during a rate limit wait."""
    pass


class RateLimitError(Exception):
    """Raised when rate limit retries are exhausted. Should not be retried."""
    pass


# MCP endpoint
MCP_URL = "https://mcp.granola.ai/mcp"

# Date ranges natively supported by the MCP list_meetings tool
MCP_NATIVE_RANGES = {"this_week", "last_week", "last_30_days"}


class GranolaAPIClient:
    """Client for Granola API via MCP protocol (JSON-RPC over HTTP)"""

    def __init__(self, token_manager):
        self.token_manager = token_manager
        self.session = requests.Session()
        self._mcp_initialized = False
        self._request_id = 0
        self.on_rate_limit = None  # callback(seconds_remaining, total_wait)
        self.cancelled = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _get_headers(self) -> Dict[str, str]:
        access_token = self.token_manager.get_valid_access_token()
        return {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
        }

    def _mcp_call(self, method: str, params: Optional[dict] = None) -> dict:
        """Send a JSON-RPC request to the MCP server and return the result."""
        msg = {'jsonrpc': '2.0', 'method': method, 'id': self._next_id()}
        if params is not None:
            msg['params'] = params

        response = self.session.post(MCP_URL, headers=self._get_headers(), json=msg, timeout=60)
        response.raise_for_status()

        # Parse SSE-formatted response
        for line in response.text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'error' in data:
                    raise Exception(f"MCP error: {data['error'].get('message', data['error'])}")
                return data.get('result', {})

        # Non-SSE JSON response
        if response.headers.get('content-type', '').startswith('application/json'):
            data = response.json()
            if 'error' in data:
                raise Exception(f"MCP error: {data['error'].get('message', data['error'])}")
            return data.get('result', {})

        raise Exception(f"Unexpected MCP response: {response.text[:200]}")

    def _mcp_notify(self, method: str, params: Optional[dict] = None):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            msg['params'] = params
        self.session.post(MCP_URL, headers=self._get_headers(), json=msg, timeout=10)

    def _ensure_initialized(self):
        """Initialize MCP session if not already done."""
        if self._mcp_initialized:
            return
        self._mcp_call('initialize', {
            'protocolVersion': '2025-03-26',
            'capabilities': {},
            'clientInfo': {'name': 'granola-export-gui', 'version': '1.0.0'}
        })
        self._mcp_notify('notifications/initialized')
        self._mcp_initialized = True
        logger.info("MCP session initialized")

    def reset_session(self):
        """Reset MCP session so the next call reinitializes."""
        self._mcp_initialized = False
        self.session = requests.Session()
        logger.info("MCP session reset")

    def _call_tool(self, tool_name: str, arguments: dict, max_retries: int = 5) -> str:
        """Call an MCP tool and return the text content.

        Retries with exponential backoff on rate limits.
        Raises RateLimitError (not generic Exception) when retries exhausted.
        """
        self._ensure_initialized()
        # Granola free API has a strict rate limit (~1 transcript per 5-10min).
        # Escalating delays give the limit time to reset; cancel button lets users bail.
        delays = [120, 180, 300, 420, 600]

        for attempt in range(max_retries + 1):
            result = self._mcp_call('tools/call', {
                'name': tool_name,
                'arguments': arguments,
            })
            content = result.get('content', [])
            texts = [c.get('text', '') for c in content if c.get('type') == 'text']
            text = '\n'.join(texts)

            # Detect rate limit responses
            if 'rate limit' in text.lower() and len(text) < 200:
                if attempt < max_retries:
                    delay = delays[min(attempt, len(delays) - 1)]
                    logger.warning(f"Rate limited on {tool_name}, waiting {delay}s (attempt {attempt + 1}/{max_retries + 1})")
                    # Countdown with callback, check for cancellation each second
                    for remaining in range(delay, 0, -1):
                        if self.cancelled:
                            raise CancelledError("Export cancelled by user")
                        if self.on_rate_limit:
                            self.on_rate_limit(remaining, delay, attempt + 1, max_retries + 1)
                        time.sleep(1)
                    if self.cancelled:
                        raise CancelledError("Export cancelled by user")
                    if self.on_rate_limit:
                        self.on_rate_limit(0, delay, attempt + 1, max_retries + 1)
                    continue
                else:
                    raise RateLimitError(f"Rate limited after {max_retries + 1} attempts: {text}")

            return text

        return text

    @staticmethod
    def _parse_date_range(date_range: str) -> tuple[Optional[str], Optional[str]]:
        """Convert a date range preset to (start_iso_date, end_iso_date) for custom MCP queries."""
        now = datetime.now()

        if date_range == "this_month":
            start = now.replace(day=1)
            return start.strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d')
        elif date_range == "last_month":
            first_of_this_month = now.replace(day=1)
            last_month_end = first_of_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            return last_month_start.strftime('%Y-%m-%d'), last_month_end.strftime('%Y-%m-%d')
        elif date_range == "this_year":
            start = now.replace(month=1, day=1)
            return start.strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d')
        elif date_range == "last_year":
            start = now.replace(year=now.year - 1, month=1, day=1)
            end = now.replace(month=1, day=1) - timedelta(days=1)
            return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

        return None, None

    @staticmethod
    def _parse_meetings_xml(xml_text: str) -> List[Dict]:
        """Parse the XML-like response from list_meetings/get_meetings into dicts."""
        meetings = []
        for match in re.finditer(
            r'<meeting\s+id="([^"]+)"\s+title="([^"]+)"\s+date="([^"]+)"',
            xml_text
        ):
            meeting = {
                'id': match.group(1),
                'title': match.group(2),
                'date': match.group(3),
            }

            # Extract participants
            block_end = xml_text.find('</meeting>', match.end())
            block = xml_text[match.end():block_end] if block_end > 0 else ''

            participants_match = re.search(
                r'<known_participants>(.*?)</known_participants>', block, re.DOTALL
            )
            if participants_match:
                names = [
                    line.strip() for line in participants_match.group(1).strip().split('\n')
                    if line.strip()
                ]
                meeting['participants'] = names

            # Extract summary if present
            summary_match = re.search(r'<summary>(.*?)</summary>', block, re.DOTALL)
            if summary_match:
                meeting['summary'] = summary_match.group(1).strip()

            # Extract private notes if present
            notes_match = re.search(r'<private_notes>(.*?)</private_notes>', block, re.DOTALL)
            if notes_match:
                meeting['private_notes'] = notes_match.group(1).strip()

            meetings.append(meeting)

        return meetings

    def list_meetings(self, date_range: str = "last_30_days",
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict]:
        """List meetings within date range via MCP."""
        # Build MCP tool arguments
        if start_date and end_date:
            args = {'time_range': 'custom', 'custom_start': start_date, 'custom_end': end_date}
        elif date_range in MCP_NATIVE_RANGES:
            args = {'time_range': date_range}
        else:
            # Convert preset to custom date range
            custom_start, custom_end = self._parse_date_range(date_range)
            if custom_start and custom_end:
                args = {'time_range': 'custom', 'custom_start': custom_start, 'custom_end': custom_end}
            else:
                args = {'time_range': 'last_30_days'}

        logger.info(f"Fetching meetings via MCP: {args}")
        text = self._call_tool('list_meetings', args)
        meetings = self._parse_meetings_xml(text)
        logger.info(f"Retrieved {len(meetings)} meetings")
        return meetings

    def get_meeting_summary(self, meeting_id: str) -> Dict:
        """Get meeting details including AI summary via MCP."""
        logger.info(f"Fetching summary for meeting: {meeting_id}")
        text = self._call_tool('get_meetings', {'meeting_ids': [meeting_id]})
        meetings = self._parse_meetings_xml(text)
        if meetings:
            return meetings[0]
        raise ValueError(f"No data returned for meeting {meeting_id}")

    def get_meeting_transcript(self, meeting_id: str) -> str:
        """Get full verbatim transcript for a meeting via MCP."""
        logger.info(f"Fetching transcript for meeting: {meeting_id}")
        text = self._call_tool('get_meeting_transcript', {'meeting_id': meeting_id})

        # Response is JSON text with transcript field
        try:
            data = json.loads(text)
            transcript = data.get('transcript', '')
        except json.JSONDecodeError:
            # Fallback: treat entire response as transcript
            transcript = text

        if not transcript:
            raise ValueError(f"Empty transcript for meeting {meeting_id}")

        logger.info(f"Retrieved transcript ({len(transcript)} chars)")
        return transcript
