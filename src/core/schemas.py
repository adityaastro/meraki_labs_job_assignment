"""
JSON Schema and Pydantic models for extracted questions.
Defines the structure for questions, options, images, and tables.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# Sub-models
# ============================================================================


class BoundingBox(BaseModel):
    """Bounding box for image location in source PDF."""

    x: float
    y: float
    width: float
    height: float


class ImageRef(BaseModel):
    """Reference to an extracted image file."""

    filename: str = Field(
        ..., description="Filename of the extracted image in assets directory"
    )
    caption: Optional[str] = Field(None, description="Image caption if present")
    bbox: Optional[BoundingBox] = Field(None, description="Bounding box in source PDF")


class TableData(BaseModel):
    """Structured table data."""

    headers: Optional[List[str]] = Field(None, description="Table header row")
    rows: List[List[str]] = Field(default_factory=list, description="Table data rows")


class MCQOption(BaseModel):
    """Multiple choice question option."""

    label: str = Field(..., description="Option label (a, b, c, d or A, B, C, D)")
    text: str = Field(..., description="Option text content")
    is_correct: Optional[bool] = Field(
        None, description="Whether this is the correct answer"
    )


class QuestionContent(BaseModel):
    """Content of a question including text, LaTeX, images, and tables."""

    text: str = Field(..., description="Question text (may include LaTeX markers)")
    latex: Optional[str] = Field(None, description="Extracted LaTeX expressions")
    images: Optional[List[ImageRef]] = Field(None, description="Referenced images")
    table: Optional[TableData] = Field(None, description="Embedded table data")


# ============================================================================
# Main Question Model
# ============================================================================

QuestionType = Literal[
    "mcq",  # Multiple choice question
    "short_answer",  # Short answer/fill in
    "long_answer",  # Extended response
    "multi_part",  # Question with sub-parts
    "fill_in_blank",  # Fill in the blank
    "true_false",  # True/False question
    "matching",  # Matching question
    "numerical",  # Numerical answer
    "proof",  # Mathematical proof
    "other",  # Other/unclassified
]


class Question(BaseModel):
    """
    Represents an extracted question from a PDF.
    Supports nested sub-questions for multi-part questions.
    """

    id: str = Field(..., description="Unique question ID (e.g., MCQ_1, SEC_II_1, SEC_III_1_i)")
    number: str = Field(
        ...,
        description="Original numbering as shown in PDF (e.g., '1.', '(a)', 'Question 5')",
    )
    type: QuestionType = Field(..., description="Question type classification")
    content: QuestionContent = Field(..., description="Question content")
    options: Optional[List[MCQOption]] = Field(
        None, description="MCQ options if applicable"
    )
    sub_questions: Optional[List["Question"]] = Field(
        None, description="Nested sub-questions"
    )
    answer: Optional[str] = Field(None, description="Answer if provided in source")
    page_number: Optional[int] = Field(
        None, description="Source page number (1-indexed)"
    )
    marks: Optional[float] = Field(None, description="Marks/points if specified")


# Enable forward reference for recursive model
Question.model_rebuild()


# ============================================================================
# Document-level Models
# ============================================================================


class DocumentMetadata(BaseModel):
    """Metadata extracted from the PDF document."""

    title: Optional[str] = Field(None, description="Document title")
    subject: Optional[str] = Field(
        None, description="Subject area (e.g., Mathematics, Physics)"
    )
    grade: Optional[str] = Field(None, description="Grade/class level")
    total_pages: int = Field(..., description="Total number of pages in PDF")
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)
    processing_time_seconds: Optional[float] = Field(
        None, description="Time taken to process"
    )


class UsageData(BaseModel):
    """Token usage statistics from the API."""

    prompt_tokens: int = Field(..., description="Number of input/prompt tokens")
    completion_tokens: int = Field(
        ..., description="Number of output/completion tokens"
    )
    total_tokens: int = Field(..., description="Total tokens (prompt + completion)")
    generation_ids: Optional[List[str]] = Field(
        None, description="OpenRouter generation IDs for cost lookup"
    )


class ExtractedDocument(BaseModel):
    """
    Complete extracted document with all questions.
    This is the root model for the output JSON.
    """

    source_pdf: str = Field(..., description="Original PDF filename")
    metadata: DocumentMetadata = Field(..., description="Document metadata")
    questions: List[Question] = Field(
        default_factory=list, description="Extracted questions"
    )
    usage: Optional[UsageData] = Field(
        None, description="Token usage statistics from extraction"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "source_pdf": "test3.pdf",
                "metadata": {
                    "title": "Triangles",
                    "subject": "Mathematics",
                    "grade": "IX CBSE",
                    "total_pages": 7,
                    "extraction_timestamp": "2024-12-24T12:00:00Z",
                    "processing_time_seconds": 50.0,
                },
                "questions": [
                    {
                        "id": "MCQ_1",
                        "number": "1",
                        "type": "mcq",
                        "content": {
                            "text": "Which of the following is not a criterion for congruence of triangles?",
                            "images": [{"filename": "test3_001.png", "caption": "Triangle diagram"}]
                        },
                        "options": [
                            {"label": "A", "text": "SAS", "is_correct": False},
                            {"label": "B", "text": "ASA", "is_correct": False},
                            {"label": "C", "text": "SSA", "is_correct": True},
                            {"label": "D", "text": "SSS", "is_correct": False},
                        ],
                        "answer": "(C)",
                        "page_number": 1,
                    },
                    {
                        "id": "SEC_III_13",
                        "number": "13",
                        "type": "multi_part",
                        "content": {"text": "In Figure 11, ABCD is a square and △DEC is an equilateral triangle. Prove that:"},
                        "sub_questions": [
                            {
                                "id": "SEC_III_13_i",
                                "number": "(i)",
                                "type": "proof",
                                "content": {"text": "△ADE ≅ △BCE"},
                            },
                            {
                                "id": "SEC_III_13_ii",
                                "number": "(ii)",
                                "type": "proof",
                                "content": {"text": "AE = BE"},
                            },
                        ],
                    }
                ],
                "usage": {
                    "prompt_tokens": 5000,
                    "completion_tokens": 9498,
                    "total_tokens": 14498,
                    "generation_ids": ["gen-abc123"],
                },
            }
        }


# ============================================================================
# API Models
# ============================================================================


class ExtractRequest(BaseModel):
    """Request body for /extract endpoint."""

    pdf_path: str = Field(..., description="Path to the PDF file to process")


class ExtractResponse(BaseModel):
    """Response body for /extract endpoint."""

    status: Literal["ok", "error"] = Field(..., description="Processing status")
    output_json_path: Optional[str] = Field(
        None, description="Path to output JSON file"
    )
    assets_dir: Optional[str] = Field(
        None, description="Path to extracted assets directory"
    )
    error: Optional[str] = Field(None, description="Error message if status is 'error'")
    processing_time_seconds: Optional[float] = Field(
        None, description="Processing time"
    )


# ============================================================================
# JSON Schema Export
# ============================================================================


def get_json_schema() -> dict:
    """Get the JSON Schema for ExtractedDocument."""
    return ExtractedDocument.model_json_schema()


def save_json_schema(path: str) -> None:
    """Save JSON Schema to a file."""
    import json

    schema = get_json_schema()
    with open(path, "w") as f:
        json.dump(schema, f, indent=2)


if __name__ == "__main__":
    # Generate and print schema when run directly
    import json

    print(json.dumps(get_json_schema(), indent=2))
