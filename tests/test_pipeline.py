import pytest
from src.pipeline import ExtractionPipeline
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

@pytest.mark.asyncio
async def test_pipeline_mode_selection(mock_api_key, output_dir):
    # Use output_dir fixture from conftest.py
    pipeline = ExtractionPipeline(api_key=mock_api_key, output_base_dir=output_dir)
    
    # Mock all internal components that touch files or APIs
    pipeline.gemini_client = AsyncMock()
    pipeline.gemini_client.extract_questions_from_pdf.return_value = ({}, MagicMock())
    pipeline.gemini_client.extract_questions_batch.return_value = ([], MagicMock())
    
    pipeline.image_extractor = MagicMock()
    pipeline.image_extractor.extract_images.return_value = []
    
    pipeline.question_parser = MagicMock()
    mock_doc = MagicMock()
    mock_doc.questions = []
    mock_doc.model_dump.return_value = {"questions": []}
    pipeline.question_parser.process_extraction_result.return_value = mock_doc

    # Patch Path.exists to return True so the pipeline doesn't exit early
    with patch.object(Path, "exists", return_value=True):
        # Case 1: PDF with few pages (should use Native PDF)
        pipeline.pdf_converter.get_page_count = MagicMock(return_value=5)
        await pipeline.process_pdf("dummy.pdf")
        assert pipeline.gemini_client.extract_questions_from_pdf.called
        
        # Case 2: PDF with many pages (should use Fallback/Batch)
        pipeline.gemini_client.extract_questions_from_pdf.reset_mock()
        pipeline.pdf_converter.get_page_count = MagicMock(return_value=100)
        pipeline.pdf_converter.convert_to_images = MagicMock(return_value=[])
        
        await pipeline.process_pdf("dummy.pdf")
        assert not pipeline.gemini_client.extract_questions_from_pdf.called
        assert pipeline.gemini_client.extract_questions_batch.called