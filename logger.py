"""decision_log.json and outputs/ writers, shared by every agent.

    log_action(agent="researcher", action="weighted_search", sources=[...], model="qwen3:8b", cost=0)
    write_output(phase=1, step=2, name="domains", content="...", status="Working")
    write_gate(phase=1, name="decision", content="...")
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from config import settings
from schemas import Status, utc_now

REQUIRED_KEYS = ("action", "sources", "model", "cost", "approved_by")
_lock = threading.Lock()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise ValueError("output name must contain letters or digits")
    return slug


def log_action(
    agent: str,
    action: str,
    sources: Optional[Iterable[str]] = None,
    model: Optional[str] = None,
    cost: float = 0,
    approved_by: Optional[str] = None,
    log_path: Optional[Path] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Append one entry to decision_log.json and return it.

    approved_by must be "founder" for gated actions and None otherwise.
    """
    if approved_by not in (None, "founder"):
        raise ValueError("approved_by must be 'founder' or None")
    entry: dict[str, Any] = {
        "timestamp": utc_now(),
        "agent": agent,
        "action": action,
        "sources": list(sources or []),
        "model": model,
        "cost": float(cost),
        "approved_by": approved_by,
        **extra,
    }
    path = Path(log_path or settings.decision_log_path)
    with _lock:
        entries: list[dict[str, Any]] = []
        if path.exists() and path.read_text(encoding="utf-8").strip():
            entries = json.loads(path.read_text(encoding="utf-8"))
        entries.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    return entry


def _header(status: Status) -> str:
    if status == "Working":
        return ""
    return f"> **{status}**: this output comes from a {status.lower()} step, not a working feature.\n\n"


def write_output(
    phase: int,
    step: int,
    name: str,
    content: str,
    status: Status = "Working",
    ext: str = "md",
    outputs_dir: Optional[Path] = None,
) -> Path:
    """Write outputs/phase<N>_step<M>_<name>.<ext>, labelling MOCKED/STUBBED steps at the top."""
    return _write(f"phase{int(phase)}_step{int(step)}_{_slug(name)}.{ext}", content, status, ext, outputs_dir)


def write_gate(
    phase: int,
    name: str,
    content: str,
    status: Status = "Working",
    ext: str = "md",
    outputs_dir: Optional[Path] = None,
) -> Path:
    """Write outputs/phase<N>_gate_<name>.<ext>."""
    return _write(f"phase{int(phase)}_gate_{_slug(name)}.{ext}", content, status, ext, outputs_dir)


def _write(filename: str, content: str, status: Status, ext: str, outputs_dir: Optional[Path]) -> Path:
    if ext not in ("md", "json", "csv", "txt", "html"):
        raise ValueError("outputs/ takes text formats only: md, json, csv, txt, html")
    folder = Path(outputs_dir or settings.outputs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    body = _header(status) + content if ext in ("md", "txt") else content
    path.write_text(body, encoding="utf-8")
    return path
