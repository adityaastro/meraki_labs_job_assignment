# EVAL: Evaluation System Design

## Overview

This document describes how to evaluate the PDF Questions Extractor system, including automated metrics, manual verification procedures, and quality assessment frameworks.

---

## 1. Automated Evaluation

### 1.1 Schema Validation

```bash
# Validate all outputs against JSON schema
python -m src.cli --validate-only -o outputs/
```

### 1.2 Performance Metrics

```bash
# Run batch extraction with timing
bash run_eval.sh test*.pdf outputs/

# Output includes per-PDF:
# - Processing time
# - Questions extracted
# - Token usage
# - Estimated cost
```

**Targets:**
| Metric | Target | How to Verify |
|--------|--------|---------------|
| Runtime (10-page PDF) | ≤180s | CLI output shows time per PDF |
| Concurrent PDFs | ≥5 | Total time < sum of individual times |
| Memory usage | <2GB | Monitor with `htop` during batch run |

### 1.3 API Endpoint Testing

```bash
# Start server
uvicorn src.api.server:app --reload &

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/schema

# Standard extraction
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}'

# SSE streaming extraction
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}'
```

---

## 2. Manual Verification

### 2.1 Checklist per PDF

| Check | Description | Pass Criteria |
|-------|-------------|---------------|
| Question Count | Compare extracted vs. actual | ≥90% questions detected |
| Numbering | Original numbering preserved | Exact match (1., a., i.) |
| MCQ Options | All options captured | 100% options with labels |
| MCQ Answers | Correct answer marked | Correct if shown in source |
| LaTeX | Mathematical notation | Readable, parseable LaTeX |
| Tables | Structure preserved | Headers + rows correct |
| Images | Referenced correctly | Filename exists in assets/ |
| Multi-part | Hierarchy preserved | Correct parent-child nesting |

### 2.2 Sample Verification Process

1. Open source PDF and output JSON side-by-side
2. For each question:
   - Locate in JSON by number
   - Verify content matches
   - Check type classification
   - Verify options/sub-questions
3. Document discrepancies

---

## 3. Quality Metrics

### 3.1 Extraction Quality Score

```
Score = (
    0.4 × Question Recall +      # % questions found
    0.2 × Type Accuracy +        # % correct classifications
    0.2 × Content Fidelity +     # Text match score
    0.1 × Structure Score +      # MCQ/multi-part correct
    0.1 × Asset Score            # Images properly linked
)
```

### 3.2 Token Usage Analysis

```python
import json
from pathlib import Path

total_tokens = 0
total_questions = 0

for f in Path("outputs").rglob("*_questions.json"):
    data = json.load(open(f))
    usage = data.get("usage", {})
    questions = len(data.get("questions", []))
    
    print(f"{f.name}: {questions} questions, {usage.get('total_tokens', 0):,} tokens")
    total_tokens += usage.get("total_tokens", 0)
    total_questions += questions

print(f"\nTotal: {total_questions} questions, {total_tokens:,} tokens")
print(f"Tokens per question: {total_tokens / total_questions:.0f}")
```

---

## 4. Test Scenarios

### 4.1 Content Types (covered by test PDFs)

| PDF | Focus | Key Tests |
|-----|-------|-----------|
| test1.pdf | Sequences & Series | Multi-part questions, LaTeX formulas |
| test2.pdf | Precalculus | Tables, sigma notation, recursive sequences |
| test3.pdf | Geometry | MCQs with figures, answer keys |
| test4.pdf | Surface Areas | MCQs, formulas mixed with options |
| test5.pdf | Practice Test | Mixed types, varying layouts |

### 4.2 Edge Cases

```bash
# Empty/corrupted PDF
echo "not a pdf" > fake.pdf
python -m src.cli fake.pdf -o outputs/
# Expected: Error handling, no crash

# Very large PDF
# Expected: Respects MAX_PAGES_PER_PDF limit

# Non-PDF file
python -m src.cli test.txt -o outputs/
# Expected: Skipped or error message
```

---

## 5. SSE Streaming Validation

### 5.1 Progress Events

Test that all expected events are streamed:

```bash
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/test1.pdf"}' | jq .
```

**Expected event sequence:**
1. `{"status": "started", "pdf": "..."}`
2. `{"status": "processing", "step": "pdf_to_images", ...}`
3. `{"status": "processing", "step": "extract_images", ...}`
4. `{"status": "processing", "step": "gemini_extraction", "page": 1, ...}`
5. ... (one per page)
6. `{"status": "processing", "step": "merge", ...}`
7. `{"status": "complete", "questions_extracted": N, ...}`

### 5.2 Error Handling in Stream

```bash
# Test with non-existent file
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/nonexistent.pdf"}'

# Expected: {"status": "error", "error": "PDF file not found..."}
```

---

## 6. Regression Testing

### 6.1 Track Metrics Over Time

```python
# Save metrics to CSV after each run
import csv
from datetime import datetime

def log_metrics(results):
    with open("eval_history.csv", "a") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(),
            results["total_questions"],
            results["total_tokens"],
            results["total_time"],
            results["success_rate"]
        ])
```

### 6.2 CI/CD Integration

```yaml
# .github/workflows/eval.yml
name: Evaluation
on: [push]
jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with: {python-version: '3.10'}
      - name: Install
        run: pip install -r requirements.txt
      - name: Run extraction
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: bash run_eval.sh test*.pdf outputs/
      - name: Validate
        run: python -m src.cli --validate-only -o outputs/
```

---

## 7. Quick Evaluation Commands

```bash
# Full evaluation run
source venv/bin/activate

# 1. Run batch extraction
bash run_eval.sh test*.pdf outputs/

# 2. Validate outputs
python -m src.cli --validate-only -o outputs/

# 3. Test API endpoints
uvicorn src.api.server:app --reload &
curl http://localhost:8000/health
curl -N http://localhost:8000/extract/stream \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "'$(pwd)'/test1.pdf"}'

# 4. Check token usage
python -c "
import json
from pathlib import Path
for f in Path('outputs').rglob('*_questions.json'):
    d = json.load(open(f))
    u = d.get('usage', {})
    print(f\"{f.name}: {len(d['questions'])} Q, {u.get('total_tokens', 0):,} tokens\")
"
```

---

## Summary

| Evaluation Area | Method | Automation |
|----------------|--------|------------|
| Schema validation | JSON Schema | ✓ Automated |
| Performance | CLI timing | ✓ Automated |
| Content accuracy | Manual review | Partially |
| API endpoints | curl tests | ✓ Automated |
| SSE streaming | Event sequence | ✓ Automated |
| Token usage | Output analysis | ✓ Automated |
