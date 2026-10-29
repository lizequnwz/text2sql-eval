"""Exercise real LangChain/SDK schema parsing through an offline HTTP transport."""

import json

import httpx
from langchain_openai import ChatOpenAI

from text2sql_eval import Evaluator


def test_real_chat_openai_uses_strict_schema_and_extracts_usage(make_case):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": "offline-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "offline-judge",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "verdict": "PASS",
                                    "reason": "The supplied evidence supports this metric.",
                                    "needs_review": False,
                                    "evidence": ["Matching required grouping and SUM(amount)."],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm = ChatOpenAI(
            model="offline-judge",
            api_key="offline-not-a-real-api-key",
            http_client=client,
            use_responses_api=False,
            max_retries=0,
        )
        scores = Evaluator(llm).evaluate(make_case())

    assert len(requests) == 2
    for request in requests:
        assert request["response_format"]["type"] == "json_schema"
        schema = request["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert set(schema["schema"]["required"]) == {
            "verdict",
            "reason",
            "needs_review",
            "evidence",
        }
    assert "target_result" in json.loads(requests[0]["messages"][-1]["content"])
    assert "target_result" not in json.loads(requests[1]["messages"][-1]["content"])
    for metric in (scores.sampled_result_consistency, scores.sql_semantic):
        assert metric.status == "PASS"
        assert metric.metadata.token_usage == {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }
