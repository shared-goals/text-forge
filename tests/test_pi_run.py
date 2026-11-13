"""Tests for `scripts/pi-run.py` — pi's JSON event stream rendered for a human.

pi itself is replaced by a fake executable (the `PI` environment variable exists
exactly for this): the wrapper owns event parsing, the summary line and the exit
code, and those are what these tests pin.
"""

import os
import pathlib
import stat
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "pi-run.py"

STREAM = """\
{"type":"session","version":3,"id":"s1","cwd":"/tmp"}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_end","message":{"role":"user","content":"job"}}
{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}
{"type":"tool_execution_start","toolCallId":"c1","toolName":"read_file","args":{}}
{"type":"tool_execution_end","toolCallId":"c1","toolName":"read_file","result":"x","isError":false,"durationMs":12}
{"type":"message_update","usage":{"input":1200,"output":40},"assistantMessageEvent":{"type":"text_delta","delta":"Гот"}}
{"type":"message_update","usage":{"input":1200,"output":44},"assistantMessageEvent":{"type":"thinking_delta","delta":"…"}}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"Готово: [bold]3[/bold] находки"}]}}
{"type":"agent_end","messages":[],"willRetry":false}
{"type":"agent_settled","aborted":false}
"""


def fake_pi(tmp_path: pathlib.Path, body: str, exit_code: int = 0) -> pathlib.Path:
    """An executable named `pi` that prints `body` and exits with `exit_code`."""
    path = tmp_path / "pi"
    path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{body}EOF\nexit {exit_code}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def run(job: pathlib.Path, pi: pathlib.Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PI=str(pi))
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(job)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tempfile.mkdtemp(),
        check=False,
    )


def make_job(tmp_path: pathlib.Path) -> pathlib.Path:
    job = tmp_path / "job.md"
    job.write_text("Проверь текст и запиши отчёт.\n", encoding="utf-8")
    return job


class TestStream:
    def test_prints_the_final_answer_and_a_summary(self, tmp_path):
        job = make_job(tmp_path)
        proc = run(job, fake_pi(tmp_path, STREAM))
        assert proc.returncode == 0, proc.stderr
        assert "Готово" in proc.stderr
        # one turn, one tool call, cumulative usage from the last update
        assert "1 turn" in proc.stderr
        assert "1 tool" in proc.stderr
        assert "1.2k in / 44 out" in proc.stderr

    def test_model_text_is_not_rich_markup(self, tmp_path):
        job = make_job(tmp_path)
        proc = run(job, fake_pi(tmp_path, STREAM))
        # "[bold]3[/bold]" must survive verbatim: an answer is text, not styling
        assert "[bold]3[/bold]" in proc.stderr

    def test_failing_run_reports_the_exit_code(self, tmp_path):
        job = make_job(tmp_path)
        proc = run(job, fake_pi(tmp_path, STREAM, exit_code=3))
        assert proc.returncode == 3
        assert "pi exited 3" in proc.stderr

    def test_garbage_on_stdout_is_skipped(self, tmp_path):
        job = make_job(tmp_path)
        body = "warning: something\n" + STREAM
        proc = run(job, fake_pi(tmp_path, body))
        assert proc.returncode == 0, proc.stderr
        assert "Готово" in proc.stderr


class TestUsage:
    def test_missing_job_file_exits_2(self, tmp_path):
        proc = run(tmp_path / "nope.md", fake_pi(tmp_path, STREAM))
        assert proc.returncode == 2
        assert "cannot read job" in proc.stderr

    def test_header_names_the_job(self, tmp_path):
        job = make_job(tmp_path)
        proc = run(job, fake_pi(tmp_path, STREAM))
        assert "job.md" in proc.stderr
