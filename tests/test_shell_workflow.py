"""Exercise the Bash entry point offline without credentials or paid judge calls."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "eval.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="The helper targets Bash on macOS/Linux.")


@pytest.fixture
def runner(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "uv-arguments.json"
    fake_uv = binaries / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['WORKFLOW_TEST_LOG']).write_text(json.dumps({\n"
        "  'arguments': sys.argv[1:], 'cwd': os.getcwd()\n"
        "}))\n"
        "raise SystemExit(int(os.environ.get('WORKFLOW_TEST_EXIT', '0')))\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    caller = tmp_path / "caller directory"
    caller.mkdir()

    def run(*args, exit_code=0, key=None, script=SCRIPT):
        if log.exists():
            log.unlink()
        environment = dict(os.environ)
        environment.update(
            PATH=f"{binaries}:/usr/bin:/bin",
            WORKFLOW_TEST_LOG=str(log),
            WORKFLOW_TEST_EXIT=str(exit_code),
        )
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("OPENAI_MODEL", None)
        if key is not None:
            environment["OPENAI_API_KEY"] = key
        result = subprocess.run(
            [BASH, str(script), *args],
            cwd=caller,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(log.read_text()) if log.exists() else None

    return run, caller


def test_bash_script_has_valid_syntax():
    subprocess.run([BASH, "-n", str(SCRIPT)], check=True)


@pytest.mark.parametrize("arguments", [[], ["--help"], ["eval", "--help"], ["demo", "--help"]])
def test_help_never_invokes_uv_or_requires_credentials(runner, arguments):
    run, _ = runner
    result, invocation = run(*arguments)
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert invocation is None


def test_unknown_commands_are_rejected_without_starting_any_tool(runner):
    run, _ = runner
    result, invocation = run("unknown")
    assert result.returncode == 2
    assert "Unknown command" in result.stderr
    assert invocation is None


def test_setup_installs_the_correct_locked_project_without_dev_packages(runner):
    run, _ = runner
    result, invocation = run("setup")
    assert result.returncode == 0
    assert invocation["arguments"] == ["sync", "--project", str(ROOT), "--locked", "--no-dev"]


def test_setup_failures_are_configuration_errors(runner):
    run, _ = runner
    result, _ = run("setup", exit_code=1)
    assert result.returncode == 2
    assert "Setup failed" in result.stderr


def test_demo_preserves_caller_paths_spaces_and_explicit_output(runner):
    run, caller = runner
    result, invocation = run("demo", "--output", "my reports/review.html")
    assert result.returncode == 0
    assert invocation["cwd"] == str(caller)
    assert invocation["arguments"] == [
        "run",
        "--project",
        str(ROOT),
        "--locked",
        "--no-sync",
        "--no-env-file",
        "python",
        str(ROOT / "examples" / "html_report.py"),
        "--output",
        str(ROOT / "reports" / "demo.html"),
        "--output",
        "my reports/review.html",
    ]


def test_eval_requires_an_exported_key_before_tool_invocation(runner):
    run, _ = runner
    result, invocation = run("eval", "--input", "cases.jsonl", "--model", "test-model")
    assert result.returncode == 2
    assert "Set OPENAI_API_KEY" in result.stderr
    assert invocation is None


def test_eval_forwards_options_and_preserves_the_operational_error_exit_code(runner):
    run, _ = runner
    secret = "workflow-test-placeholder-do-not-log"
    result, invocation = run(
        "eval",
        "--input",
        "my data/cases.jsonl",
        "--model",
        "test-model",
        "--output=reports/custom.json",
        exit_code=1,
        key=secret,
    )
    assert result.returncode == 1
    args = invocation["arguments"]
    assert args[:7] == [
        "run",
        "--project",
        str(ROOT),
        "--locked",
        "--no-sync",
        "--no-env-file",
        "text2sql-eval",
    ]
    assert args[7:9] == ["--output", str(ROOT / "reports" / "evaluation.json")]
    assert args[9:] == [
        "--input",
        "my data/cases.jsonl",
        "--model",
        "test-model",
        "--output=reports/custom.json",
    ]
    assert secret not in result.stdout + result.stderr + json.dumps(invocation)


def test_saved_report_export_does_not_require_model_configuration(runner):
    run, _ = runner
    result, invocation = run("report", "--cases", "cases.jsonl", "--results", "scores.json")
    assert result.returncode == 0
    args = invocation["arguments"]
    assert "text2sql-eval-report" in args
    assert args[-4:] == ["--cases", "cases.jsonl", "--results", "scores.json"]
    assert "--model" not in args


def test_missing_environment_shows_setup_command_instead_of_starting_uv(runner, tmp_path):
    run, _ = runner
    scripts = tmp_path / "fresh checkout" / "scripts"
    scripts.mkdir(parents=True)
    copied = scripts / "eval.sh"
    shutil.copyfile(SCRIPT, copied)
    result, invocation = run("demo", script=copied)
    assert result.returncode == 2
    assert "Run setup first" in result.stderr
    assert invocation is None
