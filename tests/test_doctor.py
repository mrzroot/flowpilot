"""Tests for standalone flowpilot.doctor diagnostics."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_DOCTOR_PATH = Path(__file__).resolve().parents[1] / "src" / "flowpilot" / "doctor.py"
_SPEC = importlib.util.spec_from_file_location("flowpilot_doctor_standalone", _DOCTOR_PATH)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
run_doctor = _MOD.run_doctor


def _make_proj(tmp_path: Path, workflow_yaml: str = "steps:\n  - id: ping\n    type: log\n    with: {message: ok}\n", config_yaml: str = "workflows_dir: workflows\nhost: 127.0.0.1\n", env_text: str = "") -> Path:
    (tmp_path / "workflows").mkdir(exist_ok=True)
    (tmp_path / "flowpilot.yaml").write_text(config_yaml, encoding="utf-8")
    (tmp_path / "workflows" / "sample.yaml").write_text(workflow_yaml, encoding="utf-8")
    if env_text:
        (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    return tmp_path


def test_doctor_valid_project_and_env(tmp_path: Path) -> None:
    proj = _make_proj(
        tmp_path,
        workflow_yaml="steps:\n  - id: notify\n    type: telegram\n    with:\n      text: '{{ env.TELEGRAM_BOT_TOKEN }}'\n",
        env_text="TELEGRAM_BOT_TOKEN=123:abc\n",
    )
    report = run_doctor(proj)
    assert report["ok"] is True
    assert report["config_present"] is True
    assert report["workflows_checked"] == 1
    assert report["env_present"] == ["TELEGRAM_BOT_TOKEN"]
    assert report["env_missing"] == []
    assert report["errors"] == []


def test_doctor_flags_missing_env_broken_yaml_and_security(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SECRET_WEBHOOK_KEY", raising=False)
    monkeypatch.delenv("FLOWPILOT_API_TOKEN", raising=False)
    proj = _make_proj(
        tmp_path,
        config_yaml="workflows_dir: workflows\nhost: 0.0.0.0\nallow_shell: true\n",
        workflow_yaml="steps:\n  - id: a\n    with: {k: '{{ env.SECRET_WEBHOOK_KEY }}'}\n",
    )
    (proj / "workflows" / "broken.yml").write_text("steps: [unclosed\n", encoding="utf-8")

    report = run_doctor(proj)
    assert report["ok"] is False
    assert report["workflows_checked"] == 2
    assert report["env_missing"] == ["SECRET_WEBHOOK_KEY"]
    assert any("allow_shell is enabled" in w for w in report["warnings"])
    assert any("without api_token" in w for w in report["warnings"])
    assert any("broken.yml" in e for e in report["errors"])


@pytest.mark.skipif(importlib.util.find_spec("jmespath") is None, reason="full flowpilot runtime deps not installed")
def test_doctor_cli_json_and_exit_code(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from flowpilot.cli import cli

    proj = _make_proj(tmp_path)
    runner = CliRunner()
    res = runner.invoke(cli, ["-p", str(proj), "doctor", "--json"])
    assert res.exit_code == 0, res.output
    assert '"ok": true' in res.output

    (proj / "workflows" / "empty.yaml").write_text("name: empty\nsteps: []\n", encoding="utf-8")
    bad = runner.invoke(cli, ["-p", str(proj), "doctor"])
    assert bad.exit_code == 1
    assert "non-empty list" in bad.output
