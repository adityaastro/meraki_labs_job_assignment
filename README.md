# PDF Questions Extractor

A robust pipeline for extracting structured questions from educational PDF documents using AI vision models (Gemini) with native PDF processing.

## Features

- **Native PDF Processing**: Sends entire PDF directly to Gemini for full document context
- **Structured Output**: Questions extracted as structured JSON with MCQs, multi-part hierarchies, tables, images, and LaTeX
- **Section-Aware Extraction**: Unique IDs with section prefixes (MCQ_*, SEC_II_*, SEC_III_*)
- **Image Linking**: Extracted images automatically linked to questions by actual filename
- **Parallel Processing**: Process ≥5 PDFs concurrently
- **REST API**: FastAPI server with `/extract` and `/extract/stream` (SSE) endpoints
- **Automatic Fallback**: Page-by-page processing for large PDFs (>30 pages)
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

**Option A: CLI**
```bash
# Single PDF
python -m src.cli tests/test1.pdf -o outputs/

# Multiple PDFs (parallel)
python -m src.cli tests/*.pdf -o outputs/

# Or use batch script
bash run_eval.sh tests/*.pdf outputs/
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

**Option C: Docker (Recommended)**
```bash
# Configure API key
cp .env.example .env
# Edit .env: OPENROUTER_API_KEY=your_key_here

# Build and run with Docker Compose
docker-compose up --build

# Or build and run manually
docker build -t pdf-extractor .
docker run -p 8000:8000 --env-file .env -v $(pwd)/outputs:/app/outputs pdf-extractor

# API is now available at http://localhost:8000
curl http://localhost:8000/health

# Extract a PDF (mount your PDF directory)
docker run --env-file .env \
  -v $(pwd)/outputs:/app/outputs \
  -v $(pwd)/tests:/app/tests:ro \
  pdf-extractor \
  python -m src.cli /app/tests/test1.pdf -o /app/outputs/
```

## How It Works

```
PDF File
   │
   ├──► Extract Embedded Images (PyMuPDF)
   │         └──► Save to assets/ folder
   │
   └──► Send PDF Natively (OpenRouter API)
             │
             └──► Gemini processes entire document
                       │
                       └──► Structured JSON output
                                 │
                                 └──► Post-process & validate
```

**Native PDF Processing Benefits:**
- Full document context (model sees all pages at once)
- Better section understanding (MCQs, Proofs, etc.)
- No page-by-page context loss
- Accurate question numbering across sections

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
data: {"status": "processing", "step": "extract_images", "message": "Extracted 24 images"}
data: {"status": "processing", "step": "native_pdf", "message": "Sending PDF to Gemini..."}
data: {"status": "complete", "questions_extracted": 42, "usage": {"prompt_tokens": 5000, ...}}
```

## Output Format

```
outputs/
└── test3/
    ├── test3_questions.json   # Structured questions + usage stats
    ├── assets/                # Extracted images (test3_001.png, etc.)
    └── pages/                 # Page images (fallback mode only)
```

### JSON Structure

```json
{
  "source_pdf": "test3.pdf",
  "metadata": {
    "title": "Triangles",
    "subject": "MATHEMATICS",
    "grade": "IX CBSE",
    "total_pages": 7,
    "processing_time_seconds": 50.2
  },
  "questions": [
    {
      "id": "MCQ_1",
      "number": "1",
      "type": "mcq",
      "content": {
        "text": "Which of the following is not a criterion for congruence of triangles?",
        "images": [{"filename": "test3_001.png", "caption": "..."}]
      },
      "options": [
        {"label": "A", "text": "SAS", "is_correct": false},
        {"label": "B", "text": "ASA", "is_correct": false},
        {"label": "C", "text": "SSA", "is_correct": true},
        {"label": "D", "text": "SSS", "is_correct": false}
      ],
      "answer": "(C)",
      "page_number": 1
    }
  ],
  "usage": {
    "prompt_tokens": 5000,
    "completion_tokens": 9498,
    "total_tokens": 14498
  }
}
```

### Question ID Naming Convention

| Section | ID Pattern | Example |
|---------|------------|---------|
| Section I (MCQs) | `MCQ_N` | MCQ_1, MCQ_2, ..., MCQ_20 |
| Section II | `SEC_II_N` | SEC_II_1, SEC_II_2, ... |
| Section III | `SEC_III_N` | SEC_III_1, SEC_III_2, ... |
| Sub-questions | `SEC_III_N_i` | SEC_III_1_i, SEC_III_1_ii |

## CLI Output Example

```
============================================================
EXTRACTION SUMMARY
============================================================
✓ test3.pdf
  Output: outputs/test3/test3_questions.json
  Time: 43.38s
  Questions: 42
  Tokens: 5,002 prompt + 9,525 completion = 14,527 total
============================================================
Total: 1 PDFs | Success: 1 | Errors: 0
Total questions extracted: 42
Total tokens: 5,002 prompt + 9,525 completion = 14,527 total
Estimated cost: $0.031076
Total time: 43.38s
============================================================
```

## Project Structure

```
.
├── src/
│   ├── api/server.py           # FastAPI + SSE streaming
│   ├── core/
│   │   ├── config.py           # Configuration
│   │   ├── schemas.py          # Pydantic models
│   │   └── schema.json         # JSON Schema
│   ├── extractors/
│   │   ├── pdf_converter.py    # PDF → Images (fallback)
│   │   └── image_extractor.py  # Embedded images
│   ├── processors/
│   │   ├── gemini_client.py    # OpenRouter API (native PDF)
│   │   └── question_parser.py  # Post-processing
│   ├── pipeline.py             # Orchestration
│   └── cli.py                  # CLI interface
├── docs/
│   ├── NOTES.md                # Technical notes & approach
│   ├── EVAL.md                 # Evaluation system design
│   └── TECHNICAL.md            # Detailed architecture docs
├── outputs/                    # Generated outputs
├── tests/                      # Unit tests & test PDFs
├── Dockerfile                  # Container build
├── docker-compose.yml          # Container orchestration
├── run_eval.sh                 # Batch processing script
└── README.md                   # This file
```

## Performance

| Metric | Target | Achieved |
|--------|--------|----------|
| Runtime (7-page PDF) | ≤3 min | ~43s |
| Concurrent PDFs | ≥5 | ✓ 5 |
| Cost per PDF | - | ~$0.01-0.06 |
| Questions extracted | - | 42 (vs 33 with old method) |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `OPENROUTER_API_KEY` | Required | Your OpenRouter API key |
| `MAX_PAGES_FOR_NATIVE` | 30 | Max pages for native PDF processing |
| `MAX_PAGES_PER_PDF` | 50 | Max pages to process (safety limit) |

## Dependencies

- Python 3.10+
- PyMuPDF (PDF processing)
- FastAPI + Uvicorn (API server)
- httpx (Async HTTP)
- Pydantic (Data validation)
- OpenRouter API (Gemini)
- Docker (optional, for containerized deployment)
