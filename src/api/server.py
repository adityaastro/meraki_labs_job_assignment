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

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.config import config
from src.core.schemas import ExtractRequest, ExtractResponse, get_json_schema
from src.pipeline import ExtractionPipeline

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global pipeline instance
pipeline: Optional[ExtractionPipeline] = None


def validate_pdf_path(pdf_path_str: str) -> tuple[Path, Optional[str]]:
    """
    Validate and resolve a PDF path, ensuring it's within INPUT_BASE_DIR.
    
    Args:
        pdf_path_str: The requested PDF path (can be relative or absolute)
        
    Returns:
        Tuple of (resolved_path, error_message). If error_message is not None,
        the path is invalid and should not be used.
    """
    try:
        # Resolve the path relative to INPUT_BASE_DIR
        requested_path = Path(pdf_path_str)
        
        # If it's an absolute path, use it directly; otherwise resolve relative to INPUT_BASE_DIR
        if requested_path.is_absolute():
            resolved_path = requested_path.resolve()
        else:
            resolved_path = (config.INPUT_BASE_DIR / pdf_path_str).resolve()
        
        # Security check: ensure path is within INPUT_BASE_DIR
        try:
            resolved_path.relative_to(config.INPUT_BASE_DIR)
        except ValueError:
            return resolved_path, f"Invalid path: must be within {config.INPUT_BASE_DIR}"
        
        # Check file exists
        if not resolved_path.exists():
            return resolved_path, f"PDF file not found: {pdf_path_str}"
        
        # Check file extension
        if resolved_path.suffix.lower() != ".pdf":
            return resolved_path, f"Invalid file type. Expected PDF, got: {resolved_path.suffix}"
        
        return resolved_path, None
        
    except Exception as e:
        return Path(pdf_path_str), f"Invalid path: {str(e)}"


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
        request: ExtractRequest with pdf_path (relative to INPUT_BASE_DIR or absolute within it)

    Returns:
        ExtractResponse with status and output paths
    """
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    # Validate and resolve PDF path (security check)
    pdf_path, error = validate_pdf_path(request.pdf_path)
    if error:
        return ExtractResponse(status="error", error=error)

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
        request: ExtractRequest with pdf_path (relative to INPUT_BASE_DIR or absolute within it)

    Returns:
        StreamingResponse with SSE events
    """
    # Validate and resolve PDF path (security check)
    pdf_path, error = validate_pdf_path(request.pdf_path)
    if error:
        async def error_stream():
            yield f"data: {json.dumps({'status': 'error', 'error': error})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # Use a queue to collect progress events from the pipeline
    progress_queue: asyncio.Queue = asyncio.Queue()
    
    async def progress_callback(event: dict) -> None:
        """Callback to receive progress events from the pipeline."""
        await progress_queue.put(event)
    
    async def run_pipeline() -> None:
        """Run the pipeline and signal completion."""
        try:
            response = await pipeline.process_pdf(
                str(pdf_path), progress_cb=progress_callback
            )
            await progress_queue.put({"_done": True, "response": response})
        except Exception as e:
            await progress_queue.put({"_error": True, "error": str(e)})

    async def event_stream() -> AsyncGenerator[str, None]:
        """Generate SSE events during PDF processing."""
        global pipeline
        
        if not pipeline:
            yield f"data: {json.dumps({'status': 'error', 'error': 'Pipeline not initialized'})}\n\n"
            return

        # Start the pipeline in a background task
        pipeline_task = asyncio.create_task(run_pipeline())
        
        try:
            while True:
                # Wait for progress events from the pipeline
                event = await progress_queue.get()
                
                # Check for completion
                if event.get("_done"):
                    response = event["response"]
                    if response.status == "ok":
                        # Read the output file to get usage stats
                        try:
                            with open(response.output_json_path) as f:
                                output_data = json.load(f)
                            usage = output_data.get("usage", {})
                            questions_count = len(output_data.get("questions", []))
                        except Exception:
                            usage = {}
                            questions_count = 0
                        
                        yield f"data: {json.dumps({'status': 'complete', 'pdf': pdf_path.name, 'output_json_path': response.output_json_path, 'assets_dir': response.assets_dir, 'questions_extracted': questions_count, 'processing_time_seconds': round(response.processing_time_seconds or 0, 2), 'usage': usage})}\n\n"
                    else:
                        yield f"data: {json.dumps({'status': 'error', 'error': response.error})}\n\n"
                    break
                
                # Check for error
                if event.get("_error"):
                    yield f"data: {json.dumps({'status': 'error', 'error': event['error']})}\n\n"
                    break
                
                # Emit progress event
                yield f"data: {json.dumps({'status': 'processing', **event})}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
        finally:
            # Ensure pipeline task is cleaned up
            if not pipeline_task.done():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except asyncio.CancelledError:
                    pass

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
