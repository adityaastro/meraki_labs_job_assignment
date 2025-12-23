#!/bin/bash
# PDF Questions Extractor - Batch Processing Script
# Usage: bash run_eval.sh pdfs/*.pdf outputs/
#        bash run_eval.sh test1.pdf test2.pdf test3.pdf outputs/

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================================="
echo "   PDF Questions Extractor - Batch Processor"
echo "=================================================="

# Check arguments
if [ $# -lt 1 ]; then
    echo -e "${RED}Usage: $0 <pdf_files...> [output_dir]${NC}"
    echo "Examples:"
    echo "  $0 test1.pdf test2.pdf"
    echo "  $0 pdfs/*.pdf outputs/"
    exit 1
fi

# Parse arguments - last arg might be output dir
LAST_ARG="${!#}"  # Get last argument using indirect reference

# Check if last argument is a directory or looks like an output path
if [[ -d "$LAST_ARG" ]] || [[ "$LAST_ARG" == */ ]] || [[ "$LAST_ARG" != *.pdf ]]; then
    # Last argument is output directory
    OUTPUT_DIR="$LAST_ARG"
    # Get all arguments except the last one
    PDF_COUNT=$(($# - 1))
    PDF_FILES=("${@:1:$PDF_COUNT}")
else
    # No output directory specified, all args are PDFs
    OUTPUT_DIR="outputs"
    PDF_FILES=("$@")
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "Output directory: $OUTPUT_DIR"
echo "PDFs to process: ${#PDF_FILES[@]}"
echo ""

# Check for virtual environment
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Check for .env file
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}Warning: .env file not found. Creating from .env.example${NC}"
        cp .env.example .env
        echo -e "${RED}Please set OPENROUTER_API_KEY in .env file${NC}"
        exit 1
    fi
fi

# Load environment variables
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check API key
if [ -z "$OPENROUTER_API_KEY" ] || [ "$OPENROUTER_API_KEY" == "your_openrouter_api_key_here" ]; then
    echo -e "${RED}Error: OPENROUTER_API_KEY not set or invalid${NC}"
    echo "Please set it in .env file"
    exit 1
fi

# Record start time
START_TIME=$(date +%s)

# Run extraction
echo "Starting extraction..."
echo ""

python -m src.cli "${PDF_FILES[@]}" -o "$OUTPUT_DIR" --concurrent 5

# Record end time
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=================================================="
echo "Batch processing complete!"
echo "Total time: ${DURATION}s"
echo "Output directory: $OUTPUT_DIR"
echo "=================================================="

# List output files
echo ""
echo "Generated files:"
find "$OUTPUT_DIR" -name "*_questions.json" -type f 2>/dev/null | while read f; do
    SIZE=$(ls -lh "$f" | awk '{print $5}')
    QUESTIONS=$(python3 -c "import json; print(len(json.load(open('$f'))['questions']))" 2>/dev/null || echo "?")
    echo "  - $(basename "$f") ($SIZE, $QUESTIONS questions)"
done
