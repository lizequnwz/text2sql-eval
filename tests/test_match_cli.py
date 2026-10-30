"""Run the standalone JSON comparator without model configuration or SQL execution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from text2sql_eval import match_cli


def write_dataset(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def invoke_error(arguments):
    """Both parser errors and runtime validation failures must be exit code two."""
    try:
        return match_cli.main(arguments)
    except SystemExit as exc:
        return exc.code


def test_help_does_not_require_credentials(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(SystemExit) as raised:
        match_cli.main(["--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "--target" in output and "--generated" in output


def test_acceptance_prints_json_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    target = write_dataset(tmp_path / "target.json", [[1, 100], [2, 200]])
    generated = write_dataset(tmp_path / "generated.json", [[2], [1]])
    assert match_cli.main(["--target", str(target), "--generated", str(generated)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["accepted"] is True
    assert output["matched_row_count"] == 2
    assert output["row_relation_counts"]["generated_subset"] == 2


def test_row_policy_rejection_has_a_json_outcome_and_exit_one(tmp_path, capsys):
    target = write_dataset(tmp_path / "target.json", [[1, 100]])
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    assert (
        match_cli.main(
            [
                "--target",
                str(target),
                "--generated",
                str(generated),
                "--row-policy",
                "target_subset",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["accepted"] is False


@pytest.mark.parametrize(
    ("target_json", "generated_json", "expected_code"),
    [
        ("[[0.1000000000000000000001]]", "[[0.1]]", 1),
        ("[[0.1000000000000000000000]]", "[[0.1]]", 0),
        ("[[9007199254740993.0]]", "[[9007199254740992.0]]", 1),
    ],
)
def test_json_numeric_precision_is_preserved_before_comparison(
    tmp_path, capsys, target_json, generated_json, expected_code
):
    target, generated = tmp_path / "target.json", tmp_path / "generated.json"
    target.write_text(target_json, encoding="utf-8")
    generated.write_text(generated_json, encoding="utf-8")
    code = match_cli.main(["--target", str(target), "--generated", str(generated)])
    assert code == expected_code
    assert json.loads(capsys.readouterr().out)["accepted"] is (expected_code == 0)


def test_dataset_policy_can_accept_extra_rows_and_write_atomic_json(tmp_path):
    target = write_dataset(tmp_path / "target.json", [["A"]])
    generated = write_dataset(tmp_path / "generated.json", [["A"], ["B"]])
    output = tmp_path / "reports" / "comparison.json"
    code = match_cli.main(
        [
            "--target",
            str(target),
            "--generated",
            str(generated),
            "--dataset-policy",
            "bidirectional",
            "--output",
            str(output),
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["accepted"] is True
    assert payload["relation"] == "target_subset"
    assert payload["row_count_match"] is False
    assert not list(output.parent.glob(".comparison.json.*"))


def test_same_input_file_may_be_compared_with_itself(tmp_path, capsys):
    source = write_dataset(tmp_path / "same.json", [[1]])
    assert match_cli.main(["--target", str(source), "--generated", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["relation"] == "full_match"


def test_default_dataset_subset_acceptance_can_be_disabled_at_cli(tmp_path, capsys):
    target = write_dataset(tmp_path / "target.json", [["A"], ["B"]])
    generated = write_dataset(tmp_path / "generated.json", [["A"]])
    arguments = ["--target", str(target), "--generated", str(generated)]
    assert match_cli.main(arguments) == 0
    default = json.loads(capsys.readouterr().out)
    assert default["relation"] == "generated_subset"
    assert default["config"]["dataset_policy"] == "bidirectional"
    assert default["row_count_match"] is False
    assert match_cli.main([*arguments, "--dataset-policy", "equal"]) == 1
    assert json.loads(capsys.readouterr().out)["accepted"] is False


@pytest.mark.parametrize("colliding_input", ["target", "generated"])
def test_output_cannot_overwrite_either_input(tmp_path, colliding_input):
    target = write_dataset(tmp_path / "target.json", [[1]])
    generated = write_dataset(tmp_path / "generated.json", [[1, 100]])
    snapshots = {target: target.read_bytes(), generated: generated.read_bytes()}
    output = target if colliding_input == "target" else generated
    assert (
        invoke_error(
            ["--target", str(target), "--generated", str(generated), "--output", str(output)]
        )
        == 2
    )
    assert all(path.read_bytes() == content for path, content in snapshots.items())


def test_output_symlink_and_hardlink_collisions_preserve_input(tmp_path):
    target = write_dataset(tmp_path / "target.json", [[1]])
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    snapshot = target.read_bytes()
    for kind in ("symlink", "hardlink"):
        output = tmp_path / f"{kind}.json"
        if kind == "symlink":
            output.symlink_to(target)
        else:
            os.link(target, output)
        assert (
            invoke_error(
                ["--target", str(target), "--generated", str(generated), "--output", str(output)]
            )
            == 2
        )
        assert target.read_bytes() == snapshot


@pytest.mark.parametrize("invalid", ["{broken", "null", "[[1],[2,3]]"])
def test_invalid_inputs_return_two_and_do_not_write_output(tmp_path, invalid):
    target = tmp_path / "target.json"
    target.write_text(invalid, encoding="utf-8")
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    output = tmp_path / "comparison.json"
    assert (
        invoke_error(
            ["--target", str(target), "--generated", str(generated), "--output", str(output)]
        )
        == 2
    )
    assert not output.exists()


@pytest.mark.parametrize(
    "invalid",
    [
        "[[NaN]]",
        "[[Infinity]]",
        "[[-Infinity]]",
        '[{"id":1,"id":2}]',
        '{"columns":["id"],"rows":[[1]],"rows":[[2]]}',
    ],
)
def test_json_with_nonfinite_values_or_duplicate_keys_is_not_silently_changed(tmp_path, invalid):
    target = tmp_path / "target.json"
    target.write_text(invalid, encoding="utf-8")
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    assert invoke_error(["--target", str(target), "--generated", str(generated)]) == 2


def test_missing_input_returns_two(tmp_path):
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    assert (
        invoke_error(["--target", str(tmp_path / "absent.json"), "--generated", str(generated)])
        == 2
    )


def test_truncated_query_result_json_is_not_reported_as_a_complete_comparison(tmp_path):
    target = write_dataset(
        tmp_path / "target.json", {"columns": ["id"], "rows": [[1]], "total_rows": 2}
    )
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    assert invoke_error(["--target", str(target), "--generated", str(generated)]) == 2


def test_resource_limit_is_an_error_instead_of_a_comparison_rejection(tmp_path, capsys):
    target = write_dataset(tmp_path / "target.json", [["A"], ["B"]])
    generated = write_dataset(tmp_path / "generated.json", [["A", "B"], ["A", "C"]])
    assert (
        invoke_error(
            [
                "--target",
                str(target),
                "--generated",
                str(generated),
                "--max-candidate-edges",
                "1",
            ]
        )
        == 2
    )
    assert '"accepted": false' not in capsys.readouterr().out


def test_write_failure_is_actionable_and_keeps_inputs(tmp_path, capsys):
    target = write_dataset(tmp_path / "target.json", [[1]])
    generated = write_dataset(tmp_path / "generated.json", [[1]])
    output = tmp_path / "directory"
    output.mkdir()
    assert (
        invoke_error(
            ["--target", str(target), "--generated", str(generated), "--output", str(output)]
        )
        == 2
    )
    assert capsys.readouterr().err
    assert json.loads(target.read_text()) == [[1]]
    assert json.loads(generated.read_text()) == [[1]]
