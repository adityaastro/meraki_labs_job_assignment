"""
Gemini client via OpenRouter API.
Handles native PDF processing and question extraction.
Tracks token usage and costs.
"""

import base64
import httpx
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from src.core.config import config

logger = logging.getLogger(__name__)


@dataclass
class UsageStats:
    """Tracks token usage and costs across API calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    generation_ids: List[str] = field(default_factory=list)

    def add(self, usage: Dict[str, Any], generation_id: Optional[str] = None):
        """Add usage from an API response."""
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)
        if generation_id:
            self.generation_ids.append(generation_id)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "generation_ids": self.generation_ids,
        }

    def __str__(self) -> str:
        return (
            f"Tokens: {self.total_tokens:,} total "
            f"({self.prompt_tokens:,} prompt + {self.completion_tokens:,} completion)"
        )


# System prompt for full PDF extraction (native PDF processing)
PDF_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting structured questions from educational PDF documents.

Your task is to analyze the ENTIRE PDF document and extract ALL questions in a structured JSON format.

=== CRITICAL REQUIREMENTS ===

1. EXTRACT ALL QUESTIONS FROM EVERY PAGE
   - Do NOT skip any pages
   - Do NOT skip any questions
   - Go through the document systematically page by page

2. USE UNIQUE QUESTION IDs WITH SECTION PREFIXES
   - For Section I (MCQs): "MCQ_1", "MCQ_2", ..., "MCQ_20"
   - For Section II: "SEC_II_1", "SEC_II_2", ...
   - For Section III: "SEC_III_1", "SEC_III_2", ...
   - For sub-questions: "SEC_III_1_i", "SEC_III_1_ii", etc.
   - NEVER reuse the same ID

3. PRESERVE DOCUMENT STRUCTURE
   - Identify section headers (e.g., "I. MCQ's", "II. Solve as directed", "III. Solve the following")
   - Include section information in each question
   - Preserve original numbering exactly as shown

4. PRESERVE MATHEMATICAL NOTATION
   - Use LaTeX for all math: $\\Delta ABC$, $\\angle B = 50^\\circ$, $\\frac{{a}}{{b}}$
   - Subscripts/superscripts: $A_n$, $x^2$, $4AD^2$
   - Greek letters: $\\pi$, $\\theta$, $\\alpha$
   - Symbols: $\\cong$ (congruent), $\\parallel$ (parallel), $\\perp$ (perpendicular)

5. FOR MCQ QUESTIONS
   - List ALL options with labels (a, b, c, d or A, B, C, D)
   - If answer is shown (often in a column), set is_correct=true for that option
   - Preserve the answer exactly as shown

6. FOR MULTI-PART QUESTIONS
   - Create parent with type="multi_part"
   - Include all parts in sub_questions array
   - Parts may be (i), (ii), (iii) or (a), (b), (c)

7. FOR FIGURES/IMAGES
   - Note presence: "[Figure shown]" or "[See Figure X]"
   - Reference by figure number if labeled in document
   - {image_reference_instructions}

=== QUESTION TYPES ===
- "mcq": Multiple choice with options
- "short_answer": Brief response
- "long_answer": Extended response
- "multi_part": Has sub-questions
- "fill_in_blank": Complete sentence/equation
- "true_false": True/False
- "numerical": Calculate a number
- "proof": Mathematical proof required
- "other": Doesn't fit other categories

=== OUTPUT FORMAT ===

Return a JSON object:
{{
  "total_pages": <integer>,
  "sections": [
    {{
      "name": "Section I - MCQs",
      "question_count": 20
    }}
  ],
  "questions": [
    {{
      "id": "MCQ_1",
      "section": "I",
      "number": "1",
      "type": "mcq",
      "content": {{
        "text": "Question text with $LaTeX$ notation",
        "latex": null,
        "images": [{{"filename": "figure_1", "caption": "Description"}}],
        "table": null
      }},
      "options": [
        {{"label": "A", "text": "Option text", "is_correct": false}},
        {{"label": "B", "text": "Option text", "is_correct": true}}
      ],
      "sub_questions": null,
      "answer": "(B)",
      "page_number": 1,
      "marks": null
    }}
  ],
  "metadata_hints": {{
    "title": "Document title",
    "subject": "Subject area",
    "grade": "Grade level",
    "institution": "School/Institution name"
  }}
}}

=== FINAL CHECKLIST ===
Before returning, verify:
- [ ] All pages processed
- [ ] All questions from each section included
- [ ] All question IDs are unique
- [ ] All MCQ options included with correct answer marked
- [ ] All sub-questions captured for multi-part questions
- [ ] Mathematical notation in LaTeX format

Extract ALL questions now."""

