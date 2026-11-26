"""Standalone project health and readiness checks for flowpilot."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

CONFIG_FILENAME = "flowpilot.yaml"
_ENV_REF_RE = re.compile(r"\benv\.([A-Z][A-Z0-9_]*)\b")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_doctor(project_dir: str | Path | None = None) -> dict[str, Any]:
    """Audit ``flowpilot.yaml``, ``.env``, and YAML workflows without starting the engine."""
    root = Path(project_dir or os.environ.get("FLOWPILOT_PROJECT") or Path.cwd()).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    env_values: dict[str, str] = {}
    env_file = root / ".env"
    if env_file.is_file():
        for k, v in dotenv_values(env_file).items():
            if v is not None:
                env_values[k] = v

    cfg_path = root / CONFIG_FILENAME
    config_present = cfg_path.is_file()
    cfg: dict[str, Any] = {}
    if config_present:
        try:
            loaded = _read_yaml(cfg_path) or {}
            if not isinstance(loaded, dict):
                errors.append(f"{CONFIG_FILENAME} must contain a mapping")
            else:
                cfg = loaded
        except yaml.YAMLError as exc:
            errors.append(f"{CONFIG_FILENAME}: invalid YAML ({exc})")
    else:
        warnings.append(f"{CONFIG_FILENAME} not found; using built-in defaults")

    host = str(os.environ.get("FLOWPILOT_HOST") or cfg.get("host") or "127.0.0.1")
    allow_shell = str(os.environ.get("FLOWPILOT_ALLOW_SHELL") or cfg.get("allow_shell") or "").lower() in {"1", "true", "yes", "on"}
    api_token = os.environ.get("FLOWPILOT_API_TOKEN") or cfg.get("api_token")
    if allow_shell:
        warnings.append("allow_shell is enabled; ensure workflows and host are trusted")
    if host not in _LOCAL_HOSTS and not api_token:
        warnings.append(f"listening on {host!r} without api_token / FLOWPILOT_API_TOKEN")

    wf_rel = cfg.get("workflows_dir") or "workflows"
    wf_dir = Path(wf_rel) if Path(wf_rel).is_absolute() else (root / wf_rel)
    referenced_env: set[str] = set()
    workflows_checked = 0

    if not wf_dir.is_dir():
        errors.append(f"workflows directory not found: {wf_dir}")
    else:
        files = sorted([*wf_dir.glob("*.yaml"), *wf_dir.glob("*.yml")])
        if not files:
            warnings.append(f"no workflow YAML files found in {wf_dir}")
        for wf_file in files:
            workflows_checked += 1
            raw = wf_file.read_text(encoding="utf-8")
            referenced_env.update(_ENV_REF_RE.findall(raw))
            try:
                doc = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                errors.append(f"{wf_file.name}: YAML syntax error ({exc})")
                continue
            if not isinstance(doc, dict):
                errors.append(f"{wf_file.name}: workflow must be a YAML mapping")
                continue
            steps = doc.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append(f"{wf_file.name}: 'steps' must be a non-empty list")

    env_present = sorted(k for k in referenced_env if os.environ.get(k) or env_values.get(k))
    env_missing = sorted(k for k in referenced_env if k not in env_present)
    if env_missing:
        warnings.append(f"missing referenced env var(s): {', '.join(env_missing)}")

    return {
        "ok": not errors,
        "project_dir": str(root),
        "config_present": config_present,
        "workflows_checked": workflows_checked,
        "env_present": env_present,
        "env_missing": env_missing,
        "warnings": warnings,
        "errors": errors,
    }
