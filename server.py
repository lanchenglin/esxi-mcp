from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from pyVmomi import vim

from audit import write_audit_log
from host_inventory import get_host_resource as get_host_resource_impl
from host_inventory import get_host_health as get_host_health_impl
from host_inventory import get_host_storage as get_host_storage_impl
from host_inventory import inspect_hosts_single as inspect_hosts_single_impl
from host_inventory import list_hosts as list_hosts_impl
from safety import SafetyError, check_power_permission
from vm_inventory import find_vm, get_vm_status as get_vm_status_impl
from vm_inventory import is_vm_name_unique, list_vms as list_vms_impl
from vm_power import power_off_vm_impl, power_on_vm_impl, restart_vm_force_impl
from vsphere_client import VSphereClientPool, load_config


CONFIG = load_config()
POOL = VSphereClientPool(CONFIG)
mcp = FastMCP(CONFIG.get("mcp", {}).get("name", "esxi-power-mcp"))


def _parallel_read(
    func: Callable[..., dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    """Runs func on all targets in parallel, merges results with source."""
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    clients = POOL.all_clients()

    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        futures = {
            executor.submit(func, client.get_service_instance(), **kwargs): target
            for target, client in clients.items()
        }
        for future in as_completed(futures):
            target = futures[future]
            try:
                result = future.result()
                if "items" in result:
                    for item in result["items"]:
                        item["source"] = target
                        items.append(item)
                else:
                    items.append({**result, "source": target})
            except Exception as exc:
                errors.append({"target": target, "error": str(exc)})

    return {"items": items, "errors": errors}


def _single_read(
    target: str, func: Callable[..., dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    """Runs func on a single target, adds source field."""
    client = POOL.get(target)
    result = func(client.get_service_instance(), **kwargs)
    if "items" in result:
        for item in result["items"]:
            item["source"] = target
        return result
    return {**result, "source": target}


@mcp.tool()
def list_vms(
    keyword: str | None = None,
    power_state: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Lists VMs, optionally filtered by keyword, power_state, and target."""
    if target is not None:
        return _single_read(target, list_vms_impl, keyword=keyword, power_state=power_state)
    return _parallel_read(list_vms_impl, keyword=keyword, power_state=power_state)


@mcp.tool()
def get_vm_status(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Gets detailed status for one VM by moid, uuid, or unique name."""
    if target is not None:
        return _single_read(target, get_vm_status_impl, vm_name=vm_name, uuid=uuid, moid=moid)
    return _parallel_read(get_vm_status_impl, vm_name=vm_name, uuid=uuid, moid=moid)


@mcp.tool()
def list_hosts(
    keyword: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Lists ESXi hosts, optionally filtered by keyword and target."""
    if target is not None:
        return _single_read(target, list_hosts_impl, keyword=keyword)
    return _parallel_read(list_hosts_impl, keyword=keyword)


@mcp.tool()
def get_host_resource(
    host_name: str,
    target: str | None = None,
) -> dict[str, Any]:
    """Gets CPU, memory, and VM-count resource summary for one host."""
    if target is not None:
        return _single_read(target, get_host_resource_impl, host_name=host_name)
    return _parallel_read(get_host_resource_impl, host_name=host_name)


@mcp.tool()
def get_host_health(
    host_name: str,
    target: str | None = None,
) -> dict[str, Any]:
    """Returns comprehensive health status for one ESXi host."""
    if target is not None:
        return _single_read(target, get_host_health_impl, host_name=host_name)
    return _parallel_read(get_host_health_impl, host_name=host_name)


@mcp.tool()
def get_host_storage(
    host_name: str,
    target: str | None = None,
) -> dict[str, Any]:
    """Returns storage/Datastore usage for one ESXi host."""
    if target is not None:
        return _single_read(target, get_host_storage_impl, host_name=host_name)
    return _parallel_read(get_host_storage_impl, host_name=host_name)


@mcp.tool()
def inspect_hosts(
    status_filter: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Batch inspection of host health across all or one target."""
    result = _parallel_read(inspect_hosts_single_impl, status_filter=status_filter)
    green = sum(1 for i in result["items"] if i.get("overall_status") == "green")
    yellow = sum(1 for i in result["items"] if i.get("overall_status") == "yellow")
    red = sum(1 for i in result["items"] if i.get("overall_status") == "red")
    result["summary"] = {
        "total_hosts": len(result["items"]),
        "green": green,
        "yellow": yellow,
        "red": red,
    }
    return result


@mcp.tool()
def power_on_vm(
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
    target: str = "",
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Powers on a VM on a specific target."""
    _require_target(target)
    start = time.monotonic()
    return _run_write_operation(
        "power_on_vm",
        target,
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
    target: str = "",
    confirm: bool = False,
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Force-powers off a VM on a specific target; confirm=true is required."""
    _require_target(target)
    start = time.monotonic()
    return _run_write_operation(
        "power_off_vm",
        target,
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
    target: str = "",
    confirm: bool = False,
    poweroff_task_timeout: int = 300,
    poweroff_state_timeout: int = 900,
    poweron_task_timeout: int = 300,
    poweron_state_timeout: int = 900,
    boot_wait: int = 30,
) -> dict[str, Any]:
    """Force-restarts a VM on a specific target; confirm=true is required."""
    _require_target(target)
    start = time.monotonic()
    return _run_write_operation(
        "restart_vm_force",
        target,
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


def _require_target(target: str) -> None:
    """Validates that target is provided and valid."""
    if not target:
        raise ValueError("target is required for write operations")
    POOL.get(target)


def _run_write_operation(
    tool: str,
    target: str,
    vm_name: str | None,
    uuid: str | None,
    moid: str | None,
    action: str,
    confirm: bool,
    operation: Callable[[vim.VirtualMachine], dict[str, Any]],
    start: float,
) -> dict[str, Any]:
    client = POOL.get(target)
    service_instance = client.get_service_instance()
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
                "target": target,
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
                "target": target,
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
                "target": target,
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
    import os

    POOL.connect_all()
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    if transport in ("sse", "streamable-http"):
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.getenv("MCP_PORT", "8001"))
    mcp.run(transport=transport)
