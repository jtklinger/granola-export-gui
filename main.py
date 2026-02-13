#!/usr/bin/env python3
"""
Granola Meeting Export GUI - Main Entry Point
Standalone desktop application for exporting Granola meeting transcripts
"""
import flet as ft
import logging
import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Parse command line arguments
parser = argparse.ArgumentParser(description='Granola Export GUI')
parser.add_argument('--test', action='store_true', help='Run in test mode with mock data')
args = parser.parse_args()

TEST_MODE = args.test

from auth import OAuthManager, TokenManager
from api import GranolaAPIClient
from verification import ExportManager
from gui import GranolaExportApp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main(page: ft.Page):
    """Main application entry point"""
    try:
        logger.info("Main function started")

        if TEST_MODE:
            logger.info("Running in TEST MODE with mock data")
            from gui.test_mode import create_test_app
            create_test_app(page)
            return

        # Initialize components
        logger.info("Initializing application components")

        # OAuth Manager (handles discovery + dynamic registration automatically)
        oauth_manager = OAuthManager()

        # Token Manager (client_id loaded from credential store if available)
        client_id = oauth_manager.get_client_id()
        token_manager = TokenManager(client_id=client_id)

        # API Client
        api_client = GranolaAPIClient(token_manager)

        # Export Manager
        export_manager = ExportManager(api_client)

        # Create main application
        logger.info("Creating main application window")
        GranolaExportApp(
            page,
            oauth_manager=oauth_manager,
            token_manager=token_manager,
            api_client=api_client,
            export_manager=export_manager
        )
        logger.info("Application initialized successfully")

    except Exception as e:
        logger.error(f"Application error: {str(e)}", exc_info=True)
        page.add(
            ft.Column([
                ft.Text("Application Error", size=24, weight=ft.FontWeight.BOLD, color="red"),
                ft.Text(f"Error: {str(e)}", size=14),
                ft.Text("Please check the console for full error details.", size=12, color="grey600"),
            ])
        )
        page.update()
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if TEST_MODE:
        logger.info("Starting Granola Export Tool in TEST MODE")
    else:
        logger.info("Starting Granola Export Tool")
    ft.run(main)
