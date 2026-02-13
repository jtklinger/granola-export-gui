"""Export manager with binary success criteria"""
import os
import time
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime
from .verifier import TranscriptVerifier
from api.client import RateLimitError, CancelledError

logger = logging.getLogger(__name__)

class ExportManager:
    """Manages meeting exports with binary success criteria"""

    # Seconds to wait between transcript fetches to avoid rate limits.
    # Granola's free API allows roughly 1 transcript per 5+ minutes.
    COOLDOWN_BETWEEN_MEETINGS = 120

    def __init__(self, api_client):
        """
        Initialize export manager

        Args:
            api_client: GranolaAPIClient instance
        """
        self.api_client = api_client
        self.verifier = TranscriptVerifier()
        self.on_cooldown = None  # callback(seconds_remaining, total_wait)

    def _sanitize_filename(self, text: str) -> str:
        """
        Sanitize text for use in filename

        Args:
            text: Text to sanitize

        Returns:
            Sanitized filename string
        """
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            text = text.replace(char, '_')

        # Limit length
        return text[:100]

    def _format_meeting_filename(self, meeting: Dict) -> str:
        """
        Format meeting filename per skill requirements

        Args:
            meeting: Meeting dictionary

        Returns:
            Filename string (YYYY-MM-DD_Meeting_Title.md)
        """
        # Extract date
        date_str = meeting.get('date', '')
        if date_str:
            try:
                date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                date_part = date_obj.strftime('%Y-%m-%d')
            except:
                date_part = datetime.now().strftime('%Y-%m-%d')
        else:
            date_part = datetime.now().strftime('%Y-%m-%d')

        # Extract and sanitize title
        title = meeting.get('title', 'Untitled_Meeting')
        title_part = self._sanitize_filename(title).replace(' ', '_')

        return f"{date_part}_{title_part}.md"

    def _format_meeting_markdown(self, meeting: Dict, transcript: str) -> str:
        """
        Format meeting content as markdown per skill requirements

        Args:
            meeting: Meeting dictionary with summary
            transcript: Full transcript text

        Returns:
            Formatted markdown content
        """
        title = meeting.get('title', 'Untitled Meeting')
        date = meeting.get('date', 'Unknown date')
        meeting_id = meeting.get('id', 'Unknown ID')

        # Extract participants
        participants = meeting.get('participants', [])
        if isinstance(participants, list):
            participants_str = ', '.join(participants) if participants else 'Unknown'
        else:
            participants_str = str(participants)

        # Extract summary
        summary = meeting.get('summary', meeting.get('ai_summary', 'No summary available'))

        # Build markdown
        markdown = f"""# {title}

**Date:** {date}
**Meeting ID:** {meeting_id}
**Participants:** {participants_str}

---

## Summary

{summary}

---

## Full Verbatim Transcript

{transcript}
"""
        return markdown

    def export_single_meeting(
        self,
        meeting: Dict,
        output_dir: str,
        max_retries: int = 2
    ) -> Dict[str, any]:
        """
        Export a single meeting with verification and retries

        Args:
            meeting: Meeting dictionary
            output_dir: Output directory path
            max_retries: Maximum retry attempts

        Returns:
            Export result dictionary
        """
        meeting_id = meeting.get('id')
        meeting_title = meeting.get('title', 'Untitled')

        result = {
            'meeting_id': meeting_id,
            'title': meeting_title,
            'complete': False,
            'filename': None,
            'error': None,
            'verification': None
        }

        logger.info(f"Exporting meeting: {meeting_title} ({meeting_id})")

        prev_transcript_len = None  # Track transcript length to detect unchanged content

        # Retry loop
        for attempt in range(max_retries + 1):
            try:
                # Fetch full meeting details (summary)
                meeting_details = self.api_client.get_meeting_summary(meeting_id)

                # Merge details into meeting dict
                meeting.update(meeting_details)

                # Fetch transcript
                transcript = self.api_client.get_meeting_transcript(meeting_id)

                # Verify transcript
                verification = self.verifier.verify_transcript(transcript)
                result['verification'] = verification

                if verification['complete']:
                    # Write to file
                    filename = self._format_meeting_filename(meeting)
                    filepath = Path(output_dir) / filename

                    # Ensure output directory exists
                    filepath.parent.mkdir(parents=True, exist_ok=True)

                    # Format and write content
                    content = self._format_meeting_markdown(meeting, transcript)
                    filepath.write_text(content, encoding='utf-8')

                    result['complete'] = True
                    result['filename'] = filename
                    logger.info(f"✓ Export complete: {filename}")
                    return result
                else:
                    # If transcript content is identical to previous attempt,
                    # retrying won't help — the API is returning the same data.
                    if prev_transcript_len == len(transcript):
                        logger.warning(
                            f"Transcript unchanged ({len(transcript)} chars) — "
                            f"skipping further retries"
                        )
                        result['error'] = "Verification failed (transcript unchanged on retry)"
                        logger.error(f"✗ Export failed: {meeting_title}")
                        return result

                    prev_transcript_len = len(transcript)

                    # Verification failed
                    if attempt < max_retries:
                        logger.warning(
                            f"Verification failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying..."
                        )
                        continue
                    else:
                        result['error'] = "Verification failed after retries"
                        logger.error(f"✗ Export failed: {meeting_title}")
                        return result

            except RateLimitError as e:
                # Rate limit retries already exhausted in _call_tool — don't retry here
                logger.error(f"Rate limit exhausted for meeting: {str(e)}")
                result['error'] = str(e)
                return result

            except Exception as e:
                logger.error(f"Error exporting meeting: {str(e)}")
                if attempt < max_retries:
                    logger.warning(f"Retrying (attempt {attempt + 1}/{max_retries + 1})...")
                    continue
                else:
                    result['error'] = str(e)
                    return result

        return result

    def export_meetings(
        self,
        meetings: List[Dict],
        output_dir: str,
        progress_callback=None,
        result_callback=None
    ) -> Dict[str, any]:
        """
        Export multiple meetings with binary success criteria

        ALL meetings must complete successfully, or export FAILS.

        Args:
            meetings: List of meeting dictionaries
            output_dir: Output directory path
            progress_callback: Optional callback(current, total, status_msg)
            result_callback: Optional callback(meeting_id, success) after each meeting

        Returns:
            Export summary dictionary
        """
        total = len(meetings)
        failed_meetings = []
        completed_meetings = []

        logger.info(f"Starting export of {total} meetings to {output_dir}")

        for i, meeting in enumerate(meetings):
            current = i + 1
            meeting_title = meeting.get('title', 'Untitled')

            # Cooldown between meetings to avoid rate limits (skip before first)
            if i > 0:
                cooldown = self.COOLDOWN_BETWEEN_MEETINGS
                logger.info(f"Cooldown: waiting {cooldown}s before next meeting")
                self.api_client.reset_session()
                for remaining in range(cooldown, 0, -1):
                    if self.api_client.cancelled:
                        raise CancelledError("Export cancelled by user")
                    if self.on_cooldown:
                        self.on_cooldown(remaining, cooldown)
                    time.sleep(1)
                if self.on_cooldown:
                    self.on_cooldown(0, cooldown)

            # Progress callback
            if progress_callback:
                progress_callback(current, total, f"Exporting: {meeting_title}")

            # Export meeting
            result = self.export_single_meeting(meeting, output_dir, max_retries=2)

            if result['complete']:
                completed_meetings.append(result)
                if result_callback:
                    result_callback(meeting.get('id'), True)
            else:
                failed_meetings.append(result)
                if result_callback:
                    result_callback(meeting.get('id'), False)
                # Binary criteria: STOP on first failure
                logger.error("Export FAILED: Binary success criteria not met")
                break

        # Binary success criteria
        success = len(failed_meetings) == 0

        summary = {
            'success': success,
            'total': total,
            'completed': len(completed_meetings),
            'failed': len(failed_meetings),
            'failed_meetings': failed_meetings,
            'output_dir': output_dir
        }

        if success:
            logger.info(f"✓ Export SUCCESSFUL: All {total} meetings exported")
        else:
            logger.error(
                f"✗ Export FAILED: {len(failed_meetings)} of {total} meetings incomplete"
            )

        return summary
