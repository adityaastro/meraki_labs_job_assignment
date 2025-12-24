"""
FastAPI Server for PDF Question Extraction.
Provides REST API endpoints for processing PDFs.
Includes SSE streaming for real-time progress updates.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import List, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.config import config
from src.core.schemas import ExtractRequest, ExtractResponse, get_json_schema
from src.pipeline import ExtractionPipeline
from src.extractors.pdf_converter import PDFConverter
from src.extractors.image_extractor import ImageExtractor
from src.processors.gemini_client import GeminiClient, UsageStats
from src.processors.question_parser import QuestionParser

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global pipeline instance
pipeline: Optional[ExtractionPipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global pipeline

    # Startup
    logger.info("Starting PDF Questions Extractor API...")

    # Validate configuration
    try:
        config.validate()
        config.ensure_dirs()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise

    # Initialize pipeline
    pipeline = ExtractionPipeline()
    logger.info("Pipeline initialized successfully")

    yield

    # Shutdown
    logger.info("Shutting down API...")


# Create FastAPI app
app = FastAPI(
    title="PDF Questions Extractor",
    description="Extract structured questions from PDF documents using AI",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "PDF Questions Extractor",
        "status": "healthy",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "config": {
            "model": config.MODEL_NAME,
            "max_concurrent_pdfs": config.MAX_CONCURRENT_PDFS,
            "image_dpi": config.IMAGE_DPI,
        },
    }


@app.post("/extract", response_model=ExtractResponse)
async def extract_questions(request: ExtractRequest) -> ExtractResponse:
    """
    Extract questions from a PDF file.

    Args:
        request: ExtractRequest with pdf_path

    Returns:
        ExtractResponse with status and output paths
    """
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    pdf_path = Path(request.pdf_path)

    # Validate PDF exists
    if not pdf_path.exists():
        return ExtractResponse(
            status="error", error=f"PDF file not found: {request.pdf_path}"
        )

    if not pdf_path.suffix.lower() == ".pdf":
        return ExtractResponse(
            status="error",
            error=f"Invalid file type. Expected PDF, got: {pdf_path.suffix}",
        )

    logger.info(f"Received extraction request for: {pdf_path.name}")

    try:
        response = await pipeline.process_pdf(str(pdf_path))
        return response
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return ExtractResponse(status="error", error=str(e))


@app.post("/extract/stream")
async def extract_questions_stream(request: ExtractRequest):
    """
    Extract questions from a PDF with SSE streaming progress updates.

    Streams real-time progress as Server-Sent Events (SSE).

    Args:
        request: ExtractRequest with pdf_path

    Returns:
        StreamingResponse with SSE events
    """
    pdf_path = Path(request.pdf_path)

    # Validate PDF exists
    if not pdf_path.exists():

        async def error_stream():
            yield f"data: {json.dumps({'status': 'error', 'error': f'PDF file not found: {request.pdf_path}'})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    if not pdf_path.suffix.lower() == ".pdf":

        async def error_stream():
            yield f"data: {json.dumps({'status': 'error', 'error': f'Invalid file type: {pdf_path.suffix}'})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_stream() -> AsyncGenerator[str, None]:
        """Generate SSE events during PDF processing."""
        start_time = time.time()
        pdf_name = pdf_path.stem

        try:
            # Send start event
            yield f"data: {json.dumps({'status': 'started', 'pdf': pdf_path.name, 'timestamp': time.time()})}\n\n"

            # Initialize components
            pdf_converter = PDFConverter(dpi=config.IMAGE_DPI)
            image_extractor = ImageExtractor()
            gemini_client = GeminiClient()
            question_parser = QuestionParser()

            # Create output directories
            pdf_output_dir = config.OUTPUTS_DIR / pdf_name
            pdf_output_dir.mkdir(parents=True, exist_ok=True)
            assets_dir = pdf_output_dir / "assets"
            assets_dir.mkdir(exist_ok=True)
            pages_dir = pdf_output_dir / "pages"
            pages_dir.mkdir(exist_ok=True)

            # Step 1: Get page count
            total_pages = pdf_converter.get_page_count(str(pdf_path))
            yield f"data: {json.dumps({'status': 'processing', 'step': 'info', 'message': f'PDF has {total_pages} pages'})}\n\n"

            # Step 2: Extract embedded images
            yield f"data: {json.dumps({'status': 'processing', 'step': 'extract_images', 'message': 'Extracting embedded images...'})}\n\n"

            extracted_images = image_extractor.extract_images(
                str(pdf_path), str(assets_dir), prefix=pdf_name
            )

            yield f"data: {json.dumps({'status': 'processing', 'step': 'extract_images', 'message': f'Extracted {len(extracted_images)} images', 'images': len(extracted_images)})}\n\n"

            # Step 3: Extract questions (choose mode)
            if total_pages <= config.MAX_PAGES_FOR_NATIVE:
                # NATIVE PDF MODE
                yield f"data: {json.dumps({'status': 'processing', 'step': 'native_pdf', 'message': 'Sending entire PDF to Gemini (Native Mode)...'})}\n\n"
                
                result, usage_stats = await gemini_client.extract_questions_from_pdf(
                    str(pdf_path),
                    extracted_images=extracted_images,
                    total_pages=total_pages
                )
                batch_usage = usage_stats
            else:
                # FALLBACK PAGE-BY-PAGE MODE
                yield f"data: {json.dumps({'status': 'processing', 'step': 'fallback_mode', 'message': f'PDF too large (>{config.MAX_PAGES_FOR_NATIVE} pages), using fallback mode...'})}\n\n"
                
                # Convert to images
                yield f"data: {json.dumps({'status': 'processing', 'step': 'pdf_to_images', 'message': 'Converting PDF to images...'})}\n\n"
                page_images = pdf_converter.convert_to_images(
                    str(pdf_path), str(pages_dir), max_pages=config.MAX_PAGES_PER_PDF
                )
                
                image_paths = [img_path for _, img_path in page_images]
                page_results = []
                batch_usage = UsageStats()

                for i, image_path in enumerate(image_paths):
                    page_num = i + 1
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'gemini_extraction', 'page': page_num, 'total_pages': len(image_paths), 'message': f'Processing page {page_num}/{len(image_paths)}...'})}\n\n"

                    try:
                        page_result = await gemini_client.extract_questions_from_image(
                            image_path, page_num
                        )
                        page_results.append(page_result)

                        if "_usage" in page_result:
                            batch_usage.add(page_result["_usage"], page_result.get("_generation_id"))

                        questions_on_page = len(page_result.get("questions", []))
                        yield f"data: {json.dumps({'status': 'processing', 'step': 'gemini_extraction', 'page': page_num, 'total_pages': len(image_paths), 'questions_found': questions_on_page, 'message': f'Page {page_num} complete: {questions_on_page} questions'})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'status': 'processing', 'step': 'gemini_extraction', 'page': page_num, 'error': str(e), 'message': f'Page {page_num} failed: {str(e)}'})}\n\n"
                        page_results.append({"page_number": page_num, "questions": [], "error": str(e)})

                result = {
                    "total_pages": total_pages,
                    "questions": [q for pr in page_results for q in pr.get("questions", [])],
                    "metadata_hints": next((pr.get("metadata_hints", {}) for pr in page_results if pr.get("metadata_hints")), {}),
                    "_from_fallback": True
                }

            # Step 4: Post-process
            yield f"data: {json.dumps({'status': 'processing', 'step': 'post_process', 'message': 'Post-processing results...'})}\n\n"
            
            processing_time = time.time() - start_time
            document = question_parser.process_extraction_result(
                result=result,
                source_pdf=pdf_path.name,
                total_pages=total_pages,
                processing_time=processing_time,
                extracted_images=extracted_images,
            )

            # Step 5: Save output
            output_json_path = pdf_output_dir / f"{pdf_name}_questions.json"
            output_data = document.model_dump(mode="json")
            output_data["usage"] = batch_usage.to_dict()

            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            # Send completion event
            yield f"data: {json.dumps({'status': 'complete', 'pdf': pdf_path.name, 'output_json_path': str(output_json_path), 'assets_dir': str(assets_dir), 'questions_extracted': len(document.questions), 'processing_time_seconds': round(processing_time, 2), 'usage': batch_usage.to_dict()})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/extract/batch")
async def extract_batch(pdf_paths: List[str]) -> List[dict]:
    """
    Extract questions from multiple PDFs concurrently.

    Args:
        pdf_paths: List of PDF file paths

    Returns:
        List of extraction results
    """
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No PDF paths provided")

    if len(pdf_paths) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 PDFs per batch")

    logger.info(f"Received batch extraction request for {len(pdf_paths)} PDFs")

    try:
        results = await pipeline.process_batch(
            pdf_paths, max_concurrent=config.MAX_CONCURRENT_PDFS
        )

        return [
            {"pdf_path": pdf_path, "response": response.model_dump()}
            for pdf_path, response in results
        ]
    except Exception as e:
        logger.error(f"Batch extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/schema")
async def get_output_schema():
    """Get the JSON schema for extracted documents."""
    return JSONResponse(content=get_json_schema())


# Error handlers
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """Handle unexpected exceptions."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"status": "error", "error": str(exc)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
