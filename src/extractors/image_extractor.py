"""
Image Extractor for PDFs.
Extracts embedded images and figures from PDF documents.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import hashlib
from src.core.config import config

logger = logging.getLogger(__name__)


class ImageExtractor:
    """
    Extracts embedded images from PDF documents.
    Saves images to disk and returns metadata for JSON referencing.
    """

    def __init__(self, min_size: Optional[int] = None):
        """
        Initialize the image extractor.

        Args:
            min_size: Minimum dimension (width or height) to extract.
                     Filters out tiny images like bullets/icons.
        """
        self.min_size = min_size or config.MIN_IMAGE_SIZE
        self._seen_hashes = set()  # Track duplicates

    def extract_images(
        self, pdf_path: str, output_dir: str, prefix: str = "img"
    ) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a PDF.

        Args:
            pdf_path: Path to the source PDF
            output_dir: Directory to save extracted images
            prefix: Prefix for image filenames

        Returns:
            List of image metadata dictionaries with:
                - filename: Saved filename
                - page_number: Source page (1-indexed)
                - bbox: Bounding box if available
                - width: Image width
                - height: Image height
        """
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._seen_hashes.clear()
        results = []
        image_counter = 0

        try:
            doc = fitz.open(str(pdf_path))

            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images(full=True)

                for img_index, img_info in enumerate(image_list):
                    try:
                        # Extract image
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)

                        if not base_image:
                            continue

                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        width = base_image["width"]
                        height = base_image["height"]

                        # Skip tiny images (likely icons/bullets)
                        if width < self.min_size or height < self.min_size:
                            continue

                        # Check for duplicates using hash
                        img_hash = hashlib.md5(image_bytes).hexdigest()[:12]
                        if img_hash in self._seen_hashes:
                            continue
                        self._seen_hashes.add(img_hash)

                        # Save image
                        image_counter += 1
                        filename = f"{prefix}_{image_counter:03d}.{image_ext}"
                        image_path = output_dir / filename

                        with open(image_path, "wb") as f:
                            f.write(image_bytes)

                        # Get bounding box if possible
                        bbox = self._get_image_bbox(page, xref)

                        results.append(
                            {
                                "filename": filename,
                                "page_number": page_num + 1,
                                "width": width,
                                "height": height,
                                "bbox": bbox,
                            }
                        )

                        logger.debug(f"Extracted image: {filename}")

                    except Exception as e:
                        logger.warning(
                            f"Failed to extract image {img_index} from page {page_num + 1}: {e}"
                        )
                        continue

            doc.close()
            logger.info(f"Extracted {len(results)} images from {pdf_path.name}")

        except Exception as e:
            logger.error(f"Error extracting images: {e}")
            raise

        return results

    def _get_image_bbox(self, page, xref: int) -> Dict[str, float] | None:
        """
        Try to get the bounding box of an image on a page.

        Args:
            page: PyMuPDF page object
            xref: Image xref number

        Returns:
            Bounding box dict or None if not found
        """
        try:
            # Get all image instances on the page
            for img in page.get_images():
                if img[0] == xref:
                    # Try to get the rect from page contents
                    # This is approximate - exact positioning requires more complex parsing
                    for block in page.get_text("dict")["blocks"]:
                        if block.get("type") == 1:  # Image block
                            bbox = block.get("bbox")
                            if bbox:
                                return {
                                    "x": bbox[0],
                                    "y": bbox[1],
                                    "width": bbox[2] - bbox[0],
                                    "height": bbox[3] - bbox[1],
                                }
        except Exception:
            pass
        return None


def extract_images_from_pdf(
    pdf_path: str, output_dir: str, prefix: str = "img", min_size: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to extract images from a PDF.

    Args:
        pdf_path: Path to PDF
        output_dir: Output directory for images
        prefix: Filename prefix
        min_size: Minimum image dimension to extract

    Returns:
        List of image metadata dictionaries
    """
    extractor = ImageExtractor(min_size=min_size)
    return extractor.extract_images(pdf_path, output_dir, prefix)
