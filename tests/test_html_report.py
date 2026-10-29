"""Offline HTML exports preserve evidence without claiming row alignment."""

from __future__ import annotations

import json
from datetime import datetime
from html.parser import HTMLParser

import pytest
from conftest import RecordingModel, decision

from text2sql_eval import Evaluator, QueryResult, render_html_report, write_html_report


class ReportParser(HTMLParser):
    """Inspect exported markup without executing JavaScript or loading a browser."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.report_scripts: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self._capturing_report = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "script" and attributes.get("id") == "report-data":
            self._capturing_report = True
            self.report_scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._capturing_report = False

    def handle_data(self, data):
        if self._capturing_report:
            self.report_scripts[-1] += data

    @property
    def payload(self):
        assert len(self.report_scripts) == 1
        return json.loads(self.report_scripts[0])


def score_cases(*cases, responder=None):
    return Evaluator(RecordingModel(responder)).evaluate_many(cases)


def test_report_joins_by_id_and_preserves_score_order(make_case):
    first = make_case(case_id="first", question="First question")
    second = make_case(case_id="second", question="Second question")
    results = score_cases(second, first)
    html = render_html_report([first, second], results, package_version="9.8.7", title="My report")
    payload = ReportParser(html).payload
    assert payload["title"] == "My report"
    assert payload["package_version"] == "9.8.7"
    assert datetime.fromisoformat(payload["rendered_at"]).tzinfo is not None
    assert [case["case_id"] for case in payload["cases"]] == ["second", "first"]
    assert [case["question"] for case in payload["cases"]] == ["Second question", "First question"]
    for metric in payload["summary"].values():
        assert metric["cases"] == 2
        assert metric["passed"] == 2
        assert metric["pass_rate"] == 1


def test_report_carries_each_judgment_and_execution_context(make_case):
    case = make_case(dialect="snowflake", context="Customer identifiers are unique.")
    results = score_cases(
        case,
        responder=lambda _: decision(
            "FAIL", needs_review=True, reason="The boundary tie needs confirmation."
        ),
    )
    payload = ReportParser(render_html_report([case], results)).payload
    record = payload["cases"][0]
    assert record["target_sql"] == case.target_sql
    assert record["generated_sql"] == case.generated_sql
    assert record["dialect"] == "snowflake"
    assert record["context"] == "Customer identifiers are unique."
    for name in ("sampled_result_consistency", "sql_semantic"):
        score = record["scores"][name]
        assert score["status"] == "REVIEW"
        assert score["score"] is None
        assert score["reason"] == "The boundary tie needs confirmation."
        assert score["judgment"]["verdict"] == "FAIL"
        assert score["judgment"]["needs_review"] is True
        assert score["judgment"]["evidence"]
    assert payload["summary"]["sql_semantic"]["review"] == 1
    assert payload["summary"]["sql_semantic"]["failed"] == 0


@pytest.mark.parametrize("problem", ["duplicate_cases", "duplicate_scores", "missing", "extra"])
def test_report_rejects_incomplete_or_ambiguous_id_joins(make_case, problem):
    case = make_case(case_id="first")
    other = make_case(case_id="second")
    cases = [case]
    results = score_cases(case)
    if problem == "duplicate_cases":
        cases.append(case)
    elif problem == "duplicate_scores":
        results.append(results[0])
    elif problem == "missing":
        cases.append(other)
    else:
        results.extend(score_cases(other))
    with pytest.raises(ValueError):
        render_html_report(cases, results)


@pytest.mark.parametrize("problem", ["input", "score", "metric_name"])
def test_report_revalidates_mutable_inputs_and_scores(make_case, problem):
    case = make_case()
    results = score_cases(case)
    if problem == "input":
        case.generated_result.rows.append([1])
    elif problem == "score":
        results[0].sql_semantic.score = 0
    else:
        results[0].row_count_match.name = "sql_semantic"
    with pytest.raises(ValueError):
        render_html_report([case], results)


def test_report_embeds_only_the_first_fifty_rows(make_case):
    hidden = "ROW_51_MUST_NOT_BE_EMBEDDED_c2ab7e"
    rows = [[number, "visible"] for number in range(50)] + [[50, hidden]]
    case = make_case(
        target_result=QueryResult(columns=["id", "note"], rows=rows, total_rows=5000),
        generated_result=QueryResult(columns=["id", "note"], rows=rows, total_rows=5000),
    )
    html = render_html_report([case], score_cases(case))
    assert hidden not in html
    record = ReportParser(html).payload["cases"][0]
    for key in ("target_result", "generated_result"):
        result = record[key]
        assert result["rows"] == rows[:50]
        assert result["total_rows"] == 5000
        assert result["provided_rows"] == 51
        assert result["shown_rows"] == 50
        assert result["truncated"] is True


def test_preview_tables_preserve_original_order_and_duplicate_column_labels(make_case):
    case = make_case(
        target_result=QueryResult(
            columns=["id", "value", "value"],
            rows=[[1, {"nested": [1, None, True]}, 100], [2, "second", 200]],
            total_rows=2,
        ),
        generated_result=QueryResult(
            columns=["id", "value", "value"],
            rows=[[2, "second", 200], [1, {"nested": [1, None, True]}, 100]],
            total_rows=2,
        ),
    )
    record = ReportParser(render_html_report([case], score_cases(case))).payload["cases"][0]
    assert record["target_result"]["columns"] == ["id", "value", "value"]
    assert record["target_result"]["rows"] == case.target_result.rows
    assert record["generated_result"]["rows"] == case.generated_result.rows
    assert record["target_result"]["truncated"] is False


def test_large_sql_integers_keep_exact_display_text(make_case):
    large_id = 9223372036854775807
    case = make_case(
        target_result=QueryResult(columns=["id"], rows=[[large_id]], total_rows=1),
        generated_result=QueryResult(columns=["id"], rows=[[large_id]], total_rows=1),
    )
    record = ReportParser(render_html_report([case], score_cases(case))).payload["cases"][0]
    for name in ("target_result", "generated_result"):
        assert record[name]["rows"] == [[large_id]]
        assert record[name]["display_rows"] == [["9223372036854775807"]]


def test_successful_empty_results_remain_distinct_from_execution_errors(make_case):
    case = make_case(
        target_result=QueryResult(columns=["id"], rows=[], total_rows=0),
        generated_result=QueryResult(
            columns=[], rows=[], total_rows=None, execution_error="Missing column"
        ),
    )
    payload = ReportParser(render_html_report([case], score_cases(case))).payload
    record = payload["cases"][0]
    assert record["target_result"]["total_rows"] == 0
    assert record["target_result"]["execution_error"] is None
    assert record["generated_result"]["total_rows"] is None
    assert record["generated_result"]["execution_error"] == "Missing column"
    assert record["scores"]["row_count_match"]["status"] == "ERROR"


def test_user_text_cannot_break_out_of_the_embedded_json_or_create_markup(make_case):
    hostile = '</script><script id="injected">alert(1)</script><img src=x onerror=alert(2)>'
    hostile += " & < > \" ' \u2028\u2029 中文 __REPORT_CSS__ __REPORT_JS__ __REPORT_DATA__"
    case = make_case(
        case_id=hostile,
        question=hostile,
        target_sql=f"SELECT '{hostile}'",
        generated_sql=f"SELECT '{hostile}'",
        dialect=hostile,
        context=hostile,
        target_result=QueryResult(columns=[hostile], rows=[[hostile]], total_rows=1),
        generated_result=QueryResult(columns=[hostile], rows=[[hostile]], total_rows=1),
    )
    response = decision(reason=hostile)
    response["parsed"].evidence = [hostile]
    html = render_html_report(
        [case], score_cases(case, responder=lambda _: response), title=hostile
    )
    assert hostile not in html
    assert '<script id="injected">' not in html
    assert "\u2028" not in html
    assert "\u2029" not in html
    parser = ReportParser(html)
    assert not any(attributes.get("id") == "injected" for _, attributes in parser.tags)
    assert not any("onerror" in attributes for _, attributes in parser.tags)
    data_script = parser.report_scripts[0]
    assert "\\u003c" in data_script.lower()
    assert "\\u2028" in data_script
    assert "\\u2029" in data_script
    payload = parser.payload
    assert payload["title"] == hostile
    record = payload["cases"][0]
    assert record["case_id"] == hostile
    assert record["question"] == hostile
    assert record["context"] == hostile
    assert record["target_result"]["columns"] == [hostile]
    assert record["target_result"]["rows"] == [[hostile]]
    assert record["scores"]["sql_semantic"]["reason"] == hostile
    assert record["scores"]["sql_semantic"]["judgment"]["evidence"] == [hostile]


def test_html_has_no_external_asset_dependencies(make_case):
    case = make_case()
    parser = ReportParser(render_html_report([case], score_cases(case)))
    for tag, attrs in parser.tags:
        if tag == "script":
            assert "src" not in attrs
        if tag == "link":
            assert attrs.get("rel") not in {"stylesheet", "preload", "modulepreload"}


def test_writer_creates_a_standalone_file_and_returns_its_path(tmp_path, make_case):
    case = make_case()
    destination = tmp_path / "reports" / "scores.html"
    returned = write_html_report([case], score_cases(case), destination)
    assert returned.samefile(destination)
    assert ReportParser(destination.read_text(encoding="utf-8")).payload["cases"][0]["case_id"]
    assert not list(destination.parent.glob(".scores.html.*"))


def test_invalid_render_does_not_replace_an_existing_report(tmp_path, make_case):
    destination = tmp_path / "scores.html"
    destination.write_text("original report", encoding="utf-8")
    case = make_case()
    with pytest.raises(ValueError):
        write_html_report([case, case], score_cases(case), destination)
    assert destination.read_text(encoding="utf-8") == "original report"
