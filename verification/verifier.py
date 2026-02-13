"""Transcript verification per exporting-granola-transcripts skill spec.

Verification checklist from skill:
  1. Character count > 10,000 (interviews/depositions typically 20k-50k+)
  2. Last 200 characters: no mid-sentence cutoff
  3. Natural conversation ending present (goodbye/thanks/bye/ending phrases)
  4. No abrupt stops like "whose title. Is principal architect." (truncation indicator)

Binary criteria: ALL complete = success, else = failure.
"""
import re
import logging

logger = logging.getLogger(__name__)


class TranscriptVerifier:
    """Verifies transcript completeness per skill standards"""

    MIN_TRANSCRIPT_LENGTH = 10000

    # Known Granola truncation patterns (from skill spec)
    TRUNCATION_PATTERNS = [
        r'whose\s+title\.\s+Is\s+',
        r'\.\s+Is\s+\w+\s+\w+\.\s*$',
    ]

    # Natural ending phrases (from skill spec)
    ENDING_PHRASES = [
        "goodbye", "bye", "thanks", "thank you", "see you",
        "take care", "have a good", "talk soon", "speak soon",
        "until next time", "catch you later",
    ]

    @classmethod
    def verify_transcript(cls, transcript: str) -> dict:
        """Run all verification checks from the skill spec."""
        results = {'complete': True, 'checks': [], 'failures': []}

        checks = [
            cls._check_length,
            cls._check_no_cutoff,
            cls._check_natural_ending,
            cls._check_no_truncation_pattern,
        ]

        for check in checks:
            name, passed, message = check(transcript)
            results['checks'].append({'name': name, 'passed': passed, 'message': message})
            if not passed:
                results['complete'] = False
                results['failures'].append(f"{name}: {message}")
                logger.warning(f"Verification failed - {name}: {message}")

        if results['complete']:
            logger.info("Transcript verification passed all checks")
        else:
            logger.error(f"Transcript verification failed: {len(results['failures'])} issues")

        return results

    @classmethod
    def _check_length(cls, transcript: str):
        length = len(transcript)
        if length > cls.MIN_TRANSCRIPT_LENGTH:
            return "Character Count", True, f"Length: {length:,} characters"
        return "Character Count", False, f"Too short: {length:,} characters (minimum {cls.MIN_TRANSCRIPT_LENGTH:,})"

    @classmethod
    def _check_no_cutoff(cls, transcript: str):
        """Check last 200 chars for mid-sentence cutoff (incomplete word/thought)."""
        if len(transcript) < 200:
            return "No Cutoff", False, "Transcript too short to verify"

        last_200 = transcript[-200:].rstrip()

        # A mid-sentence cutoff means the text ends without completing a sentence.
        # Check if it ends mid-word (no terminal punctuation and no whitespace before end).
        if last_200 and last_200[-1] not in '.!?"\')':
            # Ends without punctuation — likely cut off mid-sentence
            return "No Cutoff", False, f"Ends without punctuation: ...{last_200[-60:]}"

        return "No Cutoff", True, "No mid-sentence cutoff detected"

    @classmethod
    def _check_natural_ending(cls, transcript: str):
        """Check for natural conversation ending phrases."""
        if len(transcript) < 100:
            return "Natural Ending", False, "Transcript too short"

        last_500 = transcript[-500:].lower()
        for phrase in cls.ENDING_PHRASES:
            if phrase in last_500:
                return "Natural Ending", True, f"Found ending phrase: '{phrase}'"

        return "Natural Ending", False, "No closing phrase found (goodbye/thanks/bye)"

    @classmethod
    def _check_no_truncation_pattern(cls, transcript: str):
        """Check for known Granola truncation patterns at the end of transcript.

        Only flags patterns in the last 100 chars — the skill spec targets
        'abrupt stops' where the transcript was actually cut off, not
        mid-transcript ASR artifacts that happen to match the pattern.
        """
        if len(transcript) < 200:
            return "No Truncation Pattern", False, "Transcript too short"

        last_100 = transcript[-100:]
        for pattern in cls.TRUNCATION_PATTERNS:
            match = re.search(pattern, last_100, re.IGNORECASE)
            if match:
                return "No Truncation Pattern", False, f"Known truncation pattern at end: '{match.group()}'"

        return "No Truncation Pattern", True, "No known truncation patterns"
