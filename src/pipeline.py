"""
Main Pipeline for PDF Question Extraction.
Orchestrates native PDF processing, image extraction, and VLM processing.
"""

import asyncio
import json
import logging
import time
import traceback
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Callable, Awaitable

from src.core.config import config
from src.core.schemas import ExtractedDocument, ExtractRequest, ExtractResponse
from src.extractors.pdf_converter import PDFConverter
from src.extractors.image_extractor import ImageExtractor
from src.processors.gemini_client import GeminiClient
from src.processors.question_parser import QuestionParser

logger = logging.getLogger(__name__)

# Type alias for progress callback function
ProgressCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]


class ExtractionPipeline:
    """
    Main pipeline for extracting questions from PDFs.
    Uses native PDF processing for full document context.
    Falls back to page-by-page for very large documents.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_base_dir: Optional[str] = None,
        dpi: int = 300,
        use_native_pdf: bool = True,
    ):
        """
        Initialize the extraction pipeline.

        Args:
            api_key: OpenRouter API key (optional, uses env var)
            output_base_dir: Base directory for outputs
            dpi: Image resolution for PDF conversion (fallback mode)
            use_native_pdf: Use native PDF processing (default True)
        """
        self.pdf_converter = PDFConverter(dpi=dpi)
        self.image_extractor = ImageExtractor(min_size=50)
        self.gemini_client = GeminiClient(api_key=api_key)
        self.question_parser = QuestionParser()
        self.use_native_pdf = use_native_pdf

        self.output_base_dir = (
            Path(output_base_dir) if output_base_dir else config.OUTPUTS_DIR
        )
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

    async def _emit_progress(
        self, progress_cb: ProgressCallback, event: Dict[str, Any]
    ) -> None:
        """Helper to emit progress events if callback is provided."""
        if progress_cb:
            await progress_cb(event)

    async def process_pdf(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        progress_cb: ProgressCallback = None,
    ) -> ExtractResponse:
        """
        Process a single PDF and extract questions.

        Uses native PDF processing by default, which sends the entire PDF
        to the model for full document context. Falls back to page-by-page
        processing for very large documents.

        Args:
            pdf_path: Path to the PDF file
            output_dir: Optional specific output directory
            progress_cb: Optional async callback for progress updates

        Returns:
            ExtractResponse with status and output paths
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return ExtractResponse(
                status="error", error=f"PDF file not found: {pdf_path}"
            )

        # Create output directory for this PDF
        pdf_name = pdf_path.stem
        if output_dir:
            pdf_output_dir = Path(output_dir)
        else:
            pdf_output_dir = self.output_base_dir / pdf_name

        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = pdf_output_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        pages_dir = pdf_output_dir / "pages"
        pages_dir.mkdir(exist_ok=True)

        logger.info(f"Processing PDF: {pdf_path.name}")
        await self._emit_progress(progress_cb, {
            "step": "started",
            "pdf": pdf_path.name,
            "timestamp": time.time()
        })

        try:
            # Step 1: Get page count to decide processing method
            total_pages = self.pdf_converter.get_page_count(str(pdf_path))
            logger.info(f"PDF has {total_pages} pages")
            await self._emit_progress(progress_cb, {
                "step": "info",
                "message": f"PDF has {total_pages} pages",
                "total_pages": total_pages
            })

            # Step 2: Extract embedded images (needed for both methods)
            logger.info("Step 1: Extracting embedded images...")
            await self._emit_progress(progress_cb, {
                "step": "extract_images",
                "message": "Extracting embedded images..."
            })
            extracted_images = self.image_extractor.extract_images(
                str(pdf_path), str(assets_dir), prefix=pdf_name
            )
            logger.info(f"Extracted {len(extracted_images)} embedded images")
            await self._emit_progress(progress_cb, {
                "step": "extract_images",
                "message": f"Extracted {len(extracted_images)} images",
                "images": len(extracted_images)
            })

            # Step 3: Choose processing method based on page count
            if self.use_native_pdf and total_pages <= config.MAX_PAGES_FOR_NATIVE:
                # Use native PDF processing for full document context
                await self._emit_progress(progress_cb, {
                    "step": "native_pdf",
                    "message": "Sending entire PDF to Gemini (Native Mode)..."
                })
                result, usage_stats = await self._process_native_pdf(
                    pdf_path, extracted_images, total_pages
                )
            else:
                # Fall back to page-by-page processing for large documents
                logger.info(
                    f"PDF has {total_pages} pages (>{config.MAX_PAGES_FOR_NATIVE}), "
                    "using chunked processing"
                )
                await self._emit_progress(progress_cb, {
                    "step": "chunked_mode",
                    "message": f"Processing large document (>{config.MAX_PAGES_FOR_NATIVE} pages) in chunks..."
                })
                result, usage_stats = await self._process_large_pdf(
                    pdf_path, pages_dir, extracted_images, total_pages, progress_cb
                )

            # Step 4: Post-process and build document
            logger.info("Step 3: Post-processing results...")
            await self._emit_progress(progress_cb, {
                "step": "post_process",
                "message": "Post-processing results..."
            })
            processing_time = time.time() - start_time

            document = self.question_parser.process_extraction_result(
                result=result,
                source_pdf=pdf_path.name,
                total_pages=total_pages,
                processing_time=processing_time,
                extracted_images=extracted_images,
            )

            # Step 5: Save output JSON
            output_json_path = pdf_output_dir / f"{pdf_name}_questions.json"

            output_data = document.model_dump(mode="json")
            output_data["usage"] = usage_stats.to_dict()

            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved output to: {output_json_path}")
            logger.info(f"Total processing time: {processing_time:.2f}s")
            logger.info(f"Extracted {len(document.questions)} questions")
            logger.info(f"Token usage: {usage_stats}")

            return ExtractResponse(
                status="ok",
                output_json_path=str(output_json_path),
                assets_dir=str(assets_dir),
                processing_time_seconds=processing_time,
            )

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Pipeline failed for {pdf_path.name}: {e}")
            logger.error(traceback.format_exc())
            return ExtractResponse(
                status="error", error=str(e), processing_time_seconds=processing_time
            )

    async def _process_native_pdf(
        self,
        pdf_path: Path,
        extracted_images: List[Dict[str, Any]],
        total_pages: int,
    ) -> Tuple[Dict[str, Any], Any]:
        """
        Process PDF using native PDF support (sends entire PDF to model).

        Args:
            pdf_path: Path to PDF file
            extracted_images: List of extracted image metadata
            total_pages: Total number of pages

        Returns:
            Tuple of (extraction result dict, usage stats)
        """
        logger.info("Step 2: Extracting questions using native PDF processing...")
        
        result, usage_stats = await self.gemini_client.extract_questions_from_pdf(
            str(pdf_path),
            extracted_images=extracted_images,
            total_pages=total_pages,
        )
        
        logger.info(f"Native PDF extraction complete")
        return result, usage_stats

    async def _process_large_pdf(
        self,
        pdf_path: Path,
        pages_dir: Path,
        extracted_images: List[Dict[str, Any]],
        total_pages: int,
        progress_cb: ProgressCallback = None,
    ) -> Tuple[Dict[str, Any], Any]:
        """
        Process very large documents using chunked page processing.

        Args:
            pdf_path: Path to PDF file
            pages_dir: Directory to save page images
            extracted_images: List of extracted image metadata
            total_pages: Total number of pages
            progress_cb: Optional async callback for progress updates

        Returns:
            Tuple of (combined result dict, usage stats)
        """
        logger.info("Step 2a: Converting PDF to images (fallback mode)...")
        await self._emit_progress(progress_cb, {
            "step": "pdf_to_images",
            "message": "Converting PDF to images..."
        })
        page_images = self.pdf_converter.convert_to_images(
            str(pdf_path), str(pages_dir), max_pages=config.MAX_PAGES_PER_PDF
        )
        actual_pages = len(page_images)
        logger.info(f"Converted {actual_pages} pages to images")

        # Log warning if pages were truncated
        if actual_pages < total_pages:
            logger.warning(
                f"Processed only first {actual_pages} pages out of {total_pages} "
                f"due to MAX_PAGES_PER_PDF={config.MAX_PAGES_PER_PDF}"
            )
            await self._emit_progress(progress_cb, {
                "step": "truncation_warning",
                "message": f"Warning: Only processing first {actual_pages} of {total_pages} pages (limit: {config.MAX_PAGES_PER_PDF})",
                "processed_pages": actual_pages,
                "total_pages": total_pages
            })

        logger.info("Step 2b: Extracting questions page-by-page...")
        image_paths = [img_path for _, img_path in page_images]
        
        # Process pages with progress updates
        page_results = []
        usage_stats = self.gemini_client.usage_stats.__class__()  # Create fresh UsageStats
        
        for i, image_path in enumerate(image_paths):
            page_num = i + 1
            await self._emit_progress(progress_cb, {
                "step": "gemini_extraction",
                "page": page_num,
                "total_pages": actual_pages,
                "message": f"Processing page {page_num}/{actual_pages}..."
            })
            
            try:
                page_result = await self.gemini_client.extract_questions_from_image(
                    image_path, page_num
                )
                page_results.append(page_result)
                
                if "_usage" in page_result:
                    usage_stats.add(page_result["_usage"], page_result.get("_generation_id"))
                
                questions_on_page = len(page_result.get("questions", []))
                await self._emit_progress(progress_cb, {
                    "step": "gemini_extraction",
                    "page": page_num,
                    "total_pages": actual_pages,
                    "questions_found": questions_on_page,
                    "message": f"Page {page_num} complete: {questions_on_page} questions"
                })
            except Exception as e:
                logger.error(f"Failed to process page {page_num}: {e}")
                await self._emit_progress(progress_cb, {
                    "step": "gemini_extraction",
                    "page": page_num,
                    "error": str(e),
                    "message": f"Page {page_num} failed: {str(e)}"
                })
                page_results.append({"page_number": page_num, "questions": [], "error": str(e)})
        
        logger.info(f"Processed {len(page_results)} pages")

        # Combine page results into a single result format
        all_questions = []
        for page_result in page_results:
            if "questions" in page_result:
                all_questions.extend(page_result.get("questions", []))

        # Get metadata from first page if available
        metadata_hints = {}
        for page_result in page_results:
            hints = page_result.get("metadata_hints", {})
            if hints:
                metadata_hints = hints
                break

        combined_result = {
            "total_pages": total_pages,
            "processed_pages": actual_pages,
            "questions": all_questions,
            "metadata_hints": metadata_hints,
            "_from_chunked": True,
        }

        return combined_result, usage_stats

    async def process_batch(
        self, pdf_paths: List[str], max_concurrent: int = 5
    ) -> List[Tuple[str, ExtractResponse]]:
        """
        Process multiple PDFs concurrently.

        Args:
            pdf_paths: List of PDF file paths
            max_concurrent: Maximum concurrent processing (default 5)

        Returns:
            List of (pdf_path, response) tuples
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(pdf_path: str) -> Tuple[str, ExtractResponse]:
            async with semaphore:
                logger.info(f"Starting processing: {Path(pdf_path).name}")
                response = await self.process_pdf(pdf_path)
                return (pdf_path, response)

        # Create tasks for all PDFs
        tasks = [process_with_semaphore(pdf_path) for pdf_path in pdf_paths]

        # Run concurrently and gather results
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, converting exceptions to error responses
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Batch task failed: {result}")
                final_results.append(
                    (pdf_paths[i], ExtractResponse(status="error", error=str(result)))
                )
            else:
                final_results.append(result)

        return final_results


async def process_single_pdf(
    pdf_path: str, output_dir: Optional[str] = None, api_key: Optional[str] = None
) -> ExtractResponse:
    """
    Convenience function to process a single PDF.

    Args:
        pdf_path: Path to PDF file
        output_dir: Output directory
        api_key: Optional API key

    Returns:
        ExtractResponse with results
    """
    pipeline = ExtractionPipeline(api_key=api_key, output_base_dir=output_dir)
    return await pipeline.process_pdf(pdf_path)


async def process_multiple_pdfs(
    pdf_paths: List[str],
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    max_concurrent: int = 5,
) -> List[Tuple[str, ExtractResponse]]:
    """
    Convenience function to process multiple PDFs.

    Args:
        pdf_paths: List of PDF paths
        output_dir: Output directory
        api_key: Optional API key
        max_concurrent: Max concurrent processing

    Returns:
        List of (pdf_path, response) tuples
    """
    pipeline = ExtractionPipeline(api_key=api_key, output_base_dir=output_dir)
    return await pipeline.process_batch(pdf_paths, max_concurrent)