# Legacy system prompt for page-by-page image extraction
EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting structured questions from educational documents.

Your task is to analyze an image of a PDF page and extract all questions in a structured JSON format.

IMPORTANT RULES:
1. Identify ALL questions on the page, including numbered questions, sub-questions, and multi-part questions
2. Preserve the original numbering exactly as shown (e.g., "1.", "a.", "(i)", "Question 5")
3. Preserve ALL mathematical notation, including:
   - LaTeX expressions (e.g., \\sum, \\frac{a}{b}, \\sqrt{x})
   - Subscripts and superscripts (use LaTeX notation like A_n, x^2)
   - Greek letters (use LaTeX: \\pi, \\theta, \\alpha)
   - Special symbols (use LaTeX: \\infty, \\leq, \\geq)
4. For MCQ questions:
   - List ALL options with their labels (a, b, c, d or A, B, C, D)
   - If an answer is indicated, set is_correct to true for that option
5. For multi-part questions:
   - Create a parent question with type "multi_part"
   - Include sub_questions array with nested parts
6. For tables:
   - Extract as structured data with headers and rows
7. For images/figures:
   - Note their presence in the question text (e.g., "[Figure shown]")
   - Reference them by position (e.g., "See figure above")

QUESTION TYPES:
- "mcq": Multiple choice with options
- "short_answer": Brief response expected
- "long_answer": Extended explanation/proof
- "multi_part": Has sub-questions (a, b, c or i, ii, iii)
- "fill_in_blank": Complete the sentence/equation
- "true_false": True or false question
- "numerical": Calculate a numerical answer
- "proof": Mathematical proof required
- "other": Doesn't fit other categories

OUTPUT FORMAT:
Return a JSON object with this structure:
{
  "page_number": <integer>,
  "questions": [
    {
      "id": "Q1",
      "number": "1.",
      "type": "mcq|short_answer|long_answer|multi_part|...",
      "content": {
        "text": "Question text with $LaTeX$ if needed",
        "latex": "Pure LaTeX if present",
        "images": [{"filename": "referenced_figure", "caption": "..."}],
        "table": {"headers": [...], "rows": [[...]]}
      },
      "options": [
        {"label": "a", "text": "Option text", "is_correct": false},
        ...
      ],
      "sub_questions": [...],
      "answer": "Answer if shown",
      "marks": 5
    }
  ],
  "metadata_hints": {
    "title": "Document title if visible",
    "subject": "Subject area",
    "grade": "Grade level"
  }
}

