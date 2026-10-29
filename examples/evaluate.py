"""Run from the repository root after setting OPENAI_API_KEY and OPENAI_MODEL."""

import json
import os
from pathlib import Path

from langchain_openai import ChatOpenAI

from text2sql_eval import EvaluationCase, Evaluator, summarize

dataset = Path(__file__).with_name("cases.jsonl")
cases = [
    EvaluationCase.model_validate_json(line)
    for line in dataset.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
llm = ChatOpenAI(model=os.environ["OPENAI_MODEL"], timeout=60, max_retries=2)
results = Evaluator(llm).evaluate_many(cases)
for result in results:
    print(result.model_dump_json(indent=2))
print(
    json.dumps({name: score.model_dump() for name, score in summarize(results).items()}, indent=2)
)
