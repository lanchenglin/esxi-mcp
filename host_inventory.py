from __future__ import annotations

from typing import Any

from pyVmomi import vim


class HostInventoryError(RuntimeError):
    """Raised when host inventory lookup fails."""


def list_hosts(
    service_instance: vim.ServiceInstance,
    keyword: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lists ESXi hosts with optional name filtering.

    Args:
        service_instance: Connected pyVmomi service instance.
        keyword: Optional case-insensitive host name substring.

    Returns:
        Dictionary with an items list.
    """
    items: list[dict[str, Any]] = []
    for host in _iter_hosts(service_instance):
        name = getattr(host, "name", "")
        if keyword and keyword.lower() not in name.lower():
            continue
        summary = getattr(host, "summary", None)
        hardware = getattr(summary, "hardware", None) if summary else None
        runtime = getattr(host, "runtime", None)
        items.append(
            {
                "name": name,
                "connection_state": _enum_value(getattr(runtime, "connectionState", None) if runtime else None),
                "power_state": _enum_value(getattr(runtime, "powerState", None) if runtime else None),
                "maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)) if runtime else None,
                "cpu_cores": getattr(hardware, "numCpuCores", None) if hardware else None,
                "memory_total_gb": _bytes_to_gb(getattr(hardware, "memorySize", None) if hardware else None),
            }
        )
    return {"items": items}


def get_host_resource(service_instance: vim.ServiceInstance, host_name: str) -> dict[str, Any]:
    """Returns CPU, memory, and VM count for an ESXi host.

    Args:
        service_instance: Connected pyVmomi service instance.
        host_name: Exact host name.

    Returns:
        Host resource dictionary.

    Raises:
        HostInventoryError: If the host is not found.
    """
    host = _find_host(service_instance, host_name)
    summary = getattr(host, "summary", None)
    hardware = getattr(summary, "hardware", None) if summary else None
    quick_stats = getattr(summary, "quickStats", None) if summary else None
    runtime = getattr(host, "runtime", None)
    vm_list = list(getattr(host, "vm", []) or [])

    return {
        "name": getattr(host, "name", None),
        "connection_state": _enum_value(getattr(runtime, "connectionState", None) if runtime else None),
        "maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)) if runtime else None,
        "cpu_total_mhz": _cpu_total_mhz(hardware),
        "cpu_used_mhz": getattr(quick_stats, "overallCpuUsage", None) if quick_stats else None,
        "memory_total_mb": _bytes_to_mb(getattr(hardware, "memorySize", None) if hardware else None),
        "memory_used_mb": getattr(quick_stats, "overallMemoryUsage", None) if quick_stats else None,
        "vm_count": len(vm_list),
    }


def _find_host(service_instance: vim.ServiceInstance, host_name: str) -> vim.HostSystem:
    matches = [host for host in _iter_hosts(service_instance) if host.name == host_name]
    if not matches:
        raise HostInventoryError(f"Host not found: {host_name}")
    if len(matches) > 1:
        raise HostInventoryError(f"Host name duplicated: {host_name}")
    return matches[0]


def _iter_hosts(service_instance: vim.ServiceInstance) -> list[vim.HostSystem]:
    content = service_instance.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _cpu_total_mhz(hardware: Any) -> int | None:
    if hardware is None:
        return None
    hz = getattr(hardware, "cpuMhz", None)
    cores = getattr(hardware, "numCpuCores", None)
    if hz is None or cores is None:
        return None
    return int(hz) * int(cores)


def _bytes_to_mb(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value // 1024 // 1024)


def _bytes_to_gb(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value // 1024 // 1024 // 1024)


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
