"""
Question Parser and Post-Processor.
Merges page-level extraction results and handles cross-page questions.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.core.schemas import (
    Question,
    QuestionContent,
    MCQOption,
    ImageRef,
    TableData,
    ExtractedDocument,
    DocumentMetadata,
)

logger = logging.getLogger(__name__)


class QuestionParser:
    """
    Post-processes extracted question data.
    Handles merging, normalization, and cross-page question detection.
    """

    def __init__(self):
        self.question_counter = 0

    def merge_page_results(
        self,
        page_results: List[Dict[str, Any]],
        source_pdf: str,
        total_pages: int,
        processing_time: float,
        extracted_images: List[Dict[str, Any]],
    ) -> ExtractedDocument:
        """
        Merge extraction results from all pages into a single document.

        Args:
            page_results: List of per-page extraction results from Gemini
            source_pdf: Original PDF filename
            total_pages: Total number of pages
            processing_time: Time taken to process
            extracted_images: List of extracted image metadata

        Returns:
            ExtractedDocument with all questions
        """
        self.question_counter = 0
        all_questions = []
        metadata_hints = {}

        # Create image lookup by page
        images_by_page = {}
        for img in extracted_images:
            page = img.get("page_number", 0)
            if page not in images_by_page:
                images_by_page[page] = []
            images_by_page[page].append(img)

        # Process each page's results
        for page_result in page_results:
            if "error" in page_result and page_result.get("error"):
                logger.warning(f"Page had extraction error: {page_result['error']}")
                continue

            page_num = page_result.get("page_number", 0)
            questions_data = page_result.get("questions", [])

            # Collect metadata hints
            hints = page_result.get("metadata_hints", {})
            if hints:
                if hints.get("title") and not metadata_hints.get("title"):
                    metadata_hints["title"] = hints["title"]
                if hints.get("subject") and not metadata_hints.get("subject"):
                    metadata_hints["subject"] = hints["subject"]
                if hints.get("grade") and not metadata_hints.get("grade"):
                    metadata_hints["grade"] = hints["grade"]

            # Parse questions from this page
            for q_data in questions_data:
                try:
                    question = self._parse_question(
                        q_data, page_num, images_by_page.get(page_num, [])
                    )
                    if question:
                        all_questions.append(question)
                except Exception as e:
                    logger.warning(f"Failed to parse question: {e}")
                    continue

        # Detect and merge cross-page questions
        all_questions = self._merge_cross_page_questions(all_questions)

        # Build metadata
        metadata = DocumentMetadata(
            title=metadata_hints.get("title"),
            subject=metadata_hints.get("subject"),
            grade=metadata_hints.get("grade"),
            total_pages=total_pages,
            extraction_timestamp=datetime.utcnow(),
            processing_time_seconds=processing_time,
        )

        return ExtractedDocument(
            source_pdf=source_pdf, metadata=metadata, questions=all_questions
        )

    def _parse_question(
        self,
        q_data: Dict[str, Any],
        page_number: int,
        page_images: List[Dict[str, Any]],
    ) -> Optional[Question]:
        """Parse a single question from extraction data."""

        # Generate ID if not present
        q_id = q_data.get("id")
        if not q_id:
            self.question_counter += 1
            q_id = f"Q{self.question_counter}"

        # Get question number
        number = q_data.get("number", str(self.question_counter))

        # Get question type
        q_type = q_data.get("type", "other")
        if q_type not in [
            "mcq",
            "short_answer",
            "long_answer",
            "multi_part",
            "fill_in_blank",
            "true_false",
            "numerical",
            "proof",
            "matching",
            "other",
        ]:
            q_type = "other"

        # Parse content
        content_data = q_data.get("content", {})
        if isinstance(content_data, str):
            content_data = {"text": content_data}

        # Parse images in content
        content_images = None
        if content_data.get("images"):
            content_images = [
                ImageRef(
                    filename=img.get("filename", "unknown"), caption=img.get("caption")
                )
                for img in content_data.get("images", [])
            ]

        # Parse table in content
        content_table = None
        if content_data.get("table"):
            table_data = content_data["table"]
            content_table = TableData(
                headers=table_data.get("headers"), rows=table_data.get("rows", [])
            )

        content = QuestionContent(
            text=content_data.get("text", ""),
            latex=content_data.get("latex"),
            images=content_images,
            table=content_table,
        )

        # Parse MCQ options
        options = None
        if q_data.get("options"):
            options = [
                MCQOption(
                    label=opt.get("label", ""),
                    text=opt.get("text", ""),
                    is_correct=opt.get("is_correct"),
                )
                for opt in q_data.get("options", [])
            ]

        # Parse sub-questions recursively
        sub_questions = None
        if q_data.get("sub_questions"):
            sub_questions = []
            for sub_q in q_data.get("sub_questions", []):
                parsed_sub = self._parse_question(sub_q, page_number, page_images)
                if parsed_sub:
                    sub_questions.append(parsed_sub)

        return Question(
            id=q_id,
            number=number,
            type=q_type,
            content=content,
            options=options,
            sub_questions=sub_questions if sub_questions else None,
            answer=q_data.get("answer"),
            page_number=page_number,
            marks=q_data.get("marks"),
        )

    def _merge_cross_page_questions(self, questions: List[Question]) -> List[Question]:
        """
        Detect and merge questions that span multiple pages.

        A question might be continued on the next page if:
        - It ends with "..." or incomplete sentence
        - The next page starts with a lowercase letter or sub-question
        """
        if len(questions) <= 1:
            return questions

        merged = []
        i = 0

        while i < len(questions):
            current = questions[i]

            # Check if this question might continue on next page
            if i + 1 < len(questions):
                next_q = questions[i + 1]

                # Check for continuation indicators
                current_text = current.content.text.strip()
                next_text = next_q.content.text.strip()

                # If current ends with continuation and next looks like continuation
                if (
                    current_text.endswith("...")
                    or current_text.endswith("-")
                    or (
                        current.page_number
                        and next_q.page_number
                        and next_q.page_number == current.page_number + 1
                        and self._looks_like_continuation(next_text)
                    )
                ):

                    # Merge content
                    merged_text = (
                        current_text.rstrip("...").rstrip("-") + " " + next_text
                    )
                    current = Question(
                        id=current.id,
                        number=current.number,
                        type=current.type,
                        content=QuestionContent(
                            text=merged_text,
                            latex=current.content.latex or next_q.content.latex,
                            images=(current.content.images or [])
                            + (next_q.content.images or [])
                            or None,
                            table=current.content.table or next_q.content.table,
                        ),
                        options=current.options or next_q.options,
                        sub_questions=self._merge_subquestions(
                            current.sub_questions, next_q.sub_questions
                        ),
                        answer=current.answer or next_q.answer,
                        page_number=current.page_number,
                        marks=current.marks or next_q.marks,
                    )
                    i += 1  # Skip the next question as it was merged

            merged.append(current)
            i += 1

        return merged

    def _looks_like_continuation(self, text: str) -> bool:
        """Check if text looks like a continuation (starts lowercase, etc.)."""
        if not text:
            return False

        # Starts with lowercase letter
        if text[0].islower():
            return True

        # Starts with continuation words
        continuation_starters = ["and", "or", "but", "where", "such", "then"]
        first_word = text.split()[0].lower() if text.split() else ""
        if first_word in continuation_starters:
            return True

        return False

    def _merge_subquestions(
        self, sub1: Optional[List[Question]], sub2: Optional[List[Question]]
    ) -> Optional[List[Question]]:
        """Merge two lists of sub-questions."""
        if not sub1 and not sub2:
            return None
        if not sub1:
            return sub2
        if not sub2:
            return sub1
        return sub1 + sub2


def parse_and_merge_results(
    page_results: List[Dict[str, Any]],
    source_pdf: str,
    total_pages: int,
    processing_time: float,
    extracted_images: List[Dict[str, Any]],
) -> ExtractedDocument:
    """
    Convenience function to parse and merge page results.

    Args:
        page_results: Per-page extraction results
        source_pdf: Original PDF filename
        total_pages: Total pages in PDF
        processing_time: Processing time in seconds
        extracted_images: Extracted image metadata

    Returns:
        ExtractedDocument with merged questions
    """
    parser = QuestionParser()
    return parser.merge_page_results(
        page_results, source_pdf, total_pages, processing_time, extracted_images
    )
