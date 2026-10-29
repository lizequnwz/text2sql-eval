"""Saved JSON and original JSONL can be rendered without model credentials or calls."""

from __future__ import annotations

import json
import os

import pytest
from conftest import RecordingModel
from test_html_report import ReportParser

from text2sql_eval import Evaluator, cli, report_cli, summarize


def saved_inputs(tmp_path, make_case, *, responder=None):
    case = make_case()
    results = Evaluator(RecordingModel(responder)).evaluate_many([case])
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    report_path = tmp_path / "scores.json"
    report = {
        "package_version": "0.1.0",
        "results": [result.model_dump(mode="json") for result in results],
        "summary": {
            name: item.model_dump(mode="json") for name, item in summarize(results).items()
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return case, cases_path, report_path, report


def forbid_provider(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Rendering must not construct a model or invoke an evaluator")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(cli, "ChatOpenAI", unexpected)
    monkeypatch.setattr(cli, "Evaluator", unexpected)
    monkeypatch.setattr("langchain_openai.ChatOpenAI", unexpected)
    monkeypatch.setattr("text2sql_eval.evaluator.Evaluator", unexpected)


def invoke(cases, scores, output):
    try:
        return report_cli.main(
            ["--cases", str(cases), "--results", str(scores), "--output", str(output)]
        )
    except SystemExit as exc:
        return exc.code


def test_saved_report_exports_without_credentials_or_provider(tmp_path, make_case, monkeypatch):
    case, cases, scores, original = saved_inputs(tmp_path, make_case)
    forbid_provider(monkeypatch)
    output = tmp_path / "saved.html"
    assert invoke(cases, scores, output) == 0
    payload = ReportParser(output.read_text(encoding="utf-8")).payload
    assert payload["package_version"] == "0.1.0"
    assert payload["cases"][0]["question"] == case.question
    assert payload["summary"] == original["summary"]
    assert json.loads(scores.read_text(encoding="utf-8")) == original


def test_exporter_success_is_independent_of_evaluation_errors(tmp_path, make_case, monkeypatch):
    _, cases, scores, _ = saved_inputs(
        tmp_path, make_case, responder=lambda _: RuntimeError("Provider unavailable")
    )
    forbid_provider(monkeypatch)
    output = tmp_path / "errors.html"
    assert invoke(cases, scores, output) == 0
    payload = ReportParser(output.read_text(encoding="utf-8")).payload
    assert payload["summary"]["sql_semantic"]["errors"] == 1


def test_export_help_has_no_model_requirement(monkeypatch, capsys):
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        report_cli.main(["--help"])
    assert raised.value.code == 0
    assert "--cases" in capsys.readouterr().out


@pytest.mark.parametrize("problem", ["summary", "root_shape", "duplicate_scores", "bad_json"])
def test_invalid_saved_reports_fail_without_creating_html(
    tmp_path, make_case, monkeypatch, problem
):
    _, cases, scores, record = saved_inputs(tmp_path, make_case)
    if problem == "summary":
        record["summary"]["sql_semantic"]["passed"] = 0
    elif problem == "root_shape":
        record = [record]
    elif problem == "duplicate_scores":
        record["results"].append(record["results"][0])
    scores.write_text(
        "{bad json" if problem == "bad_json" else json.dumps(record), encoding="utf-8"
    )
    forbid_provider(monkeypatch)
    output = tmp_path / "invalid.html"
    assert invoke(cases, scores, output) == 2
    assert not output.exists()


def test_saved_scores_cannot_silently_join_to_different_case_ids(tmp_path, make_case, monkeypatch):
    _, cases, scores, _ = saved_inputs(tmp_path, make_case)
    cases.write_text(make_case(case_id="different").model_dump_json() + "\n", encoding="utf-8")
    forbid_provider(monkeypatch)
    output = tmp_path / "mismatch.html"
    assert invoke(cases, scores, output) == 2
    assert not output.exists()


@pytest.mark.parametrize("destination", ["cases", "scores", "symlink", "hardlink"])
def test_export_cannot_replace_either_input_through_an_alias(
    tmp_path, make_case, monkeypatch, destination
):
    _, cases, scores, _ = saved_inputs(tmp_path, make_case)
    original_cases = cases.read_bytes()
    original_scores = scores.read_bytes()
    if destination == "cases":
        output = cases
    elif destination == "scores":
        output = scores
    else:
        output = tmp_path / "alias.html"
        if destination == "symlink":
            output.symlink_to(cases)
        else:
            os.link(scores, output)
    forbid_provider(monkeypatch)
    assert invoke(cases, scores, output) == 2
    assert cases.read_bytes() == original_cases
    assert scores.read_bytes() == original_scores


def test_html_write_failure_returns_two_without_changing_saved_inputs(
    tmp_path, make_case, monkeypatch
):
    _, cases, scores, _ = saved_inputs(tmp_path, make_case)
    original = scores.read_bytes()
    parent = tmp_path / "occupied"
    parent.write_text("not a directory", encoding="utf-8")
    forbid_provider(monkeypatch)
    assert invoke(cases, scores, parent / "scores.html") == 2
    assert scores.read_bytes() == original
