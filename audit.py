from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 10 * 1024 * 1024


class AuditLogError(RuntimeError):
    """Raised when an audit log entry cannot be written."""


def write_audit_log(
    config: dict[str, Any],
    entry: dict[str, Any],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    """Writes an audit entry as JSON Lines, rotating large logs.

    Args:
        config: Loaded project configuration.
        entry: Audit entry fields.
        max_bytes: Maximum audit file size before rotation.
    """
    audit_config = config.get("audit", {}) if isinstance(config, dict) else {}
    if isinstance(audit_config, dict) and audit_config.get("enabled", True) is False:
        return

    audit_file = Path(audit_config.get("file", "./logs/audit.log")) if isinstance(audit_config, dict) else Path("./logs/audit.log")
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(audit_file, max_bytes)

    payload = {
        "time": datetime.now(timezone.utc).astimezone().isoformat(),
        "operator": os.getenv("USER") or "mcp-user",
        **entry,
    }
    with audit_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    if not path.exists() or path.stat().st_size < max_bytes:
        return
    rotated = path.with_suffix(path.suffix + ".1")
    if rotated.exists():
        rotated.unlink()
    path.rename(rotated)
