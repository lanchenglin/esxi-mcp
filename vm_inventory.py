from __future__ import annotations

from datetime import datetime
from typing import Any

from pyVmomi import vim


class VMInventoryError(RuntimeError):
    """Raised when VM inventory lookup fails."""


class VMNotFoundError(VMInventoryError):
    """Raised when a VM cannot be found."""


class VMDuplicatedError(VMInventoryError):
    """Raised when a VM name resolves to multiple VMs."""


def list_vms(
    service_instance: vim.ServiceInstance,
    keyword: str | None = None,
    power_state: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lists virtual machines with optional name and power-state filters.

    Args:
        service_instance: Connected pyVmomi service instance.
        keyword: Optional case-insensitive VM name substring.
        power_state: Optional power state: poweredOn, poweredOff, or suspended.

    Returns:
        Dictionary with an items list.
    """
    items: list[dict[str, Any]] = []
    for vm in _iter_objects(service_instance, vim.VirtualMachine):
        try:
            status = refresh_vm_status(vm)
        except Exception as exc:
            status = {
                "name": getattr(vm, "name", None),
                "moid": getattr(vm, "_moId", None),
                "uuid": None,
                "power_state": None,
                "host": None,
                "ip": None,
                "cpu": None,
                "memory_mb": None,
                "error": str(exc),
            }

        name = str(status.get("name") or "")
        current_power_state = status.get("power_state")
        if keyword and keyword.lower() not in name.lower():
            continue
        if power_state and current_power_state != power_state:
            continue

        items.append(
            {
                "name": status.get("name"),
                "moid": status.get("moid"),
                "uuid": status.get("uuid"),
                "power_state": current_power_state,
                "host": status.get("host"),
                "ip": status.get("ip"),
                "cpu": status.get("cpu"),
                "memory_mb": status.get("memory_mb"),
                **({"error": status["error"]} if "error" in status else {}),
            }
        )
    return {"items": items}


def get_vm_status(
    service_instance: vim.ServiceInstance,
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
) -> dict[str, Any]:
    """Returns detailed status for a single VM.

    Args:
        service_instance: Connected pyVmomi service instance.
        vm_name: VM name, used only when moid and uuid are not provided.
        uuid: VM instance UUID or BIOS UUID.
        moid: Managed object ID.

    Returns:
        VM status dictionary.
    """
    vm = find_vm(service_instance, vm_name=vm_name, uuid=uuid, moid=moid)
    return refresh_vm_status(vm)


def find_vm(
    service_instance: vim.ServiceInstance,
    vm_name: str | None = None,
    uuid: str | None = None,
    moid: str | None = None,
) -> vim.VirtualMachine:
    """Finds a VM by moid, uuid, or unique name in that priority order.

    Args:
        service_instance: Connected pyVmomi service instance.
        vm_name: VM name.
        uuid: VM instance UUID or BIOS UUID.
        moid: Managed object ID.

    Returns:
        Matching VM object.

    Raises:
        VMNotFoundError: If no VM matches.
        VMDuplicatedError: If vm_name matches more than one VM.
    """
    if moid:
        for vm in _iter_objects(service_instance, vim.VirtualMachine):
            if getattr(vm, "_moId", None) == moid:
                return vm
        raise VMNotFoundError(f"VM not found by moid: {moid}")

    if uuid:
        content = service_instance.RetrieveContent()
        search_index = content.searchIndex
        for instance_uuid in (True, False):
            vm = search_index.FindByUuid(None, uuid, True, instance_uuid)
            if vm is not None:
                return vm
        raise VMNotFoundError(f"VM not found by uuid: {uuid}")

    if vm_name:
        matches = [vm for vm in _iter_objects(service_instance, vim.VirtualMachine) if vm.name == vm_name]
        if not matches:
            raise VMNotFoundError(f"VM not found by name: {vm_name}")
        if len(matches) > 1:
            raise VMDuplicatedError(f"VM name duplicated: {vm_name}; use uuid or moid")
        return matches[0]

    raise VMNotFoundError("VM not found: provide moid, uuid, or vm_name")


def refresh_vm_status(vm: vim.VirtualMachine) -> dict[str, Any]:
    """Builds a VM status dictionary from pyVmomi runtime fields.

    Args:
        vm: pyVmomi virtual machine object.

    Returns:
        VM status dictionary.
    """
    config = getattr(vm, "config", None)
    runtime = getattr(vm, "runtime", None)
    guest = getattr(vm, "guest", None)
    hardware = getattr(config, "hardware", None) if config else None
    host = getattr(runtime, "host", None) if runtime else None
    boot_time = getattr(runtime, "bootTime", None) if runtime else None

    return {
        "name": getattr(vm, "name", None),
        "moid": getattr(vm, "_moId", None),
        "uuid": _first_non_empty(
            getattr(config, "instanceUuid", None) if config else None,
            getattr(config, "uuid", None) if config else None,
        ),
        "power_state": _enum_value(getattr(runtime, "powerState", None) if runtime else None),
        "connection_state": _enum_value(getattr(runtime, "connectionState", None) if runtime else None),
        "host": getattr(host, "name", None) if host else None,
        "ip": getattr(guest, "ipAddress", None) if guest else None,
        "tools_status": _enum_value(getattr(guest, "toolsStatus", None) if guest else None),
        "boot_time": _format_datetime(boot_time),
        "cpu": getattr(hardware, "numCPU", None) if hardware else None,
        "memory_mb": getattr(hardware, "memoryMB", None) if hardware else None,
    }


def is_vm_name_unique(service_instance: vim.ServiceInstance, vm_name: str) -> bool:
    """Checks whether a VM name resolves to exactly one VM.

    Args:
        service_instance: Connected pyVmomi service instance.
        vm_name: VM name to check.

    Returns:
        True when exactly one VM has the supplied name.
    """
    return sum(1 for vm in _iter_objects(service_instance, vim.VirtualMachine) if vm.name == vm_name) == 1


def _iter_objects(service_instance: vim.ServiceInstance, vim_type: type[Any]) -> list[Any]:
    content = service_instance.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim_type], True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None