Be thorough and extract ALL questions visible on the page."""


class GeminiClient:
    """
    Client for Gemini 3 Flash via OpenRouter API.
    Handles image-based question extraction with structured JSON output.
    Tracks token usage and costs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "google/gemini-3-flash-preview",
        timeout: int = 120,
    ):
        """
        Initialize the Gemini client.

        Args:
            api_key: OpenRouter API key (defaults to config)
            model: Model identifier on OpenRouter
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or config.OPENROUTER_API_KEY
        self.model = model
        self.base_url = config.OPENROUTER_BASE_URL
        self.timeout = timeout

        # Initialize usage tracking
        self.usage_stats = UsageStats()

        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. Set OPENROUTER_API_KEY environment variable."
            )

    def _encode_image(self, image_path: str) -> str:
        """Encode an image file to base64 data URL."""
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Determine MIME type
        suffix = path.suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(suffix, "image/png")

        # Read and encode
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        return f"data:{mime_type};base64,{image_data}"

    def _encode_pdf(self, pdf_path: str) -> str:
        """Encode a PDF file to base64 data URL for native PDF processing."""
        path = Path(pdf_path)

        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Read and encode
        with open(path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")

        return f"data:application/pdf;base64,{pdf_data}"

    async def get_generation_cost(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """
        Query OpenRouter for detailed generation stats including cost.

        Args:
            generation_id: The generation ID from the API response

        Returns:
            Generation stats including native tokens and cost
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/generation?id={generation_id}", headers=headers
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning(f"Failed to get generation stats: {e}")
                return None

    async def extract_questions_from_pdf(
        self,
        pdf_path: str,
        extracted_images: Optional[List[Dict[str, Any]]] = None,
        total_pages: Optional[int] = None,
    ) -> tuple[Dict[str, Any], UsageStats]:
        """
        Extract questions from an entire PDF using native PDF processing.

        This sends the PDF directly to OpenRouter which passes it natively to
        Gemini for processing, giving the model full document context.

        Args:
            pdf_path: Path to the PDF file
            extracted_images: List of extracted image metadata (filenames, pages)
            total_pages: Total number of pages in the PDF

        Returns:
            Tuple of (parsed extraction result, usage stats)
        """
        # Encode PDF
        pdf_data_url = self._encode_pdf(pdf_path)
        pdf_name = Path(pdf_path).name

        # Build image reference instructions for the prompt
        if extracted_images:
            image_list = [img.get("filename", "") for img in extracted_images]
            image_info = f"The following figures have been extracted from this PDF: {image_list}. When referencing figures, use these exact filenames."
        else:
            image_info = "Reference figures by their label in the document (e.g., 'Figure 1', 'Fig. 5')."

        # Build the system prompt with image information
        system_prompt = PDF_EXTRACTION_SYSTEM_PROMPT.format(
            image_reference_instructions=image_info
        )

        # Build user message with PDF
        # OpenRouter accepts PDFs as image_url type with base64 data URL
        page_info = f" ({total_pages} pages)" if total_pages else ""
        user_content = [
            {
                "type": "text",
                "text": f"Extract ALL questions from this PDF document: {pdf_name}{page_info}. Process every page systematically.",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": pdf_data_url,
                },
            },
        ]

        # Build request payload with native PDF processing
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,  # Low temperature for consistent extraction
            "max_tokens": 16384,  # Increased for full document extraction
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pdf-questions-extractor",
            "X-Title": "PDF Questions Extractor",
        }

        # Create usage stats for this extraction
        usage_stats = UsageStats()

        logger.info(f"Sending PDF to OpenRouter for native processing: {pdf_name}")

        # Make API request with extended timeout for full PDF processing
        async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()

                result = response.json()

                # Track usage stats
                generation_id = result.get("id")
                usage = result.get("usage", {})
                if usage:
                    usage_stats.add(usage, generation_id)
                    self.usage_stats.add(usage, generation_id)
                    logger.info(
                        f"PDF extraction tokens: "
                        f"{usage.get('prompt_tokens', 0):,} prompt + "
                        f"{usage.get('completion_tokens', 0):,} completion = "
                        f"{usage.get('total_tokens', 0):,} total"
                    )

                # Extract content from response
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]

                    # Parse JSON from response
                    try:
                        parsed = json.loads(content)
                        parsed["_usage"] = usage
                        parsed["_generation_id"] = generation_id
                        logger.info(
                            f"Extracted {len(parsed.get('questions', []))} questions from PDF"
                        )
                        return parsed, usage_stats
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
                        logger.debug(f"Raw content: {content[:1000]}")
                        return {
                            "questions": [],
                            "error": f"JSON parse error: {str(e)}",
                        }, usage_stats
                else:
                    logger.error(f"Unexpected response structure: {result}")
                    return {
                        "questions": [],
                        "error": "No choices in response",
                    }, usage_stats

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error: {e.response.status_code} - {e.response.text}"
                )
                raise
            except httpx.TimeoutException as e:
                logger.error(f"Request timeout for PDF extraction: {e}")
                raise
            except Exception as e:
                logger.error(f"API request failed: {e}")
                raise

    async def extract_questions_from_image(
        self, image_path: str, page_number: int, additional_context: str = ""
    ) -> Dict[str, Any]:
        """
        Extract questions from a single page image.

        Args:
            image_path: Path to the page image
            page_number: Page number for reference
            additional_context: Additional instructions or context

        Returns:
            Parsed JSON response with extracted questions and usage stats
        """
        # Encode image
        image_data_url = self._encode_image(image_path)

        # Build user message with image
        user_content = [
            {
                "type": "text",
                "text": f"Extract all questions from this PDF page (page {page_number}). {additional_context}".strip(),
            },
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]

        # Build request payload
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,  # Low temperature for consistent extraction
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pdf-questions-extractor",
            "X-Title": "PDF Questions Extractor",
        }

        # Make API request
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()

                result = response.json()

                # Track usage stats
                generation_id = result.get("id")
                usage = result.get("usage", {})
                if usage:
                    self.usage_stats.add(usage, generation_id)
                    logger.info(
                        f"Page {page_number} tokens: "
                        f"{usage.get('prompt_tokens', 0):,} prompt + "
                        f"{usage.get('completion_tokens', 0):,} completion = "
                        f"{usage.get('total_tokens', 0):,} total"
                    )

                # Extract content from response
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]

                    # Parse JSON from response
                    try:
                        parsed = json.loads(content)
                        # Add usage info to result
                        parsed["_usage"] = usage
                        parsed["_generation_id"] = generation_id
                        return parsed
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
                        logger.debug(f"Raw content: {content[:500]}")
                        return {
                            "page_number": page_number,
                            "questions": [],
                            "error": str(e),
                        }
                else:
                    logger.error(f"Unexpected response structure: {result}")
                    return {
                        "page_number": page_number,
                        "questions": [],
                        "error": "No choices in response",
                    }

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error: {e.response.status_code} - {e.response.text}"
                )
                raise
            except Exception as e:
                logger.error(f"API request failed: {e}")
                raise

    async def extract_questions_batch(
        self, image_paths: List[str], start_page: int = 1
    ) -> tuple[List[Dict[str, Any]], UsageStats]:
        """
        Extract questions from multiple page images.

        Args:
            image_paths: List of paths to page images
            start_page: Starting page number

        Returns:
            Tuple of (extraction results for each page, usage stats for this batch)
        """
        results = []

        # Create LOCAL usage stats for this batch (thread-safe for parallel processing)
        batch_usage = UsageStats()

        # Process pages sequentially for now (can add concurrency later)
        for i, image_path in enumerate(image_paths):
            page_num = start_page + i
            logger.info(
                f"Processing page {page_num}/{start_page + len(image_paths) - 1}"
            )

            try:
                result = await self.extract_questions_from_image(image_path, page_num)
                results.append(result)

                # Add usage from this page to batch stats
                if "_usage" in result:
                    batch_usage.add(result["_usage"], result.get("_generation_id"))
            except Exception as e:
                logger.error(f"Failed to process page {page_num}: {e}")
                results.append(
                    {"page_number": page_num, "questions": [], "error": str(e)}
                )

        # Log total usage for this batch
        logger.info(f"Batch complete - {batch_usage}")

        return results, batch_usage

    def get_usage_summary(self) -> Dict[str, Any]:
        """Get a summary of token usage for the current session."""
        return self.usage_stats.to_dict()

    async def get_cost_summary(self) -> Dict[str, Any]:
        """
        Get detailed cost information by querying OpenRouter.

        Returns:
            Dictionary with cost breakdown
        """
        total_cost = 0.0
        costs = []

        for gen_id in self.usage_stats.generation_ids:
            stats = await self.get_generation_cost(gen_id)
            if stats and "data" in stats:
                data = stats["data"]
                cost = data.get("total_cost", 0)
                total_cost += cost
                costs.append(
                    {
                        "generation_id": gen_id,
                        "native_tokens_prompt": data.get("native_tokens_prompt"),
                        "native_tokens_completion": data.get(
                            "native_tokens_completion"
                        ),
                        "cost": cost,
                    }
                )

        return {
            "total_cost_usd": total_cost,
            "generations": costs,
            "usage": self.usage_stats.to_dict(),
        }


# Convenience function for synchronous usage
def create_gemini_client(api_key: Optional[str] = None) -> GeminiClient:
    """Create a Gemini client instance."""
    return GeminiClient(api_key=api_key)
