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
    MODEL_NAME: str = os.getenv("MODEL_NAME", "google/gemini-3-flash-preview")
    MODEL_TEMPERATURE: float = float(os.getenv("MODEL_TEMPERATURE", "0.1"))
    MODEL_MAX_TOKENS: int = int(os.getenv("MODEL_MAX_TOKENS", "65536"))

    # Processing Configuration
    MAX_CONCURRENT_PDFS: int = int(os.getenv("MAX_CONCURRENT_PDFS", "5"))
    IMAGE_DPI: int = int(os.getenv("IMAGE_DPI", "300"))
    MAX_PAGES_PER_PDF: int = int(os.getenv("MAX_PAGES_PER_PDF", "50"))
    MAX_PAGES_FOR_NATIVE: int = int(os.getenv("MAX_PAGES_FOR_NATIVE", "30"))
    MIN_IMAGE_SIZE: int = int(os.getenv("MIN_IMAGE_SIZE", "50"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "120"))

    # Resilience Configuration
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF_BASE: float = float(os.getenv("RETRY_BACKOFF_BASE", "2.0"))

    # Cost Tracking Configuration
    COST_WARNING_THRESHOLD: float = float(os.getenv("COST_WARNING_THRESHOLD", "0.10"))
    MODEL_COST_INPUT_1M: float = float(os.getenv("MODEL_COST_INPUT_1M", "0.50"))
    MODEL_COST_OUTPUT_1M: float = float(os.getenv("MODEL_COST_OUTPUT_1M", "3.00"))

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    OUTPUTS_DIR: Path = BASE_DIR / "outputs"
    # Default to BASE_DIR for backwards compatibility; set INPUT_BASE_DIR env var to restrict
    INPUT_BASE_DIR: Path = Path(
        os.getenv("INPUT_BASE_DIR", str(BASE_DIR))
    ).resolve()

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
