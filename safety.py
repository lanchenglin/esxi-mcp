from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


class SafetyError(RuntimeError):
    """Raised when a VM power operation is blocked by safety rules."""


def load_safety_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Loads safety configuration from config.yaml.

    Args:
        path: Path to config.yaml.

    Returns:
        Full parsed configuration dictionary.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SafetyError("Config file must contain a YAML mapping")
    return data


def check_power_permission(
    vm_name: str,
    action: str,
    confirm: bool = False,
    config: dict[str, Any] | None = None,
    unique: bool = True,
) -> dict[str, Any]:
    """Checks whether a VM power operation is allowed.

    Args:
        vm_name: Exact VM name.
        action: power_on, power_off, or restart_force.
        confirm: Whether the caller confirmed a dangerous operation.
        config: Optional loaded config dictionary.
        unique: Whether VM lookup resolved to exactly one VM name.

    Returns:
        Allow decision dictionary.

    Raises:
        SafetyError: If any safety rule blocks the operation.
    """
    if not unique:
        raise SafetyError(f"VM name duplicated: {vm_name}; use uuid or moid")
    if not vm_name:
        raise SafetyError("VM name is required for power operation safety check")

    loaded_config = config if config is not None else load_safety_config()
    safety_config = loaded_config.get("safety", {})
    if not isinstance(safety_config, dict):
        raise SafetyError("safety config must be a mapping")

    if action == "power_off" and safety_config.get("require_confirm_for_poweroff", True) and not confirm:
        raise SafetyError("power_off_vm confirm=true required")
    if action == "restart_force" and safety_config.get("require_confirm_for_restart", True) and not confirm:
        raise SafetyError("restart_vm_force confirm=true required")
    if action not in {"power_on", "power_off", "restart_force"}:
        raise SafetyError(f"Unsupported power action: {action}")

    allow_patterns = _string_list(safety_config.get("allow_power_ops", []))
    deny_patterns = _string_list(safety_config.get("deny_power_ops", []))

    if _matches_any(vm_name, deny_patterns):
        raise SafetyError("VM matched deny_power_ops")
    if not allow_patterns:
        raise SafetyError("No allow_power_ops configured; refusing VM power operation")
    if not _matches_any(vm_name, allow_patterns):
        raise SafetyError("VM did not match allow_power_ops")

    return {
        "allowed": True,
        "action": action,
        "vm": vm_name,
        "reason": "VM matched allow_power_ops",
    }


def _matches_any(vm_name: str, patterns: list[str]) -> bool:
    normalized_name = vm_name.casefold()
    return any(fnmatchcase(normalized_name, pattern.casefold()) for pattern in patterns)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SafetyError("allow_power_ops and deny_power_ops must be lists")
    return [item for item in value if isinstance(item, str) and item]
