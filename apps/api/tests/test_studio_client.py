"""Launch Studio client (M5): the mesh's only door to the studio CLI."""
import json
import os
import sys
import time

import pytest

from dispatch import studio_client as sc


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_DIR", str(tmp_path))
    calls = []

    def fake(argv, cwd, env, timeout):
        calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        return fake.reply

    fake.reply = (0, "", "")
    fake.calls = calls
    monkeypatch.setattr(sc, "runner", fake)
    return fake


def test_reads_the_exit_code_and_the_last_line(cli, tmp_path):
    cli.reply = (3, "run: sample-desk at spec\nSTOP sample-desk spec-1\n", "")
    res = sc.run(["run", "sample-desk"], timeout=60)
    assert res.code == 3 and res.last == "STOP sample-desk spec-1" and not res.ok
    assert cli.calls[0]["argv"] == ["npx", "-y", "pnpm@12.8.1", "studio", "run", "sample-desk"]
    assert cli.calls[0]["cwd"] == tmp_path and cli.calls[0]["timeout"] == 60


def test_a_missing_studio_is_a_result_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_DIR", str(tmp_path / "nope"))
    res = sc.run(["status", "--json"])
    assert res.code is None and "not installed" in res.error


def test_a_missing_npx_is_a_result(cli, monkeypatch):
    def boom(*_a):
        raise FileNotFoundError("npx")

    monkeypatch.setattr(sc, "runner", boom)
    assert "PATH" in sc.run(["status"]).error


def test_a_stack_trace_never_becomes_the_chat_reason(cli):
    cli.reply = (1, "Error: boom\n    at main (/Users/clawd/dev/launch-studio/scripts/studio.ts:40:9)\n", "")
    res = sc.run(["answer", "sample-desk", "spec-1", "approve"])
    assert res.code == 1
    assert "studio.ts" not in res.error and "at main" not in res.error and "mesh log" in res.error


def test_a_fail_line_is_the_reason(cli):
    cli.reply = (1, "FAIL sample-desk no progress at build\n", "")
    assert sc.run(["run", "sample-desk"]).error == "sample-desk no progress at build"


def test_the_child_gets_studio_settings_but_not_mesh_secrets(cli, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    monkeypatch.setenv("FMP_API_KEY", "k")
    monkeypatch.setenv("STUDIO_MAX_RUNS", "2")
    monkeypatch.setenv("CLAUDE_CLI_PATH", "/Users/clawd/.local/bin/claude")
    sc.run(["status"])
    env = cli.calls[0]["env"]
    assert "TELEGRAM_BOT_TOKEN" not in env and "FMP_API_KEY" not in env
    assert env["STUDIO_MAX_RUNS"] == "2" and env["CLAUDE_CLI_PATH"] == "/Users/clawd/.local/bin/claude"
    assert env["PATH"]


def test_pending_stops_reads_the_json_line(cli):
    cli.reply = (0, '$ node --import tsx scripts/studio.ts\n{"stops":[{"id":"spec-1","slug":"sample-desk"}]}\n', "")
    assert sc.pending_stops() == [{"id": "spec-1", "slug": "sample-desk"}]


def test_pending_stops_is_none_when_the_cli_fails(cli):
    cli.reply = (1, "FAIL no project\n", "")
    assert sc.pending_stops() is None


def test_a_long_json_line_is_not_cut(cli):
    body = "x" * 3000
    cli.reply = (0, json.dumps({"stops": [{"id": "spec-1", "slug": "sample-desk", "body": body}]}) + "\n", "")
    assert sc.pending_stops()[0]["body"] == body


def test_a_timeout_kills_the_whole_process_group(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[1], 'w').write(str(g.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(60)\n"
    )
    t0 = time.monotonic()
    code, out, _err = sc.popen_runner([sys.executable, "-c", script, str(pidfile)], tmp_path, dict(os.environ), 1.0)
    assert code is None and "started" in out
    assert time.monotonic() - t0 < 10
    grandchild = int(pidfile.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the grandchild survived the timeout")


PNPM_BANNER = "$ node --import tsx scripts/studio.ts answer sample-desk spec-1 x --by telegram\n"
PNPM_FAILED = "[ELIFECYCLE] Command failed with exit code 1.\n"


def test_the_cli_error_line_on_stderr_is_the_reason(cli):
    cli.reply = (1, "", PNPM_BANNER + "studio answer: unknown option\n" + PNPM_FAILED)
    res = sc.run(["answer", "sample-desk", "spec-1", "x", "--by", "telegram"])
    assert res.code == 1 and res.error == "unknown option"


def test_a_stack_trace_on_stderr_never_becomes_the_reason(cli):
    trace = ("file:///Users/clawd/dev/launch-studio/studio/cli.ts:3\nSyntaxError: Unexpected token\n"
             "    at compileSourceTextModule (node:internal/modules/esm/utils:340:16)\n\nNode.js v22.22.0\n")
    cli.reply = (1, "", PNPM_BANNER + trace + PNPM_FAILED)
    res = sc.run(["status", "--json"])
    assert "mesh log" in res.error and "Node.js" not in res.error and "cli.ts" not in res.error


def test_popen_runner_keeps_stderr_apart(tmp_path):
    script = "import sys; print('out'); print('err', file=sys.stderr)"
    assert sc.popen_runner([sys.executable, "-c", script], tmp_path, dict(os.environ), 10.0) == (0, "out\n", "err\n")
