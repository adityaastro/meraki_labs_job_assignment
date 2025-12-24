# Test Scenarios - PDF Questions Extractor

Comprehensive test scenarios for end-to-end validation.

---

## 1. API Server Tests

### 1.1 Health Check
```bash
# Start server
source venv/bin/activate
uvicorn src.api.server:app --host 0.0.0.0 --port 8000 &

# Test health endpoints
curl http://localhost:8000/
curl http://localhost:8000/health
curl http://localhost:8000/schema
```

**Expected:** JSON responses with status "healthy" and schema definition.

### 1.2 Single PDF Extraction
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "tests/test1.pdf"}'
```

**Expected:** `{"status": "ok", "output_json_path": "...", "assets_dir": "..."}`

### 1.3 Invalid PDF Path
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "tests/nonexistent.pdf"}'
```

**Expected:** `{"status": "error", "error": "PDF file not found..."}`

### 1.4 Batch Extraction via API
```bash
curl -X POST http://localhost:8000/extract/batch \
  -H "Content-Type: application/json" \
  -d '["tests/test1.pdf", "tests/test2.pdf"]'
```

**Expected:** Array of results for each PDF.

---

## 2. CLI Tests

### 2.1 Single PDF via CLI
```bash
python -m src.cli test1.pdf -o outputs/
```

**Expected:** 
- Output JSON created in `outputs/test1/`
- Summary shows questions extracted and token usage

### 2.2 Multiple PDFs via CLI
```bash
python -m src.cli test1.pdf test2.pdf test3.pdf -o outputs/
```

**Expected:** All PDFs processed, summary shows totals.

### 2.3 Glob Pattern
```bash
python -m src.cli test*.pdf -o outputs/
```

**Expected:** All matching PDFs processed.

### 2.4 Validation Only
```bash
python -m src.cli --validate-only -o outputs/
```

**Expected:** Validates all `*_questions.json` files against schema.

### 2.5 Missing API Key
```bash
unset OPENROUTER_API_KEY
python -m src.cli test1.pdf -o outputs/
```

**Expected:** Error message about missing API key.

---

## 3. Batch Script Tests

### 3.1 Basic Batch Run
```bash
bash run_eval.sh test1.pdf test2.pdf outputs/
```

### 3.2 All Test PDFs
```bash
bash run_eval.sh test*.pdf outputs/
```

### 3.3 No Output Directory (uses default)
```bash
bash run_eval.sh test1.pdf
```

**Expected:** Uses `outputs/` as default.

---

## 4. Output Validation Tests

### 4.1 JSON Schema Validation
```python
import json
from jsonschema import validate
from src.core.schemas import get_json_schema

with open("outputs/test1/test1_questions.json") as f:
    data = json.load(f)

schema = get_json_schema()
validate(instance=data, schema=schema)
print("✓ Valid")
```

### 4.2 Required Fields Present
```python
# Check output structure
assert "source_pdf" in data
assert "metadata" in data
assert "questions" in data
assert "usage" in data
assert len(data["questions"]) > 0
```

### 4.3 MCQ Options Extraction (test3.pdf, test4.pdf)
```python
# Check MCQ questions have options
mcq_questions = [q for q in data["questions"] if q["type"] == "mcq"]
for q in mcq_questions:
    assert q.get("options"), f"MCQ {q['id']} missing options"
    assert len(q["options"]) >= 2, f"MCQ {q['id']} has too few options"
```

### 4.4 Multi-part Questions (test1.pdf, test2.pdf)
```python
# Check multi-part questions have sub_questions
multi_part = [q for q in data["questions"] if q["type"] == "multi_part"]
for q in multi_part:
    assert q.get("sub_questions"), f"Multi-part {q['id']} missing sub_questions"
```

### 4.5 Image Extraction
```bash
# Check assets directory has images
ls outputs/test1/assets/
# Should show extracted images if PDF had embedded figures
```

---

## 5. Performance Tests

### 5.1 Runtime Constraint (≤3 min for 10-page PDF)
```bash
time python -m src.cli test5.pdf -o outputs/
# test5.pdf has 16 pages, should complete in reasonable time
```

### 5.2 Parallel Processing (≥5 PDFs)
```bash
time bash run_eval.sh test*.pdf outputs/
# Total time should be less than sum of individual times
```

### 5.3 Memory Usage
```bash
# Monitor memory during batch processing
/usr/bin/time -l python -m src.cli test*.pdf -o outputs/
```

---

## 6. Edge Case Tests

### 6.1 Empty PDF (create one for testing)
```python
# Should handle gracefully, return empty questions list
```

### 6.2 PDF with Only Images (no text)
```python
# Should still extract questions from image content
```

### 6.3 Very Large PDF (>50 pages)
```python
# Should respect MAX_PAGES_PER_PDF limit
```

### 6.4 Corrupted PDF
```bash
echo "not a pdf" > fake.pdf
python -m src.cli fake.pdf -o outputs/
# Expected: Error handling, no crash
```

### 6.5 Non-PDF File Extension
```bash
python -m src.cli test.txt -o outputs/
# Expected: Skipped or error
```

---

## 7. Content-Specific Tests

### 7.1 LaTeX Preservation (test1.pdf, test2.pdf)
```python
# Verify LaTeX notation is preserved
for q in data["questions"]:
    text = q["content"]["text"]
    # Check for LaTeX markers like $, \frac, \sum, etc.
```

### 7.2 Table Extraction (test2.pdf)
```python
# Check tables are structured, not flattened
for q in data["questions"]:
    if q["content"].get("table"):
        table = q["content"]["table"]
        assert "rows" in table
```

### 7.3 Question Numbering Preserved
```python
# Verify original numbering is maintained
numbers = [q["number"] for q in data["questions"]]
# Should see: "1.", "2.", "a.", "(i)", etc.
```

---

## 8. Token Usage Tests

### 8.1 Usage Stats in Output
```python
assert "usage" in data
assert data["usage"]["prompt_tokens"] > 0
assert data["usage"]["completion_tokens"] > 0
assert data["usage"]["total_tokens"] > 0
```

### 8.2 Cost Estimation
```python
# Verify cost calculation
prompt = data["usage"]["prompt_tokens"]
completion = data["usage"]["completion_tokens"]
cost = (prompt * 0.10 / 1_000_000) + (completion * 0.40 / 1_000_000)
print(f"Estimated cost: ${cost:.6f}")
```

---

## Quick Test Commands

```bash
# Full test suite
source venv/bin/activate

# 1. Single PDF
python -m src.cli test1.pdf -o outputs/

# 2. All PDFs parallel
bash run_eval.sh test*.pdf outputs/

# 3. Validate outputs
python -m src.cli --validate-only -o outputs/

# 4. Start API server
uvicorn src.api.server:app --reload

# 5. Test API
curl http://localhost:8000/health
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "'$(pwd)'/test1.pdf"}'
```
