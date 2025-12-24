# NOTES: PDF Questions Extractor

## Approach

### Native PDF Processing Architecture

This project uses **OpenRouter's native PDF processing** to send entire PDFs directly to Gemini for extraction. This gives the model full document context, improving accuracy significantly.

**Pipeline Flow:**
1. **Extract Embedded Images** (PyMuPDF) → Save as assets
2. **Send PDF Natively** (OpenRouter API) → Full document to Gemini
3. **Structured JSON Output** with schema validation

**Why native PDF processing works better:**
- Model sees the **entire document at once** (full context)
- No page-by-page context loss
- Section structures (MCQs, Proofs, etc.) naturally understood
- Better handling of cross-page questions
- Simpler pipeline (no PDF → Image conversion for extraction)

### Key Design Decisions

| Decision                      | Rationale                                               |
|-------------------------------|---------------------------------------------------------|
| Native PDF via OpenRouter     | Full document context, superior accuracy                 |
| Gemini 3.0 Flash              | High performance, efficient PDF understanding           |
| PyMuPDF for image extraction  | Reliable high-resolution asset extraction               |
| Async processing              | High throughput (≥5 concurrent PDFs)                    |
| Pydantic schemas              | Type safety and automatic JSON Schema generation        |
| Chunked processing for scale  | Ensures performance on very large documents             |
| Section-aware prompting       | Intelligent structural identification (MCQ_*, etc.)     |

---

## Methods Used

### PDF Processing
- **Native PDF upload**: Base64-encoded PDF sent directly to OpenRouter
- **PyMuPDF (fitz)**: Embedded image extraction with hash-based deduplication
- **Chunked mode**: Page-by-page processing for very large PDFs (>30 pages)

### Question Extraction
- **Vision Language Model**: Gemini via OpenRouter API with native PDF support
- **Structured output**: JSON mode with comprehensive system prompt
- **Section-aware extraction**: Unique ID prefixes per section (MCQ_*, SEC_II_*, etc.)
- **Temperature 0.1**: Low temperature for consistent, deterministic extraction

### Post-Processing
- **Image filename mapping**: Resolves generic references to actual asset filenames
- **ID deduplication**: Ensures unique question IDs across sections
- **Schema validation**: Pydantic models ensure output correctness
- **Hierarchical nesting**: Sub-questions properly nested under parent

### API Features
- **SSE Streaming**: `/extract/stream` endpoint for real-time progress
- **Batch processing**: Concurrent extraction with semaphore limiting
- **Token tracking**: Per-PDF usage stats saved to output JSON

---

## Trade-offs

| Choice                 | Benefits                                | Considerations                            |
|------------------------|-----------------------------------------|-------------------------------------------|
| Native PDF processing  | Full document context, superior recall  | Cloud-based API, requires internet         |
| Section-aware prompting | Automated structure identification      | Model-driven parsing                      |
| Image filename mapping | Seamless link to extracted assets       | Best with labeled figures                 |
| Chunked processing     | Unlimited document scale                | Maintains high accuracy at scale          |

---

## What Worked Well

1. **Complete extraction**: High recall of questions including all MCQs and sub-parts.
2. **Section preservation**: MCQ_*, SEC_II_*, SEC_III_* prefixes maintained
3. **Image linking**: References resolved to actual asset filenames (test3_001.png, etc.)
4. **LaTeX preservation**: Mathematical notation accurately extracted
5. **MCQ detection**: Options reliably identified with answer marking
6. **Multi-part parsing**: Hierarchical questions correctly nested
7. **Parallel processing**: 5 PDFs concurrently with proper isolation

---

## Key Improvements

- **Native PDF processing**: Leveraging model's native understanding for full document context.
- **Section-aware prompting**: Intelligent ID generation based on document structure.
- **Image filename mapping**: Automated resolution of image references to actual assets.
- **Robustness**: Advanced error handling and automatic chunked processing for very large documents.

---

## System Considerations

1. **Large Document Handling**: PDFs exceeding 30 pages are processed using an automated chunked approach to maintain accuracy within model limits.
2. **Complex Layouts**: The system is optimized for standard educational document layouts; highly irregular formats may require additional tuning.
3. **Image Mapping**: Best performance is achieved when figures are labeled (e.g., "Figure 1") within the document.
4. **API Management**: The architecture includes robustness features like circuit breakers to handle API rate limits and transient failures.

---

## Prioritized Next Steps

If more time were available:

1. **[ ] Confidence scoring**: Add confidence scores to extracted fields
2. **[ ] Batch PDF processing**: Send multiple small PDFs in one request
3. **[ ] Caching layer**: Cache API responses for identical documents
4. **[ ] Human-in-the-loop**: Review interface for edge cases
5. **[ ] Fine-tuning**: Train on educational document patterns