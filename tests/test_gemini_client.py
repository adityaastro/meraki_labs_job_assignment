import pytest
import respx
import httpx
import json
from src.processors.gemini_client import GeminiClient, UsageStats

@pytest.mark.asyncio
@respx.mock
async def test_gemini_client_pdf_extraction(mock_api_key):
    client = GeminiClient(api_key=mock_api_key)
    
    # Mock response
    mock_response = {
        "id": "gen-123",
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "questions": [
                            {"id": "Q1", "number": "1", "type": "mcq", "content": {"text": "Test?"}}
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    }
    
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=mock_response)
    )
    
    # We need a dummy PDF or mock the _encode_pdf
    # For unit test, we can mock _encode_pdf
    client._encode_pdf = lambda x: "data:application/pdf;base64,dummy"
    
    result, usage = await client.extract_questions_from_pdf("dummy.pdf")
    
    assert len(result["questions"]) == 1
    assert usage.total_tokens == 150
    assert usage.prompt_tokens == 100

def test_usage_stats_aggregation():
    stats = UsageStats()
    stats.add({"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}, "id1")
    stats.add({"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}, "id2")
    
    assert stats.prompt_tokens == 15
    assert stats.completion_tokens == 25
    assert stats.total_tokens == 40
    assert len(stats.generation_ids) == 2

