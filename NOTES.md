# NOTES: PDF Questions Extractor

## Approach

### Vision-First Architecture

Instead of traditional PDF text extraction (which struggles with LaTeX, complex layouts, and embedded content), this project uses a **vision-based approach**:

1. **PDF → High-Resolution Images** (300 DPI via PyMuPDF)
2. **Images → VLM Processing** (Gemini 3 Flash via OpenRouter)
3. **Structured JSON Output** with schema validation

**Why this works better:**
- VLMs "see" the page exactly as humans do
- No issues with font encoding, LaTeX rendering, or complex layouts
- Tables, figures, and mathematical notation are naturally understood
- Single unified pipeline instead of multiple specialized extractors

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Gemini 3 Flash | Fast, cost-effective (~$0.01/PDF), excellent vision |
| PyMuPDF for PDF→Image | Fastest Python library, reliable rendering |
| Async processing | Enables concurrent PDF processing (≥5 simultaneous) |
| Pydantic schemas | Type safety, automatic validation, JSON Schema export |
| SSE streaming | Real-time progress for long-running extractions |
| Per-batch usage tracking | Thread-safe token counting for parallel processing |

---

## Methods Used

### PDF Processing
- **PyMuPDF (fitz)**: PDF rendering at 300 DPI
- **Embedded image extraction**: Hash-based deduplication, size filtering (≥50px)

### Question Extraction
- **Vision Language Model**: Gemini 3 Flash via OpenRouter API
- **Structured output**: JSON mode with detailed system prompt
- **Temperature 0.1**: Low temperature for consistent, deterministic extraction

### Post-Processing
- **Cross-page detection**: Merge questions spanning multiple pages
- **Schema validation**: Pydantic models ensure output correctness
- **Hierarchical nesting**: Sub-questions properly nested under parent

### API Features
- **SSE Streaming**: `/extract/stream` endpoint for real-time progress
- **Batch processing**: Concurrent extraction with semaphore limiting
- **Token tracking**: Per-PDF usage stats saved to output JSON

---

## Trade-offs

| Choice | Pros | Cons |
|--------|------|------|
| Vision-based extraction | Robust to any PDF format, handles LaTeX/tables naturally | Requires API costs (~$0.01/PDF), needs internet |
| Page-level processing | Simple, reliable, easy to parallelize | Cross-page questions require post-processing |
| Synchronous page processing | Simpler, easier debugging | Not optimal for large PDFs (could batch pages) |
| SSE streaming | Real-time progress visibility | More complex client handling |

---

## What Worked Well

1. **LaTeX preservation**: Gemini accurately extracts and preserves mathematical notation
2. **MCQ detection**: Options (a, b, c, d) reliably identified with answer marking
3. **Table extraction**: Structured table output with headers and rows
4. **Multi-part parsing**: Hierarchical questions (1.a.i) correctly nested
5. **Parallel processing**: 5 PDFs concurrently, total time < sum of individual times
6. **Token tracking**: Accurate per-PDF usage with cost estimation

---

## Challenges & Limitations

1. **Cross-page questions**: Heuristic-based merging may miss edge cases
2. **Answer key detection**: Some PDFs have answers inline, others separate
3. **Complex layouts**: Multi-column or unusual layouts may confuse extraction
4. **Image references**: Linking extracted images to specific questions is approximate
5. **Rate limiting**: High-volume usage may hit OpenRouter rate limits

---

## Baseline → Improvements

| Version | Features |
|---------|----------|
| **Baseline** | Single-pass page extraction, basic question detection |
| **Improvement 1** | Cross-page question detection and merging |
| **Improvement 2** | Structured prompting with examples, LaTeX handling |
| **Improvement 3** | SSE streaming for real-time progress |
| **Improvement 4** | Thread-safe per-batch token tracking |

---

## Performance Results (5 Test PDFs)

| PDF | Pages | Time | Questions | Tokens | Cost |
|-----|-------|------|-----------|--------|------|
| test1.pdf | 8 | 50s | 10 | 57K | $0.012 |
| test2.pdf | 3 | 27s | 15 | 27K | $0.006 |
| test3.pdf | 7 | 74s | 33 | 76K | $0.015 |
| test4.pdf | 3 | 38s | 30 | 48K | $0.010 |
| test5.pdf | 16 | 159s | 63 | 103K | $0.020 |
| **Total** | **37** | **162s** | **151** | **311K** | **$0.063** |

All within the 3-minute target for 10-page PDFs. Parallel processing reduced total time from ~6 min (sequential) to ~3 min.

---

## Prioritized Next Steps

If more time were available:

1. **[ ] Page batching**: Send 2-3 pages together for better context
2. **[ ] Confidence scoring**: Add confidence scores to extracted fields
5. **[ ] Caching layer**: Cache API responses for identical pages
