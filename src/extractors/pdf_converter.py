"""
PDF to Image Converter.
Converts PDF pages to high-resolution images for VLM processing.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


class PDFConverter:
    """
    Converts PDF documents to images for vision model processing.
    Uses PyMuPDF (fitz) for fast, reliable conversion.
    """

    def __init__(self, dpi: int = 300):
        """
        Initialize the PDF converter.

        Args:
            dpi: Resolution for rendered images (default 300 for high quality)
        """
        self.dpi = dpi
        # Calculate zoom factor from DPI (72 is default PDF DPI)
        self.zoom = dpi / 72.0
        self.matrix = fitz.Matrix(self.zoom, self.zoom)

    def convert_to_images(
        self, pdf_path: str, output_dir: str, max_pages: int = 50
    ) -> List[Tuple[int, str]]:
        """
        Convert all pages of a PDF to PNG images.

        Args:
            pdf_path: Path to the source PDF file
            output_dir: Directory to save output images
            max_pages: Maximum number of pages to process (safety limit)

        Returns:
            List of tuples (page_number, image_path)
        """
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        results = []

        try:
            doc = fitz.open(str(pdf_path))
            total_pages = min(len(doc), max_pages)

            logger.info(f"Converting {total_pages} pages from {pdf_path.name}")

            for page_num in range(total_pages):
                page = doc[page_num]

                # Render page to pixmap (image)
                pixmap = page.get_pixmap(matrix=self.matrix)

                # Generate output filename
                image_filename = f"page_{page_num + 1:03d}.png"
                image_path = output_dir / image_filename

                # Save as PNG
                pixmap.save(str(image_path))

                results.append((page_num + 1, str(image_path)))
                logger.debug(f"Converted page {page_num + 1}/{total_pages}")

            doc.close()
            logger.info(f"Successfully converted {len(results)} pages")

        except Exception as e:
            logger.error(f"Error converting PDF: {e}")
            raise

        return results

    def get_page_count(self, pdf_path: str) -> int:
        """Get the number of pages in a PDF."""
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count

    def convert_single_page(
        self, pdf_path: str, page_number: int, output_path: str
    ) -> str:
        """
        Convert a single page to an image.

        Args:
            pdf_path: Path to the source PDF
            page_number: Page number (1-indexed)
            output_path: Path for output image

        Returns:
            Path to the created image
        """
        doc = fitz.open(pdf_path)

        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} out of range (1-{len(doc)})")

        page = doc[page_number - 1]  # 0-indexed internally
        pixmap = page.get_pixmap(matrix=self.matrix)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(output_path))

        doc.close()
        return str(output_path)


def convert_pdf_to_images(
    pdf_path: str, output_dir: str, dpi: int = 300, max_pages: int = 50
) -> List[Tuple[int, str]]:
    """
    Convenience function to convert a PDF to images.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory for output images
        dpi: Image resolution
        max_pages: Maximum pages to convert

    Returns:
        List of (page_number, image_path) tuples
    """
    converter = PDFConverter(dpi=dpi)
    return converter.convert_to_images(pdf_path, output_dir, max_pages)
