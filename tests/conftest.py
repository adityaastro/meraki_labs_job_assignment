import pytest
import os
from pathlib import Path

@pytest.fixture
def sample_pdf():
    """Returns path to a sample PDF for testing."""
    return str(Path(__file__).parent.parent / "tests" / "test1.pdf")

@pytest.fixture
def output_dir(tmp_path):
    """Returns a temporary output directory."""
    d = tmp_path / "outputs"
    d.mkdir()
    return str(d)

@pytest.fixture
def mock_api_key():
    """Sets up a mock API key for testing."""
    os.environ["OPENROUTER_API_KEY"] = "sk-test-key"
    return "sk-test-key"

