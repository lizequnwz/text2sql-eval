"""Validate datasets before provider setup and exercise complete offline CLI runs."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import RecordingModel, decision
from test_html_report import ReportParser

from text2sql_eval import cli


def write_cases(path: Path, *cases) -> Path:
    path.write_text("\n".join(case.model_dump_json() for case in cases) + "\n", encoding="utf-8")
    return path


def forbid_provider(monkeypatch):
    def unexpected_provider(**kwargs):
        pytest.fail("Invalid input and --help must not construct a provider client")

    monkeypatch.setattr(cli, "ChatOpenAI", unexpected_provider)


def test_load_cases_keeps_input_order_and_ignores_blank_lines(tmp_path, make_case):
    path = tmp_path / "cases.jsonl"
    first, second = make_case(case_id="first"), make_case(case_id="second")
    path.write_text(
        f"\n{first.model_dump_json()}\n  \n{second.model_dump_json()}\n", encoding="utf-8"
    )
    assert [case.case_id for case in cli.load_cases(path)] == ["first", "second"]


def test_load_cases_identifies_the_duplicate_line(tmp_path, make_case):
    path = tmp_path / "duplicate.jsonl"
    case = make_case()
    path.write_text(f"{case.model_dump_json()}\n\n{case.model_dump_json()}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Duplicate case_id.*:3:"):
        cli.load_cases(path)


def test_load_cases_reports_the_malformed_json_line(tmp_path, make_case):
    path = tmp_path / "broken.jsonl"
    path.write_text(f"{make_case().model_dump_json()}\n{{not json}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Invalid case.*:2:"):
        cli.load_cases(path)


def test_load_cases_rejects_invalid_gold_instead_of_dropping_it(tmp_path, make_case):
    path = tmp_path / "invalid-gold.jsonl"
    record = make_case(case_id="invalid-gold").model_dump(mode="json")
    record["target_result"] = {
        "columns": [],
        "rows": [],
        "total_rows": None,
        "execution_error": "Reference query failed",
    }
    path.write_text(
        f"{make_case(case_id='valid').model_dump_json()}\n{json.dumps(record)}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"Invalid case.*:2:"):
        cli.load_cases(path)


def test_load_cases_rejects_an_empty_dataset(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no evaluation cases"):
        cli.load_cases(path)


def test_help_does_not_need_credentials_or_a_provider(monkeypatch, capsys):
    forbid_provider(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0
    assert "--input" in capsys.readouterr().out


def test_client_setup_errors_are_configuration_errors_not_tracebacks(
    tmp_path, make_case, monkeypatch, capsys
):
    source = write_cases(tmp_path / "cases.jsonl", make_case())

    def failed_setup(**kwargs):
        raise RuntimeError("Potentially sensitive provider setup message")

    monkeypatch.setattr(cli, "ChatOpenAI", failed_setup)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            ["--input", str(source), "--output", str(tmp_path / "out.json"), "--model", "fake"]
        )
    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert "Could not configure the judge (RuntimeError)" in error
    assert "Potentially sensitive" not in error


def test_all_input_is_validated_before_provider_construction(tmp_path, make_case, monkeypatch):
    path = write_cases(tmp_path / "cases.jsonl", make_case(), make_case())
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            ["--input", str(path), "--output", str(tmp_path / "report.json"), "--model", "fake"]
        )
    assert raised.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_cli_writes_a_complete_structured_report_without_network(
    tmp_path, make_case, monkeypatch, capsys
):
    source = write_cases(
        tmp_path / "cases.jsonl", make_case(case_id="first"), make_case(case_id="second")
    )
    output = tmp_path / "reports" / "scores.json"
    model = RecordingModel()
    construction_options = []

    def fake_chat_openai(**kwargs):
        construction_options.append(kwargs)
        return model

    monkeypatch.setattr(cli, "ChatOpenAI", fake_chat_openai)
    code = cli.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--model",
            "offline-model",
            "--base-url",
            "https://example.invalid/v1",
            "--concurrency",
            "2",
        ]
    )
    assert code == 0
    assert len(model.calls) == 4
    assert construction_options[0]["model"] == "offline-model"
    assert construction_options[0]["base_url"] == "https://example.invalid/v1"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["package_version"]
    assert [item["case_id"] for item in report["results"]] == ["first", "second"]
    for name, summary in report["summary"].items():
        assert summary["cases"] == 2
        assert summary["passed"] == 2
        assert summary["pass_rate"] == 1
        assert report["results"][0][name]["score"] == 1
    assert json.loads(capsys.readouterr().out) == report["summary"]
    assert not list(output.parent.glob(".scores.json.*"))
    html_output = output.with_suffix(".html")
    html_payload = ReportParser(html_output.read_text(encoding="utf-8")).payload
    assert html_payload["summary"] == report["summary"]
    assert [item["case_id"] for item in html_payload["cases"]] == ["first", "second"]


def test_sql_failures_are_results_not_cli_operational_errors(tmp_path, make_case, monkeypatch):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        cli, "ChatOpenAI", lambda **kwargs: RecordingModel(lambda _: decision("FAIL"))
    )
    assert cli.main(["--input", str(source), "--output", str(output), "--model", "fake"]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["sql_semantic"]["failed"] == 1
    assert report["summary"]["sql_semantic"]["errors"] == 0


def test_provider_errors_keep_the_case_and_return_operational_exit_code(
    tmp_path, make_case, monkeypatch
):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    output = tmp_path / "report.json"
    model = RecordingModel(lambda _: RuntimeError("Provider unavailable"))
    monkeypatch.setattr(cli, "ChatOpenAI", lambda **kwargs: model)
    assert cli.main(["--input", str(source), "--output", str(output), "--model", "fake"]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["results"]) == 1
    assert report["summary"]["sql_semantic"]["cases"] == 1
    assert report["summary"]["sql_semantic"]["errors"] == 1
    assert report["summary"]["sql_semantic"]["pass_rate"] == 0


def test_report_write_errors_have_a_distinct_exit_code(tmp_path, make_case, monkeypatch, capsys):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    occupied_parent = tmp_path / "not-a-directory"
    occupied_parent.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(cli, "ChatOpenAI", lambda **kwargs: RecordingModel())
    code = cli.main(
        [
            "--input",
            str(source),
            "--output",
            str(occupied_parent / "report.json"),
            "--model",
            "fake",
        ]
    )
    assert code == 2
    assert "Could not write the report" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--concurrency", "0"],
        ["--max-retries", "-1"],
        ["--timeout", "nan"],
        ["--timeout", "inf"],
        ["--temperature", "nan"],
    ],
)
def test_invalid_runtime_arguments_fail_before_any_provider_call(tmp_path, monkeypatch, extra_args):
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--input",
                str(tmp_path / "input.jsonl"),
                "--output",
                str(tmp_path / "report.json"),
                "--model",
                "fake",
                *extra_args,
            ]
        )
    assert raised.value.code == 2


def test_cli_refuses_to_replace_its_input_dataset(tmp_path, make_case, monkeypatch):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    before = source.read_text(encoding="utf-8")
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--input", str(source), "--output", str(source), "--model", "fake"])
    assert raised.value.code == 2
    assert source.read_text(encoding="utf-8") == before


def test_custom_html_destination_replaces_the_default_without_extra_judge_calls(
    tmp_path, make_case, monkeypatch
):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    output = tmp_path / "scores.json"
    html_output = tmp_path / "custom" / "review.html"
    model = RecordingModel()
    monkeypatch.setattr(cli, "ChatOpenAI", lambda **kwargs: model)
    assert (
        cli.main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--html-output",
                str(html_output),
                "--model",
                "fake",
            ]
        )
        == 0
    )
    assert len(model.calls) == 2
    assert html_output.exists()
    assert not output.with_suffix(".html").exists()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert set(report) == {"package_version", "results", "summary"}
    assert set(report["summary"]) == {
        "row_count_match",
        "sampled_result_consistency",
        "sql_semantic",
    }


@pytest.mark.parametrize("collision", ["source", "json", "symlink_source", "hardlink_json"])
def test_html_path_collisions_are_rejected_before_model_setup(
    tmp_path, make_case, monkeypatch, collision
):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    original_source = source.read_bytes()
    output = tmp_path / "scores.json"
    output.write_text("original scores", encoding="utf-8")
    if collision == "source":
        html_output = source
    elif collision == "json":
        html_output = output
    elif collision == "symlink_source":
        html_output = tmp_path / "alias.html"
        html_output.symlink_to(source)
    else:
        html_output = tmp_path / "alias.html"
        os.link(output, html_output)
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--html-output",
                str(html_output),
                "--model",
                "fake",
            ]
        )
    assert raised.value.code == 2
    assert source.read_bytes() == original_source
    assert output.read_text(encoding="utf-8") == "original scores"


def test_default_html_path_cannot_overwrite_the_input(tmp_path, make_case, monkeypatch):
    source = write_cases(tmp_path / "scores.html", make_case())
    before = source.read_bytes()
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--input",
                str(source),
                "--output",
                str(tmp_path / "scores.json"),
                "--model",
                "fake",
            ]
        )
    assert raised.value.code == 2
    assert source.read_bytes() == before


def test_json_output_cannot_replace_input_through_a_hard_link(tmp_path, make_case, monkeypatch):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    before = source.read_bytes()
    output = tmp_path / "alias.json"
    os.link(source, output)
    forbid_provider(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--input", str(source), "--output", str(output), "--model", "fake"])
    assert raised.value.code == 2
    assert source.read_bytes() == before


def test_html_write_failure_keeps_the_completed_json_report(
    tmp_path, make_case, monkeypatch, capsys
):
    source = write_cases(tmp_path / "cases.jsonl", make_case())
    output = tmp_path / "scores.json"
    occupied_parent = tmp_path / "occupied"
    occupied_parent.write_text("not a directory", encoding="utf-8")
    model = RecordingModel()
    monkeypatch.setattr(cli, "ChatOpenAI", lambda **kwargs: model)
    code = cli.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--html-output",
            str(occupied_parent / "scores.html"),
            "--model",
            "fake",
        ]
    )
    assert code == 2
    assert len(model.calls) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["sql_semantic"]["passed"] == 1
    assert "html" in capsys.readouterr().err.lower()
