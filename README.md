# Granola Meeting Export GUI

A desktop application for exporting [Granola](https://granola.ai) meeting transcripts with AI summaries and completeness verification.

## Features

- **Automatic OAuth Authentication** — Browser-based login via Granola's OAuth provider with PKCE. No API keys or client IDs to configure.
- **MCP Protocol Integration** — Communicates with Granola's MCP server for reliable meeting data access.
- **Complete Transcript Export** — Each meeting exported as markdown with metadata, AI summary, and full verbatim transcript.
- **Verification** — Every transcript checked for completeness (length, natural ending, no truncation).
- **Binary Success Criteria** — ALL transcripts must pass verification or the export fails. No partial exports.
- **Rate Limit Handling** — Automatic retry with escalating backoff and cooldown between meetings. Cancel button available during waits.
- **Secure Credential Storage** — OAuth tokens stored in OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service).
- **Real-time Progress** — Per-meeting status with green/red indicators, rate limit countdown, and cooldown display.

## Requirements

- Python 3.10+
- Windows, macOS, or Linux
- A [Granola](https://granola.ai) account

## Installation

```bash
git clone https://github.com/jtklinger/granola-export-gui.git
cd granola-export-gui
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

### Test Mode

Explore the UI with mock data (no Granola account needed):

```bash
python main.py --test
```

### Workflow

1. **Authenticate** — Click "Login with Granola". Your browser opens for OAuth login. Credentials are saved for future sessions.
2. **Select Date Range** — Choose a preset (last 7 days, last 30 days, this month, last month, this year, last year) or pick a custom date range.
3. **Fetch Meetings** — Click "Fetch Meetings" to load your meeting list.
4. **Select Meetings** — Check the meetings you want to export (or use Select All).
5. **Choose Export Location** — Default is `~/granola_exports/`. Click "Browse..." to change.
6. **Export** — Click "Export Selected" and monitor progress. Each meeting shows green (success) or red (failed) as it completes.

## Export Format

Each meeting is saved as `YYYY-MM-DD_Meeting_Title.md`:

```markdown
# Meeting Title

**Date:** 2025-11-24T10:00:00Z
**Meeting ID:** uuid-here
**Participants:** Alice, Bob, Charlie

---

## Summary

[AI-generated summary from Granola]

---

## Full Verbatim Transcript

[Complete verified transcript]
```

## Rate Limits

Granola's API has strict rate limits on transcript fetches. The app handles this automatically:

- **Cooldown**: 120-second pause between each meeting export
- **Backoff**: If rate limited, retries with escalating delays (2 min, 3 min, 5 min, 7 min, 10 min)
- **Cancel**: A cancel button is available at any time during export

Estimated export time: **~3 minutes per meeting** under normal conditions. Large batches (10+ meetings) can take 30+ minutes.

## Verification

Each transcript is verified for completeness before saving:

1. **Character count** > 10,000 (typical meetings are 20k–50k+)
2. **No mid-sentence cutoff** in the last 200 characters
3. **Natural conversation ending** present (goodbye, thanks, etc.)
4. **No known truncation patterns** at the end of transcript

If any check fails, the transcript is re-fetched (up to 2 retries). If still incomplete after retries, the entire export fails with a clear error message.

## Project Structure

```
granola-export-gui/
├── main.py                     # Application entry point
├── requirements.txt            # Dependencies
├── LICENSE                     # MIT License
│
├── auth/                       # Authentication
│   ├── oauth_manager.py        # OAuth 2.0 + PKCE + dynamic client registration
│   ├── token_manager.py        # Token refresh with rotation support
│   └── credential_store.py     # OS keyring integration
│
├── api/                        # API Integration
│   └── client.py               # Granola MCP protocol client
│
├── verification/               # Transcript Verification
│   ├── verifier.py             # Completeness checks
│   └── export_manager.py       # Export orchestration with binary success
│
├── gui/                        # User Interface (Flet)
│   ├── main_window.py          # Main application window
│   ├── auth_screen.py          # Authentication UI
│   ├── export_progress.py      # Progress display with rate limit/cooldown
│   └── test_mode.py            # Mock data for test mode
│
└── utils/                      # Utilities
    └── config.py               # Configuration constants
```

## Architecture

- **MCP Protocol**: The app communicates with Granola via the [Model Context Protocol](https://modelcontextprotocol.io/) (JSON-RPC over HTTP with SSE responses). OAuth tokens from Granola's auth server are scoped to the MCP endpoint.
- **OAuth 2.0 + PKCE**: Authentication uses dynamic client registration with the OAuth discovery endpoint, so no manual API key setup is needed.
- **Flet UI**: Cross-platform desktop UI built with [Flet](https://flet.dev/) (Flutter for Python). Background operations use `page.run_thread()` with event-loop-scheduled updates for reliable rendering.
- **Binary Success**: Follows the principle that incomplete data is worse than no data. The export either fully succeeds or clearly fails.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Browser doesn't open for login | Copy the URL from the console and open manually |
| "Rate limit exceeded" | Normal — the app retries automatically. Use cancel if needed. |
| Verification failures | The transcript is genuinely incomplete. Try again later or contact Granola support. |
| UI not updating during waits | Should be fixed — updates are scheduled on the Flet event loop. Restart the app if stale. |
| Authentication expired | Click Logout, then Login again. Tokens refresh automatically in most cases. |

## Dependencies

- [Flet](https://flet.dev/) 0.80.5 — UI framework
- [Requests](https://requests.readthedocs.io/) — HTTP client
- [Authlib](https://authlib.org/) — OAuth library
- [Keyring](https://github.com/jaraco/keyring) — Secure credential storage

## License

[MIT](LICENSE)
