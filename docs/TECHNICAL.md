# Technical Documentation: PDF Questions Extractor

> A comprehensive guide to the architecture, design decisions, and technical nuances of the PDF Questions Extractor system.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Component Deep Dive](#component-deep-dive)
3. [Data Flow](#data-flow)
4. [Processing Modes](#processing-modes)
5. [Schema Design](#schema-design)
6. [API Architecture](#api-architecture)
7. [Prompt Engineering](#prompt-engineering)
8. [Concurrency Model](#concurrency-model)
9. [Token & Cost Management](#token--cost-management)
10. [Error Handling](#error-handling)
11. [Technical Nuances](#technical-nuances)
12. [Configuration Reference](#configuration-reference)

---

## System Architecture

### High-Level Architecture Diagram

```mermaid
flowchart TB
    subgraph Entrypoints["Entry Points"]
        CLI["CLI.py<br/>(argparse)"]
        API["API Server<br/>(FastAPI)"]
        Batch["Batch Script<br/>(run_eval.sh)"]
    end

    subgraph Pipeline["EXTRACTION PIPELINE (pipeline.py)"]
        direction TB
        PipelineDesc["• Orchestrates entire extraction workflow<br/>• Decides between native PDF vs chunked mode<br/>• Manages concurrency for batch processing<br/>• Handles output generation and validation"]
    end

    subgraph Components["Core Components"]
        direction LR
        subgraph Extractors["EXTRACTORS"]
            ImageExtractor["ImageExtractor<br/>(PyMuPDF)"]
            PDFConverter["PDFConverter<br/>(PyMuPDF)"]
        end
        subgraph Processors["PROCESSORS"]
            GeminiClient["GeminiClient<br/>(OpenRouter)"]
            QuestionParser["QuestionParser"]
        end
        subgraph Core["CORE"]
            Config["Config"]
            Schemas["Schemas<br/>(Pydantic)"]
        end
    end

    subgraph Output["OUTPUT: outputs/{pdf_name}/"]
        QuestionsJSON["{pdf_name}_questions.json"]
        Assets["assets/<br/>├── {pdf_name}_001.png<br/>├── {pdf_name}_002.jpeg"]
        Pages["pages/<br/>├── page_001.png<br/>(chunked mode only)"]
    end

    subgraph External["EXTERNAL SERVICES"]
        OpenRouter["OpenRouter API<br/>└── google/gemini-3-flash<br/>(Native PDF Processing)"]
    end

    CLI --> Pipeline
    API --> Pipeline
    Batch --> Pipeline
    Pipeline --> Extractors
    Pipeline --> Processors
    Pipeline --> Core
    Extractors --> Output
    Processors --> Output
    Core --> Output
    Processors --> External
```

### Module Dependency Graph

```mermaid
flowchart TB
    cli["cli.py"]
    pipeline["pipeline.py"]
    
    subgraph extractors["extractors/"]
        image_extractor["image_extractor.py"]
        pdf_converter["pdf_converter.py"]
    end
    
    subgraph processors["processors/"]
        gemini_client["gemini_client.py"]
        question_parser["question_parser.py"]
    end
    
    subgraph core["core/"]
        config["config.py"]
        schemas["schemas.py"]
    end
    
    subgraph deps1["External Dependencies"]
        pymupdf["PyMuPDF (fitz)"]
    end
    
    subgraph deps2["External Dependencies"]
        httpx["httpx (async)<br/>OpenRouter"]
    end
    
    subgraph deps3["External Dependencies"]
        pydantic["Pydantic<br/>dotenv"]
    end
    
    cli --> pipeline
    pipeline --> extractors
    pipeline --> processors
    pipeline --> core
    
    extractors <--> processors
    processors <--> core
    
    extractors --> pymupdf
    processors --> httpx
    core --> pydantic
```

---

## Component Deep Dive

### 1. Extraction Pipeline (`src/pipeline.py`)

The central orchestrator that manages the entire extraction workflow.

```python
class ExtractionPipeline:
    """
    Main responsibilities:
    1. Determine processing mode (native PDF vs chunked)
    2. Coordinate extractors and processors
    3. Manage output directories
    4. Handle batch processing with concurrency control
    """
```

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `process_pdf()` | Main entry point for single PDF processing |
| `_process_native_pdf()` | Send entire PDF to Gemini (≤30 pages) |
| `_process_large_pdf()` | Chunked processing for large PDFs |
| `process_batch()` | Concurrent processing with semaphore |

**Processing Decision Logic:**

```mermaid
flowchart TD
    A[PDF Input] --> B[Get page count]
    B --> C{page_count <= 30 pages?}
    C -->|YES| D[Native PDF Processing]
    C -->|NO| E[Page-by-page Fallback]
```

### 2. Gemini Client (`src/processors/gemini_client.py`)

Handles all communication with the OpenRouter API for Gemini 3.0 Flash.

**Key Features:**

```python
class GeminiClient:
    """
    - Native PDF processing via base64 encoding
    - Structured JSON output mode
    - Token usage tracking
    - Cost estimation
    - Automatic retry handling
    """
```

**API Request Structure:**

```python
payload = {
    "model": "google/gemini-3-flash-preview",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": "Extract questions..."},
            {"type": "image_url", "image_url": {"url": pdf_data_url}}  # Base64 PDF
        ]}
    ],
    "temperature": 0.1,           # Low for deterministic extraction
    "max_tokens": 65536,          # Large for full document extraction
    "response_format": {"type": "json_object"}  # Structured output
}
```

**Token Usage Tracking:**

```python
@dataclass
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    generation_ids: List[str] = field(default_factory=list)
```

### 3. Image Extractor (`src/extractors/image_extractor.py`)

Extracts embedded images from PDFs using PyMuPDF.

**Extraction Process:**

```mermaid
flowchart TD
    A[PDF Document] --> B[For each page]
    B --> C[Get all images - xref list]
    C --> D[Extract image bytes]
    D --> E{width/height >= 50px?}
    E -->|No| F[Skip - removes icons, bullets]
    E -->|Yes| G[Deduplicate via MD5 hash]
    G --> H{Already seen hash?}
    H -->|Yes| I[Skip duplicate]
    H -->|No| J["Save with sequential naming<br/>{prefix}_{001}.{ext}"]
    J --> K["Return metadata:<br/>[{filename, page_number, width, height, bbox}]"]
```

**Deduplication Logic:**

```python
# Prevent same image being saved multiple times
img_hash = hashlib.md5(image_bytes).hexdigest()[:12]
if img_hash in self._seen_hashes:
    continue  # Skip duplicate
self._seen_hashes.add(img_hash)
```

### 4. PDF Converter (`src/extractors/pdf_converter.py`)

Converts PDF pages to images (used in chunked mode).

```python
class PDFConverter:
    """
    - 300 DPI rendering for high-quality text recognition
    - PNG format for lossless output
    - Sequential page naming (page_001.png, page_002.png)
    """

    def __init__(self, dpi: int = 300):
        self.zoom = dpi / 72.0  # 72 is default PDF DPI
        self.matrix = fitz.Matrix(self.zoom, self.zoom)
```

### 5. Question Parser (`src/processors/question_parser.py`)

Post-processes extraction results with validation and enrichment.

**Key Responsibilities:**

```mermaid
flowchart TD
    A[Raw Extraction Result] --> B["ID Deduplication<br/>(Ensure unique IDs: MCQ_1, SEC_II_1, etc.)"]
    B --> C["Image Filename Resolution<br/>(figure_1 → test3_001.png)"]
    C --> D["Type Validation<br/>(Ensure valid question types)"]
    D --> E["Nested Sub-question Parsing<br/>(Recursive structure building)"]
    E --> F["Cross-page Question Merging<br/>(Detect and merge continuations)"]
    F --> G["Pydantic Model Construction<br/>(ExtractedDocument)"]
```

**Image Filename Mapping:**

```python
# Build flexible lookup mapping
mapping = {
    "1": "test3_001.png",           # By index
    "figure_1": "test3_001.png",    # By figure number
    "fig_1": "test3_001.png",       # Abbreviated
    "figure 1": "test3_001.png",    # With space
    "test3_001": "test3_001.png",   # By name
    ...
}
```

---

## Data Flow

### Complete Processing Flow

```mermaid
flowchart LR
    subgraph Input
        PDF[test3.pdf]
    end

    subgraph Pipeline["Processing Pipeline"]
        direction TB
        Init[Pipeline Init]
        
        subgraph Step1["STEP 1: Image Extraction"]
            S1_1["PyMuPDF extracts embedded images"]
            S1_2["Filter small images < 50px"]
            S1_3["Deduplicate via MD5 hash"]
            S1_4["Save to assets/ directory"]
            S1_1 --> S1_2 --> S1_3 --> S1_4
        end
        
        subgraph Step2["STEP 2: Question Extraction"]
            S2_Check{pages <= 30?}
            S2_Native["Native PDF Processing<br/>Send base64 PDF to Gemini"]
            S2_Chunked["Convert pages to images<br/>Process by chunks"]
            S2_Check -->|Yes| S2_Native
            S2_Check -->|No| S2_Chunked
        end
        
        subgraph Step3["STEP 3: Post-Processing"]
            S3_1["Parse raw JSON response"]
            S3_2["Resolve image filenames"]
            S3_3["Deduplicate question IDs"]
            S3_4["Build Pydantic models"]
            S3_5["Validate against schema"]
        end
        
        subgraph Step4["STEP 4: Output Generation"]
            S4_1["Serialize to JSON"]
            S4_2["Add usage stats"]
            S4_3["Save to output directory"]
        end
        
        Init --> Step1
        Step1 --> Step2
        Step2 --> Step3
        Step3 --> Step4
    end

    subgraph Output
        JSON[test3_questions.json]
        Assets["assets/<br/>├── test3_001.png<br/>├── test3_002.jpeg"]
    end

    PDF --> Init
    Step1 --> Assets
    Step4 --> JSON
```

### Data Transformations

```mermaid
flowchart TB
    subgraph Stage1["Stage 1: PDF → Embedded Images"]
        direction TB
        S1A[PDF Binary]
        S1B["[{xref, image_bytes, page}]"]
        S1C["[{filename: 'test3_001.png', page: 1, width: 400, height: 300}]"]
        S1A --> S1B --> S1C
    end

    subgraph Stage2["Stage 2: PDF → Raw Questions"]
        direction TB
        S2A["PDF Binary (base64)"]
        S2B[OpenRouter API Request]
        S2C["{ questions: [{ id: 'MCQ_1', content: {...} }] }"]
        S2A --> S2B --> S2C
    end

    subgraph Stage3["Stage 3: Raw → Validated Questions"]
        direction TB
        S3A[Raw API Response]
        S3B["QuestionParser.process_extraction_result()"]
        S3C["ExtractedDocument (Pydantic)<br/>{ source_pdf, metadata, questions, usage }"]
        S3A --> S3B --> S3C
    end

    Stage1 ~~~ Stage2
    Stage2 ~~~ Stage3
```

---

## Processing Modes

### Mode 1: Native PDF Processing (Default)

**When Used:** PDF has ≤30 pages

```mermaid
flowchart LR
    A[PDF File] --> B[base64 encode] --> C[OpenRouter API] --> D[JSON Result]
```

**Advantages:**
- ✓ Full document context (model sees all pages at once)
- ✓ Better section understanding
- ✓ No context loss between pages
- ✓ Simpler pipeline (no image conversion needed)
- ✓ Cross-page questions handled naturally

**Limitations:**
- ✗ Token limit constraints (large PDFs exceed limits)
- ✗ API cost scales with document size

### Mode 2: Page-by-Page Fallback

**When Used:** PDF has >30 pages

```mermaid
flowchart TD
    A[PDF File] --> B["Convert to Images (300 DPI)"]
    B --> C[page_001.png]
    B --> D[page_002.png]
    B --> E[page_003.png]
    B --> F[...]
    
    C --> G[API Call] --> H["Questions (page 1)"]
    D --> I[API Call] --> J["Questions (page 2)"]
    E --> K[API Call] --> L["Questions (page 3)"]
    
    H --> M[Merge Results]
    J --> M
    L --> M
    
    M --> N[Detect Cross-page Questions]
```

**Advantages:**
- ✓ Handles any PDF size
- ✓ More granular progress tracking

**Limitations:**
- ✗ Context loss between pages
- ✗ More API calls (higher latency)
- ✗ Cross-page question detection is heuristic-based

---

## Schema Design

### Entity Relationship Diagram

```mermaid
classDiagram
    class ExtractedDocument {
        +string source_pdf
        +DocumentMetadata metadata
        +List~Question~ questions
        +UsageData usage
    }

    class DocumentMetadata {
        +string title
        +string subject
        +string grade
        +int total_pages
        +datetime extraction_timestamp
        +float processing_time_seconds
    }

    class Question {
        +string id
        +string number
        +QuestionType type
        +QuestionContent content
        +List~MCQOption~ options
        +List~Question~ sub_questions
        +string answer
        +int page_number
        +float marks
    }

    class QuestionContent {
        +string text
        +string latex
        +List~ImageRef~ images
        +TableData table
    }

    class ImageRef {
        +string filename
        +string caption
        +BoundingBox bbox
    }

    class BoundingBox {
        +float x
        +float y
        +float width
        +float height
    }

    class TableData {
        +List~string~ headers
        +List~List~string~~ rows
    }

    class MCQOption {
        +string label
        +string text
        +bool is_correct
    }

    class UsageData {
        +int prompt_tokens
        +int completion_tokens
        +int total_tokens
        +List~string~ generation_ids
    }

    ExtractedDocument --> DocumentMetadata
    ExtractedDocument --> Question
    ExtractedDocument --> UsageData
    Question --> QuestionContent
    Question --> MCQOption
    Question --> Question : sub_questions
    QuestionContent --> ImageRef
    QuestionContent --> TableData
    ImageRef --> BoundingBox
```

### Question ID Naming Convention

```mermaid
flowchart TB
    subgraph SectionI["Section I (MCQs)"]
        MCQ["MCQ_1, MCQ_2, ..., MCQ_20"]
    end

    subgraph SectionII["Section II (Short Answer)"]
        SEC_II["SEC_II_1, SEC_II_2, ..."]
    end

    subgraph SectionIII["Section III (Long Answer)"]
        SEC_III["SEC_III_1, SEC_III_2, ..."]
        subgraph SubQuestions["Sub-questions"]
            Sub1["SEC_III_1_i, SEC_III_1_ii"]
            Sub2["SEC_III_2_a, SEC_III_2_b"]
        end
        SEC_III --> SubQuestions
    end
```

### Question Types

```python
QuestionType = Literal[
    "mcq",           # Multiple choice with options
    "short_answer",  # Brief response/fill in
    "long_answer",   # Extended response
    "multi_part",    # Question with sub-parts
    "fill_in_blank", # Complete sentence/equation
    "true_false",    # True/False question
    "matching",      # Matching question
    "numerical",     # Numerical answer required
    "proof",         # Mathematical proof required
    "other",         # Doesn't fit other categories
]
```

---

## API Architecture

### Endpoint Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/health` | GET | Detailed health status with config |
| `/extract` | POST | Synchronous extraction (waits for completion) |
| `/extract/stream` | POST | SSE streaming (real-time progress updates) |
| `/extract/batch` | POST | Batch extraction (multiple PDFs) |
| `/schema` | GET | JSON Schema for output format |

### SSE Streaming Protocol

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Client->>Server: POST /extract/stream<br/>{"pdf_path": "/path/to/test.pdf"}
    Server-->>Client: data: {"status": "started", "pdf": "..."}
    Server-->>Client: data: {"status": "processing",<br/>"step": "extract_images",<br/>"message": "Extracted 24 images"}
    Server-->>Client: data: {"status": "processing",<br/>"step": "gemini_extraction",<br/>"page": 1, "total_pages": 7}
    Note over Server,Client: ...progress events...
    Server-->>Client: data: {"status": "complete",<br/>"questions_extracted": 42,<br/>"usage": {...}}
```

### Request/Response Examples

**Synchronous Extraction:**

```bash
# Request
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test3.pdf"}'

# Response
{
  "status": "ok",
  "output_json_path": "/outputs/test3/test3_questions.json",
  "assets_dir": "/outputs/test3/assets",
  "processing_time_seconds": 50.2
}
```

---

## Prompt Engineering

### System Prompt Structure

The system prompt is carefully engineered for reliable extraction:

```mermaid
flowchart TB
    subgraph Prompt["SYSTEM PROMPT SECTIONS"]
        direction TB
        S1["1. ROLE DEFINITION<br/>You are an expert at extracting structured questions..."]
        S2["2. CRITICAL REQUIREMENTS<br/>• Extract ALL questions from every page<br/>• Use unique IDs with section prefixes<br/>• Preserve document structure<br/>• Preserve mathematical notation (LaTeX)"]
        S3["3. MCQ HANDLING<br/>• List all options with labels<br/>• Mark correct answers<br/>• Preserve answer column values"]
        S4["4. MULTI-PART HANDLING<br/>• Create parent with type='multi_part'<br/>• Include sub_questions array"]
        S5["5. OUTPUT FORMAT SPECIFICATION<br/>• Detailed JSON structure<br/>• Field types and requirements"]
        S6["6. FINAL CHECKLIST<br/>• Verification steps before returning"]
        
        S1 --> S2 --> S3 --> S4 --> S5 --> S6
    end
```

### Dynamic Image Reference Instructions

```python
# When images are extracted, inform the model about actual filenames
if extracted_images:
    image_list = [img.get("filename", "") for img in extracted_images]
    image_info = f"The following figures have been extracted: {image_list}.
                   Use these exact filenames when referencing figures."
else:
    image_info = "Reference figures by their label (e.g., 'Figure 1')."
```

### LaTeX Preservation Guidelines

```
Mathematical Notation Requirements:
─────────────────────────────────
• Triangle: $\Delta ABC$
• Angle: $\angle B = 50^\circ$
• Fraction: $\frac{a}{b}$
• Subscript/Superscript: $A_n$, $x^2$, $4AD^2$
• Greek letters: $\pi$, $\theta$, $\alpha$
• Congruent: $\cong$
• Parallel: $\parallel$
• Perpendicular: $\perp$
```

---

## Concurrency Model

### Batch Processing Architecture

```mermaid
flowchart TB
    subgraph Input["Input PDFs"]
        PDF1[pdf1.pdf]
        PDF2[pdf2.pdf]
        PDF3[pdf3.pdf]
        PDF4[pdf4.pdf]
        PDF5[pdf5.pdf]
        PDF6[pdf6.pdf]
    end

    Semaphore["Semaphore (max_concurrent=5)"]
    
    subgraph Running["Running Concurrently (async)"]
        P1[PDF1 Processing]
        P2[PDF2 Processing]
        P3[PDF3 Processing]
        P4[PDF4 Processing]
        P5[PDF5 Processing]
    end
    
    Waiting["PDF6 (waiting)"]
    
    subgraph Complete["Completed"]
        D1[Done]
        D2[Done]
        D3[Done]
        D4[Done]
        D5[Done]
    end
    
    P6Start["PDF6 starts"]

    PDF1 & PDF2 & PDF3 & PDF4 & PDF5 --> Semaphore
    PDF6 --> Waiting
    Semaphore --> Running
    P1 --> D1
    P2 --> D2
    P3 --> D3
    P4 --> D4
    P5 --> D5
    D5 --> P6Start
    Waiting -.-> P6Start
```

### Implementation

```python
async def process_batch(self, pdf_paths: List[str], max_concurrent: int = 5):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(pdf_path: str):
        async with semaphore:  # Acquire semaphore slot
            return await self.process_pdf(pdf_path)

    # Create all tasks
    tasks = [process_with_semaphore(path) for path in pdf_paths]

    # Run concurrently with exception handling
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
```

### Thread Safety Considerations

```mermaid
flowchart TB
    subgraph Isolated["✓ Each PDF gets its own:"]
        direction TB
        O1["Output directory (isolated write paths)"]
        O2["GeminiClient instance (separate token tracking)"]
        O3["QuestionParser instance (separate ID deduplication set)"]
    end

    subgraph Shared["✓ Shared resources (read-only):"]
        direction TB
        S1["API key"]
        S2["Configuration"]
    end

    subgraph AsyncModel["✓ Async/await model prevents race conditions:"]
        direction TB
        A1["Single-threaded event loop"]
        A2["Semaphore controls concurrent API calls"]
    end
```

---

## Token & Cost Management

### Token Tracking Flow

```mermaid
flowchart TD
    A[API Call] --> B["OpenRouter Response<br/>{id: 'gen-abc123', usage: {...}, choices: [...]}"]
    B --> C["UsageStats.add(usage, generation_id)"]
    C --> D["Saved to output JSON:<br/>{prompt_tokens: 5000, completion_tokens: 9498,<br/>total_tokens: 14498, generation_ids: ['gen-abc123']}"]
```

### Cost Estimation

```python
# Gemini 3 Flash pricing (via OpenRouter)
PRICE_PER_1M_INPUT_TOKENS = 0.50   # $0.50 per million input tokens
PRICE_PER_1M_OUTPUT_TOKENS = 3.00  # $3.00 per million output tokens

estimated_cost = (
    (prompt_tokens * 0.50 / 1_000_000) +
    (completion_tokens * 3.00 / 1_000_000)
)

# Example for test3.pdf:
# 5,002 prompt + 9,525 completion
# Cost: (5002 * 0.50 + 9525 * 3.00) / 1_000_000 = ~$0.031
```

---

## Error Handling

### Error Hierarchy

```mermaid
flowchart TB
    subgraph Layer1["Layer 1: Pipeline Level"]
        direction TB
        L1A["PDF not found → ExtractResponse(status='error')"]
        L1B["Invalid file type → ExtractResponse(status='error')"]
        L1C["Processing exception → Logged + wrapped"]
    end

    subgraph Layer2["Layer 2: API Level"]
        direction TB
        L2A["HTTP Status Errors → Re-raised with context"]
        L2B["Timeout → Logged + re-raised"]
        L2C["JSON Parse Error → Return {questions: [], error}"]
    end

    subgraph Layer3["Layer 3: Batch Level"]
        direction TB
        L3A["Individual failures don't stop batch"]
        L3B["Exceptions caught per PDF"]
        L3C["Results include success/error status per file"]
    end

    subgraph Layer4["Layer 4: Server Level"]
        direction TB
        L4A["Generic exception handler → 500 response"]
        L4B["HTTPException → Proper HTTP status codes"]
        L4C["All errors logged with traceback"]
    end

    Layer1 --> Layer2 --> Layer3 --> Layer4
```

### Graceful Degradation

```python
# Batch processing continues even if individual PDFs fail
for i, result in enumerate(results):
    if isinstance(result, Exception):
        logger.error(f"Batch task failed: {result}")
        final_results.append(
            (pdf_paths[i], ExtractResponse(status="error", error=str(result)))
        )
    else:
        final_results.append(result)
```

---

## Technical Nuances

### 1. Native PDF Encoding

```python
def _encode_pdf(self, pdf_path: str) -> str:
    """
    PDFs are sent to OpenRouter as base64-encoded data URLs.
    This leverages Gemini's native PDF understanding capabilities.
    """
    with open(path, "rb") as f:
        pdf_data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:application/pdf;base64,{pdf_data}"
```

### 2. Image Reference Resolution

The model may reference images generically (e.g., "figure_1") but we need actual filenames:

```python
# Build comprehensive mapping for flexible matching
mapping = {
    "1": "test3_001.png",
    "figure_1": "test3_001.png",
    "fig_1": "test3_001.png",
    "figure 1": "test3_001.png",
    "image_1": "test3_001.png",
    "test3_001": "test3_001.png",
    "test3_001.png": "test3_001.png",
}

# Resolution order:
# 1. Exact match
# 2. Lowercase match
# 3. Extract number from reference ("Figure 5" → "5")
# 4. Fall back to original reference
```

### 3. Cross-Page Question Detection

When using chunked mode, questions may span pages:

```python
def _looks_like_continuation(self, text: str) -> bool:
    """Detect if text is a continuation of previous question."""

    # Starts with lowercase letter
    if text[0].islower():
        return True

    # Starts with continuation words
    continuation_starters = ["and", "or", "but", "where", "such", "then"]
    first_word = text.split()[0].lower()
    if first_word in continuation_starters:
        return True

    return False
```

### 4. ID Deduplication

Prevent duplicate question IDs across sections:

```python
# Handle duplicate IDs by appending suffix
original_id = q_id
suffix = 1
while q_id in self._seen_ids:
    q_id = f"{original_id}_{suffix}"
    suffix += 1
self._seen_ids.add(q_id)
```

### 5. Image Deduplication

Prevent same image saved multiple times:

```python
# MD5 hash for duplicate detection
img_hash = hashlib.md5(image_bytes).hexdigest()[:12]
if img_hash in self._seen_hashes:
    continue  # Skip duplicate
self._seen_hashes.add(img_hash)
```

### 6. Temperature Setting

```python
"temperature": 0.1  # Low for deterministic, consistent extraction
```

Low temperature ensures:
- Consistent output structure
- Reproducible extractions
- Less creative "interpretation" of content

### 7. Max Token Configuration

```python
"max_tokens": 65536  # Generous limit for full document extraction
```

Large limit ensures:
- All questions can be extracted
- Long multi-part questions aren't truncated
- Tables and LaTeX aren't cut off

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Required | API key for OpenRouter |
| `MAX_CONCURRENT_PDFS` | `5` | Maximum parallel PDF processing |
| `IMAGE_DPI` | `300` | Image rendering resolution |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Internal Constants

| Constant | Value | Location |
|----------|-------|----------|
| `MAX_PAGES_FOR_NATIVE` | `30` | `pipeline.py` |
| `MAX_PAGES_PER_PDF` | `50` | `config.py` |
| `REQUEST_TIMEOUT` | `120` | `config.py` |
| `MIN_IMAGE_SIZE` | `50` | `image_extractor.py` |
| `PDF_DPI` | `72` | Standard PDF DPI |
| `RENDER_DPI` | `300` | `pdf_converter.py` |

### Output Structure

```
outputs/
└── {pdf_name}/
    ├── {pdf_name}_questions.json   # Main output
    ├── assets/                     # Extracted images
    │   ├── {pdf_name}_001.png
    │   ├── {pdf_name}_002.jpeg
    │   └── ...
    └── pages/                      # Page images (chunked mode)
        ├── page_001.png
        └── ...
```

---

## Performance Benchmarks

| Metric | Value | Notes |
|--------|-------|-------|
| **7-page PDF** | ~43s | Native PDF mode |
| **Processing rate** | ~7s/page | Average with native mode |
| **Concurrent PDFs** | 5 | Default semaphore limit |
| **Cost per PDF** | ~$0.01-0.06 | Depends on size |
| **Token efficiency** | ~2,100 tokens/page | Average |

### Native vs Page-by-Page Comparison

| Aspect | Native PDF | Page-by-Page |
|--------|------------|--------------|
| Questions extracted | **42** | 33 |
| MCQs captured | **20/20** | 11/20 |
| Processing time | **~43s** | ~74s |
| Context quality | **Full document** | Per-page only |
| Cross-page questions | **Automatic** | Heuristic merge |

---

*Last updated: December 2024*

