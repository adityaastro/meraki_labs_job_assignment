# PDF Questions Extractor

A robust pipeline for extracting structured questions from educational PDF documents using AI vision models (Gemini 3 Flash).

## Features

- **Vision-First Approach**: Converts PDF pages to images and uses Gemini 3 Flash for accurate extraction
- **Structured Output**: Questions extracted as structured JSON with MCQs, multi-part hierarchies, tables, images, and LaTeX
- **Parallel Processing**: Process ≥5 PDFs concurrently
- **REST API**: FastAPI server with `/extract` and `/extract/stream` (SSE) endpoints
- **Real-time Progress**: Server-Sent Events for live progress updates
- **Token Tracking**: Accurate per-PDF token usage and cost estimation

## Quick Start

### 1. Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env: OPENROUTER_API_KEY=your_key_here
```

### 2. Run Extraction

**Option A: CLI (Recommended)**
```bash
# Single PDF
python -m src.cli test1.pdf -o outputs/

# Multiple PDFs (parallel)
python -m src.cli test*.pdf -o outputs/

# Or use batch script
bash run_eval.sh test*.pdf outputs/
```

**Option B: API Server**
```bash
# Start server
uvicorn src.api.server:app --reload

# Standard request (waits for completion)
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}'

# Streaming request (real-time progress)
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}'
```

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/health` | GET | Detailed health status |
| `/extract` | POST | Extract questions (sync) |
| `/extract/stream` | POST | Extract with SSE progress |
| `/extract/batch` | POST | Batch extraction |
| `/schema` | GET | JSON Schema for output |

### SSE Streaming Example

```bash
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}'
```

**Output (Server-Sent Events):**
```
data: {"status": "started", "pdf": "test1.pdf"}
data: {"status": "processing", "step": "pdf_to_images", "message": "Converted 8 pages"}
data: {"status": "processing", "step": "gemini_extraction", "page": 1, "total_pages": 8}
data: {"status": "processing", "step": "gemini_extraction", "page": 2, "total_pages": 8}
...
data: {"status": "complete", "questions_extracted": 15, "usage": {"prompt_tokens": 38086, ...}}
```

## Output Format

```
outputs/
└── test1/
    ├── test1_questions.json   # Structured questions + usage stats
    ├── assets/                 # Extracted images
    └── pages/                  # Page images (optional)
```

### JSON Structure

```json
{
  "source_pdf": "test1.pdf",
  "metadata": {
    "title": "Unit 1: Sequences and Series",
    "subject": "Mathematics",
    "total_pages": 8,
    "processing_time_seconds": 50.2
  },
  "questions": [
    {
      "id": "Q1",
      "number": "1.",
      "type": "multi_part",
      "content": {"text": "..."},
      "sub_questions": [...]
    }
  ],
  "usage": {
    "prompt_tokens": 38086,
    "completion_tokens": 19104,
    "total_tokens": 57190
  }
}
```

## CLI Output Example

```
============================================================
EXTRACTION SUMMARY
============================================================
✓ test1.pdf
  Output: outputs/test1/test1_questions.json
  Time: 50.20s
  Questions: 10
  Tokens: 38,086 prompt + 19,104 completion = 57,190 total
✓ test2.pdf
  ...
============================================================
Total: 5 PDFs | Success: 5 | Errors: 0
Total questions extracted: 151
Total tokens: 204,857 prompt + 106,217 completion = 311,074 total
Estimated cost: $0.062973
Total time: 162.14s
============================================================
```

## Project Structure

```
.
├── src/
│   ├── api/server.py           # FastAPI + SSE streaming
│   ├── core/
│   │   ├── config.py           # Configuration
│   │   └── schemas.py          # Pydantic models
│   ├── extractors/
│   │   ├── pdf_converter.py    # PDF → Images
│   │   └── image_extractor.py  # Embedded images
│   ├── processors/
│   │   ├── gemini_client.py    # OpenRouter API
│   │   └── question_parser.py  # Post-processing
│   ├── pipeline.py             # Orchestration
│   └── cli.py                  # CLI interface
├── outputs/                    # Generated outputs
├── run_eval.sh                 # Batch script
├── TEST_SCENARIOS.md           # Test cases
├── README.md                   # This file
├── NOTES.md                    # Technical notes
└── EVAL.md                     # Evaluation design
```

## Performance

| Metric | Target | Achieved |
|--------|--------|----------|
| Runtime (10-page PDF) | ≤3 min | ~50-60s |
| Concurrent PDFs | ≥5 | ✓ 5 |
| Cost per PDF | - | ~$0.01 |

## Dependencies

- Python 3.10+
- PyMuPDF (PDF processing)
- FastAPI + Uvicorn (API server)
- httpx (Async HTTP)
- Pydantic (Data validation)
- OpenRouter API (Gemini 3 Flash)
