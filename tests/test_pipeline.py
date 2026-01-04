import pytest
from src.pipeline import ExtractionPipeline
from src.processors.gemini_client import UsageStats
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

@pytest.mark.asyncio
async def test_pipeline_mode_selection(mock_api_key, output_dir):
    # Use output_dir fixture from conftest.py
    pipeline = ExtractionPipeline(api_key=mock_api_key, output_base_dir=output_dir)
    
    # Create a proper UsageStats mock that can be serialized
    mock_usage = UsageStats()
    
    # Mock all internal components that touch files or APIs
    pipeline.gemini_client = AsyncMock()
    pipeline.gemini_client.extract_questions_from_pdf.return_value = ({"questions": []}, mock_usage)
    pipeline.gemini_client.extract_questions_from_image.return_value = {"questions": [], "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    pipeline.gemini_client.usage_stats = mock_usage
    
    pipeline.image_extractor = MagicMock()
    pipeline.image_extractor.extract_images.return_value = []
    
    pipeline.question_parser = MagicMock()
    mock_doc = MagicMock()
    mock_doc.questions = []
    mock_doc.model_dump.return_value = {"questions": [], "metadata": {}, "source_pdf": "dummy.pdf"}
    pipeline.question_parser.process_extraction_result.return_value = mock_doc

    # Patch Path.exists to return True so the pipeline doesn't exit early
    with patch.object(Path, "exists", return_value=True):
        # Case 1: PDF with few pages (should use Native PDF)
        pipeline.pdf_converter.get_page_count = MagicMock(return_value=5)
        await pipeline.process_pdf("dummy.pdf")
        assert pipeline.gemini_client.extract_questions_from_pdf.called
        
        # Case 2: PDF with many pages (should use Fallback/Chunked mode)
        # In chunked mode, we now call extract_questions_from_image directly
        # instead of extract_questions_batch
        pipeline.gemini_client.extract_questions_from_pdf.reset_mock()
        pipeline.gemini_client.extract_questions_from_image.reset_mock()
        pipeline.pdf_converter.get_page_count = MagicMock(return_value=100)
        pipeline.pdf_converter.convert_to_images = MagicMock(return_value=[
            (1, "/tmp/page_001.png"),
            (2, "/tmp/page_002.png"),
        ])
        
        await pipeline.process_pdf("dummy.pdf")
        # Native PDF should NOT be called for large documents
        assert not pipeline.gemini_client.extract_questions_from_pdf.called
        # Individual page extraction should be called for each page
        assert pipeline.gemini_client.extract_questions_from_image.call_count == 2
