"""Configuration management"""

class Config:
    """Application configuration"""

    # Granola OAuth discovery
    OAUTH_DISCOVERY_URL = "https://mcp-auth.granola.ai/.well-known/oauth-authorization-server"
    GRANOLA_RESOURCE = "https://mcp.granola.ai/"

    # Rate Limiting
    API_RATE_LIMIT_DELAY = 60  # seconds
    API_MAX_RETRIES = 2

    # Verification
    MIN_TRANSCRIPT_LENGTH = 10000
