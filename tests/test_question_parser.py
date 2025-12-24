import pytest
from src.processors.question_parser import QuestionParser
from src.core.schemas import Question

def test_id_deduplication():
    parser = QuestionParser()
    # Mock question data with same ID
    q_data = {
        "id": "MCQ_1",
        "number": "1",
        "type": "mcq",
        "content": {"text": "Question 1"}
    }
    
    q1 = parser._parse_question(q_data, page_number=1)
    q2 = parser._parse_question(q_data, page_number=1)
    
    assert q1.id == "MCQ_1"
    assert q2.id == "MCQ_1_1"

def test_image_filename_resolution():
    parser = QuestionParser()
    image_mapping = {"figure_1": "test_001.png", "fig_2": "test_002.png"}
    
    # Exact match
    assert parser._resolve_image_filename("figure_1", image_mapping) == "test_001.png"
    # Case insensitive
    assert parser._resolve_image_filename("Figure_1", image_mapping) == "test_001.png"
    # Mapping via number
    assert parser._resolve_image_filename("Fig 2", image_mapping) == "test_002.png"
    # Fallback
    assert parser._resolve_image_filename("unknown", image_mapping) == "unknown"

def test_cross_page_merging():
    parser = QuestionParser()
    q1 = Question(
        id="Q1", number="1", type="other",
        content={"text": "Question starts here..."},
        page_number=1
    )
    q2 = Question(
        id="Q2", number="2", type="other",
        content={"text": "continues here."},
        page_number=2
    )
    
    merged = parser._merge_cross_page_questions([q1, q2])
    assert len(merged) == 1
    assert merged[0].content.text == "Question starts here continues here."
    assert merged[0].page_number == 1

