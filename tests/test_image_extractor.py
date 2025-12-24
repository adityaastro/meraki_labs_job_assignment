import pytest
from pathlib import Path
from src.extractors.image_extractor import ImageExtractor

def test_image_extractor_init():
    extractor = ImageExtractor(min_size=100)
    assert extractor.min_size == 100

def test_extract_images_from_real_pdf(sample_pdf, output_dir):
    extractor = ImageExtractor(min_size=10)
    results = extractor.extract_images(sample_pdf, output_dir, prefix="test")
    
    assert isinstance(results, list)
    if len(results) > 0:
        first = results[0]
        assert "filename" in first
        assert "page_number" in first
        assert Path(output_dir, first["filename"]).exists()

