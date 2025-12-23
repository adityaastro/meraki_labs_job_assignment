"""
Configuration module for PDF Questions Extractor.
Loads environment variables and provides centralized settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # API Configuration
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    MODEL_NAME: str = "google/gemini-3-flash-preview"

    # Processing Configuration
    MAX_CONCURRENT_PDFS: int = int(os.getenv("MAX_CONCURRENT_PDFS", "5"))
    IMAGE_DPI: int = int(os.getenv("IMAGE_DPI", "300"))
    MAX_PAGES_PER_PDF: int = 50  # Safety limit
    REQUEST_TIMEOUT: int = 120  # seconds

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    OUTPUTS_DIR: Path = BASE_DIR / "outputs"

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
        if not cls.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")
        return True

    @classmethod
    def ensure_dirs(cls) -> None:
        """Ensure required directories exist."""
        cls.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


# Singleton instance
config = Config()
