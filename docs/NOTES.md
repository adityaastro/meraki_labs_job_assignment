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
| Native PDF via OpenRouter     | Full document context, better accuracy                  |
| Gemini 3.0 Flash              | Fast, cost-effective, excellent PDF understanding       |
| PyMuPDF for image extraction  | Reliable embedded image extraction                      |
| Async processing              | Enables concurrent PDF processing (≥5 simultaneous)     |
| Pydantic schemas              | Type safety, automatic validation, JSON Schema export   |
| Fallback to page-by-page      | For PDFs >30 pages (token limit safety)                |
| Section-aware prompting       | Unique IDs: MCQ_*, SEC_II_*, SEC_III_*                  |

---

## Methods Used

### PDF Processing
- **Native PDF upload**: Base64-encoded PDF sent directly to OpenRouter
- **PyMuPDF (fitz)**: Embedded image extraction with hash-based deduplication
- **Fallback mode**: Page-by-page processing for very large PDFs (>30 pages)

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

| Choice                 | Pros                                | Cons                                      |
|------------------------|-------------------------------------|-------------------------------------------|
| Native PDF processing  | Full document context, better accuracy | Requires API costs, needs internet        |
| Section-aware prompting | Unique IDs, proper structure         | Relies on model understanding sections    |
| Image filename mapping | Links to real assets                | Approximate matching for unlabeled figures |
| Fallback for large PDFs| Handles any PDF size                | Less context for >30 page documents       |

---

## What Worked Well

1. **Complete extraction**: All 20 MCQs captured (vs. 11 with old approach)
2. **Section preservation**: MCQ_*, SEC_II_*, SEC_III_* prefixes maintained
3. **Image linking**: References resolved to actual asset filenames (test3_001.png, etc.)
4. **LaTeX preservation**: Mathematical notation accurately extracted
5. **MCQ detection**: Options reliably identified with answer marking
6. **Multi-part parsing**: Hierarchical questions correctly nested
7. **Parallel processing**: 5 PDFs concurrently with proper isolation

---

## Baseline → Improvements

| Version         | Features                                       |
|-----------------|------------------------------------------------|
| **Baseline**    | Page-by-page image extraction, basic detection |
| **Improvement 1** | Native PDF processing (full document context)  |
| **Improvement 2** | Section-aware prompting with unique IDs        |
| **Improvement 3** | Image filename mapping to actual assets        |
| **Improvement 4** | Automatic fallback for large PDFs              |

---

## Performance Results (test3.pdf Comparison)

| Metric             | Old (Page-by-Page) | New (Native PDF)   |
|--------------------|-------------------|-------------------|
| Total Questions    | 33                | **42**            |
| MCQs Extracted     | 11                | **20**            |
| Missing Q10-18     | Yes               | **No**            |
| Unique IDs         | Duplicates        | **All unique**    |
| Image Links        | Generic names     | **Actual filenames**|
| Processing Time    | ~74s              | **~43s**          |

---

## Challenges & Limitations

1. **Token limits**: Very large PDFs (>30 pages) require fallback mode
2. **Complex layouts**: Unusual multi-column layouts may still confuse extraction
3. **Image references**: Mapping depends on figure numbering in document
4. **Rate limiting**: High-volume usage may hit OpenRouter rate limits
5. **Cost**: API calls required for each extraction (~$0.01-0.06/PDF)

---

## Prioritized Next Steps

If more time were available:

1. **[ ] Confidence scoring**: Add confidence scores to extracted fields
2. **[ ] Batch PDF processing**: Send multiple small PDFs in one request
3. **[ ] Caching layer**: Cache API responses for identical documents
4. **[ ] Human-in-the-loop**: Review interface for edge cases
5. **[ ] Fine-tuning**: Train on educational document patterns