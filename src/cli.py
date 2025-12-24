"""
CLI for PDF Question Extraction.
Provides command-line interface for processing PDFs.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import List

from src.core.config import config
from src.pipeline import ExtractionPipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract questions from PDF files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.cli test1.pdf
  python -m src.cli pdfs/*.pdf -o outputs/
  python -m src.cli pdfs/*.pdf --concurrent 5
        """,
    )

    parser.add_argument("pdf_files", nargs="*", help="PDF files to process")

    parser.add_argument(
        "-o", "--output", default="outputs", help="Output directory (default: outputs)"
    )

    parser.add_argument(
        "-c",
        "--concurrent",
        type=int,
        default=5,
        help="Maximum concurrent PDFs (default: 5)",
    )

    parser.add_argument(
        "--api-key", help="OpenRouter API key (or set OPENROUTER_API_KEY env var)"
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate output JSON files, don't extract",
    )

    return parser.parse_args()


async def run_extraction(
    pdf_files: List[str], output_dir: str, max_concurrent: int, api_key: str = None
):
    """Run extraction on multiple PDFs."""

    # Filter to existing PDF files
    valid_pdfs = []
    for pdf_path in pdf_files:
        path = Path(pdf_path)
        if path.exists() and path.suffix.lower() == ".pdf":
            valid_pdfs.append(str(path.absolute()))
        else:
            logger.warning(f"Skipping invalid file: {pdf_path}")

    if not valid_pdfs:
        logger.error("No valid PDF files found")
        return []

    logger.info(
        f"Processing {len(valid_pdfs)} PDF(s) with max {max_concurrent} concurrent"
    )

    # Initialize pipeline
    pipeline = ExtractionPipeline(api_key=api_key, output_base_dir=output_dir)

    # Process PDFs
    start_time = time.time()
    results = await pipeline.process_batch(valid_pdfs, max_concurrent)
    total_time = time.time() - start_time

    # Print summary
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)

    success_count = 0
    error_count = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_questions = 0

    for pdf_path, response in results:
        pdf_name = Path(pdf_path).name
        status_icon = "✓" if response.status == "ok" else "✗"

        if response.status == "ok":
            success_count += 1
            print(f"{status_icon} {pdf_name}")
            print(f"  Output: {response.output_json_path}")
            print(f"  Time: {response.processing_time_seconds:.2f}s")

            # Read token usage from output file
            try:
                with open(response.output_json_path) as f:
                    output_data = json.load(f)
                usage = output_data.get("usage", {})
                questions_count = len(output_data.get("questions", []))
                total_questions += questions_count

                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens
                
                cost = usage.get("estimated_cost_usd", 0)

                print(f"  Questions: {questions_count}")
                print(
                    f"  Tokens: {prompt_tokens:,} prompt + {completion_tokens:,} completion = {prompt_tokens + completion_tokens:,} total"
                )
                print(f"  Estimated Cost: ${cost:.6f}")
            except Exception:
                pass
        else:
            error_count += 1
            print(f"{status_icon} {pdf_name}")
            print(f"  Error: {response.error}")

    print("=" * 60)
    print(
        f"Total: {len(results)} PDFs | Success: {success_count} | Errors: {error_count}"
    )
    print(f"Total questions extracted: {total_questions}")
    print(
        f"Total tokens: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion = {total_prompt_tokens + total_completion_tokens:,} total"
    )

    # Estimate cost
    estimated_cost = (total_prompt_tokens * config.MODEL_COST_INPUT_1M / 1_000_000) + (
        total_completion_tokens * config.MODEL_COST_OUTPUT_1M / 1_000_000
    )
    print(f"Estimated cost: ${estimated_cost:.6f}")

    print(f"Total time: {total_time:.2f}s")
    print("=" * 60)

    return results


def validate_outputs(output_dir: str):
    """Validate output JSON files against schema."""
    from jsonschema import validate, ValidationError
    from src.core.schemas import get_json_schema

    output_path = Path(output_dir)
    if not output_path.exists():
        logger.error(f"Output directory not found: {output_dir}")
        return

    schema = get_json_schema()
    json_files = list(output_path.rglob("*_questions.json"))

    if not json_files:
        logger.warning("No output JSON files found")
        return

    print(f"\nValidating {len(json_files)} output files...")

    valid_count = 0
    invalid_count = 0

    for json_file in json_files:
        try:
            with open(json_file) as f:
                data = json.load(f)

            validate(instance=data, schema=schema)
            print(f"✓ {json_file.name} - Valid")
            valid_count += 1

        except ValidationError as e:
            print(f"✗ {json_file.name} - Invalid")
            print(f"  Error: {e.message}")
            invalid_count += 1

        except json.JSONDecodeError as e:
            print(f"✗ {json_file.name} - Invalid JSON")
            print(f"  Error: {e}")
            invalid_count += 1

    print(f"\nValidation complete: {valid_count} valid, {invalid_count} invalid")


def main():
    """Main entry point."""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check for API key
    api_key = args.api_key or config.OPENROUTER_API_KEY
    if not api_key and not args.validate_only:
        logger.error(
            "OpenRouter API key required. Set OPENROUTER_API_KEY or use --api-key"
        )
        sys.exit(1)

    if args.validate_only:
        validate_outputs(args.output)
    else:
        if not args.pdf_files:
            logger.error("No PDF files specified for extraction")
            sys.exit(1)
        # Run extraction
        asyncio.run(
            run_extraction(
                pdf_files=args.pdf_files,
                output_dir=args.output,
                max_concurrent=args.concurrent,
                api_key=api_key,
            )
        )


if __name__ == "__main__":
    main()
