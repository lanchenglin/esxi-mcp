from __future__ import annotations

import time
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from pyVmomi import vim

from audit import write_audit_log
from host_inventory import get_host_resource as get_host_resource_impl
from host_inventory import list_hosts as list_hosts_impl
from safety import SafetyError, check_power_permission
from vm_inventory import find_vm, get_vm_status as get_vm_status_impl
from vm_inventory import is_vm_name_unique, list_vms as list_vms_impl
from vm_power import power_off_vm_impl, power_on_vm_impl, restart_vm_force_impl
from vsphere_client import VSphereClient, load_config


CONFIG = load_config()
CLIENT = VSphereClient(CONFIG)
mcp = FastMCP(CONFIG.get("mcp", {}).get("name", "esxi-power-mcp"))


def _service_instance() -> vim.ServiceInstance:
    return CLIENT.get_service_instance()


@mcp.tool()
def list_vms(keyword: str | None = None, power_state: str | None = None) -> dict[str, Any]:
    """Lists VMs, optionally filtered by keyword and power_state."""
    return list_vms_impl(_service_instance(), keyword=keyword, power_state=power_state)


@mcp.tool()
def get_vm_status(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
) -> dict[str, Any]:
    """Gets detailed status for one VM by moid, uuid, or unique name."""
    return get_vm_status_impl(_service_instance(), vm_name=vm_name, uuid=uuid, moid=moid)


@mcp.tool()
def list_hosts(keyword: str | None = None) -> dict[str, Any]:
    """Lists ESXi hosts, optionally filtered by keyword."""
    return list_hosts_impl(_service_instance(), keyword=keyword)


@mcp.tool()
def get_host_resource(host_name: str) -> dict[str, Any]:
    """Gets CPU, memory, and VM-count resource summary for one host."""
    return get_host_resource_impl(_service_instance(), host_name=host_name)


@mcp.tool()
def power_on_vm(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Powers on a VM after whitelist and blacklist safety checks."""
    start = time.monotonic()
    return _run_write_operation(
        "power_on_vm",
        vm_name,
        uuid,
        moid,
        "power_on",
        False,
        lambda vm: power_on_vm_impl(vm, task_timeout=task_timeout, state_timeout=state_timeout),
        start,
    )


@mcp.tool()
def power_off_vm(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
    confirm: bool = False,
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Force-powers off a VM; confirm=true is required."""
    start = time.monotonic()
    return _run_write_operation(
        "power_off_vm",
        vm_name,
        uuid,
        moid,
        "power_off",
        confirm,
        lambda vm: power_off_vm_impl(vm, task_timeout=task_timeout, state_timeout=state_timeout),
        start,
    )


@mcp.tool()
def restart_vm_force(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
    confirm: bool = False,
    poweroff_task_timeout: int = 300,
    poweroff_state_timeout: int = 900,
    poweron_task_timeout: int = 300,
    poweron_state_timeout: int = 900,
    boot_wait: int = 30,
) -> dict[str, Any]:
    """Force-restarts a VM; confirm=true is required."""
    start = time.monotonic()
    return _run_write_operation(
        "restart_vm_force",
        vm_name,
        uuid,
        moid,
        "restart_force",
        confirm,
        lambda vm: restart_vm_force_impl(
            vm,
            confirm=confirm,
            poweroff_task_timeout=poweroff_task_timeout,
            poweroff_state_timeout=poweroff_state_timeout,
            poweron_task_timeout=poweron_task_timeout,
            poweron_state_timeout=poweron_state_timeout,
            boot_wait=boot_wait,
        ),
        start,
    )


def _run_write_operation(
    tool: str,
    vm_name: str | None,
    uuid: str | None,
    moid: str | None,
    action: str,
    confirm: bool,
    operation: Callable[[vim.VirtualMachine], dict[str, Any]],
    start: float,
) -> dict[str, Any]:
    service_instance = _service_instance()
    vm_for_log = vm_name or uuid or moid or "unknown"
    try:
        vm = find_vm(service_instance, vm_name=vm_name, uuid=uuid, moid=moid)
        unique = True if moid or uuid else is_vm_name_unique(service_instance, vm.name)
        check_power_permission(vm.name, action=action, confirm=confirm, config=CONFIG, unique=unique)
        result = operation(vm)
        write_audit_log(
            CONFIG,
            {
                "tool": tool,
                "vm": vm.name,
                "moid": getattr(vm, "_moId", None),
                "confirm": confirm,
                "before_power_state": _before_power_state(result),
                "after_power_state": _after_power_state(result),
                "result": "success",
                "operation_result": result.get("result"),
                "duration_seconds": round(time.monotonic() - start, 3),
            },
        )
        return result
    except SafetyError as exc:
        write_audit_log(
            CONFIG,
            {
                "tool": tool,
                "vm": vm_for_log,
                "confirm": confirm,
                "result": "blocked",
                "reason": str(exc),
                "duration_seconds": round(time.monotonic() - start, 3),
            },
        )
        raise
    except Exception as exc:
        write_audit_log(
            CONFIG,
            {
                "tool": tool,
                "vm": vm_for_log,
                "confirm": confirm,
                "result": "failure",
                "reason": str(exc),
                "duration_seconds": round(time.monotonic() - start, 3),
            },
        )
        raise


def _before_power_state(result: dict[str, Any]) -> Any:
    if "before_power_state" in result:
        return result["before_power_state"]
    before = result.get("before")
    if isinstance(before, dict):
        return before.get("power_state")
    return None


def _after_power_state(result: dict[str, Any]) -> Any:
    if "after_power_state" in result:
        return result["after_power_state"]
    after = result.get("after")
    if isinstance(after, dict):
        return after.get("power_state")
    return None


if __name__ == "__main__":
    CLIENT.connect()
    mcp.run()
