from __future__ import annotations

import time
from typing import Any

from pyVmomi import vim, vmodl

from vm_inventory import refresh_vm_status


class PowerOperationError(RuntimeError):
    """Raised when a VM power operation fails."""


def wait_task(task: vim.Task, timeout: int = 300, interval: int = 2) -> bool:
    """Waits for a vSphere task to complete successfully.

    Args:
        task: pyVmomi task object.
        timeout: Maximum seconds to wait.
        interval: Poll interval in seconds.

    Returns:
        True when the task succeeds.

    Raises:
        TimeoutError: If the task does not finish before timeout.
        PowerOperationError: If the task enters error state.
    """
    start = time.monotonic()
    while True:
        state = task.info.state
        if state == vim.TaskInfo.State.success:
            return True
        if state == vim.TaskInfo.State.error:
            error = task.info.error
            raise PowerOperationError(f"Task failed: {_fault_message(error)}")
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"Timedout waiting for vSphere task after {timeout}s")
        time.sleep(interval)


def wait_power_state(
    vm: vim.VirtualMachine,
    target_state: vim.VirtualMachinePowerState,
    timeout: int = 900,
    interval: int = 5,
) -> bool:
    """Waits for a VM runtime power state.

    Args:
        vm: pyVmomi VM object.
        target_state: Desired vim.VirtualMachinePowerState.
        timeout: Maximum seconds to wait.
        interval: Poll interval in seconds.

    Returns:
        True when the VM reaches target_state.

    Raises:
        TimeoutError: If the state is not reached before timeout.
    """
    start = time.monotonic()
    while True:
        current_state = vm.runtime.powerState
        if current_state == target_state:
            return True
        if time.monotonic() - start > timeout:
            raise TimeoutError(
                f"Timedout waiting for VM power state: vm={vm.name}, "
                f"current={_state_value(current_state)}, target={_state_value(target_state)}"
            )
        time.sleep(interval)


def power_on_vm_impl(
    vm: vim.VirtualMachine,
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Powers on a VM and confirms runtime state.

    Args:
        vm: pyVmomi VM object.
        task_timeout: Task wait timeout in seconds.
        state_timeout: Power-state wait timeout in seconds.

    Returns:
        Operation result dictionary.
    """
    before = _state_value(vm.runtime.powerState)
    result = {
        "vm": vm.name,
        "moid": getattr(vm, "_moId", None),
        "before_power_state": before,
        "steps": [],
    }

    if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
        result["result"] = "already_powered_on"
        result["after_power_state"] = before
        result["steps"].append("already_powered_on")
        return result
    if vm.runtime.powerState == vim.VirtualMachinePowerState.suspended:
        raise PowerOperationError(f"InvalidPowerState: VM is suspended, manual handling recommended: {vm.name}")
    if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOff:
        raise PowerOperationError(f"InvalidPowerState: unsupported VM power state: {before}")

    result["steps"].append("poweron_task_start")
    task = _call_power_task(vm.PowerOnVM_Task)
    wait_task(task, timeout=task_timeout)
    result["steps"].append("poweron_task_success")
    wait_power_state(vm, vim.VirtualMachinePowerState.poweredOn, timeout=state_timeout)
    result["steps"].append("vm_powered_on_confirmed")
    result["after_power_state"] = _state_value(vm.runtime.powerState)
    result["result"] = "powered_on"
    return result


def power_off_vm_impl(
    vm: vim.VirtualMachine,
    task_timeout: int = 300,
    state_timeout: int = 900,
) -> dict[str, Any]:
    """Powers off a VM and confirms runtime state.

    Args:
        vm: pyVmomi VM object.
        task_timeout: Task wait timeout in seconds.
        state_timeout: Power-state wait timeout in seconds.

    Returns:
        Operation result dictionary.
    """
    before = _state_value(vm.runtime.powerState)
    result = {
        "vm": vm.name,
        "moid": getattr(vm, "_moId", None),
        "before_power_state": before,
        "steps": [],
    }

    if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOff:
        result["result"] = "already_powered_off"
        result["after_power_state"] = before
        result["steps"].append("already_powered_off")
        return result
    if vm.runtime.powerState == vim.VirtualMachinePowerState.suspended:
        raise PowerOperationError(f"InvalidPowerState: VM is suspended, manual handling recommended: {vm.name}")
    if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
        raise PowerOperationError(f"InvalidPowerState: unsupported VM power state: {before}")

    result["steps"].append("poweroff_task_start")
    task = _call_power_task(vm.PowerOffVM_Task)
    wait_task(task, timeout=task_timeout)
    result["steps"].append("poweroff_task_success")
    wait_power_state(vm, vim.VirtualMachinePowerState.poweredOff, timeout=state_timeout)
    result["steps"].append("vm_powered_off_confirmed")
    result["after_power_state"] = _state_value(vm.runtime.powerState)
    result["result"] = "powered_off"
    return result


def restart_vm_force_impl(
    vm: vim.VirtualMachine,
    confirm: bool = False,
    poweroff_task_timeout: int = 300,
    poweroff_state_timeout: int = 900,
    poweron_task_timeout: int = 300,
    poweron_state_timeout: int = 900,
    boot_wait: int = 30,
) -> dict[str, Any]:
    """Force-restarts a VM with task and runtime-state confirmation.

    Args:
        vm: pyVmomi VM object.
        confirm: Must be true for forced restart.
        poweroff_task_timeout: Power-off task timeout in seconds.
        poweroff_state_timeout: Power-off state timeout in seconds.
        poweron_task_timeout: Power-on task timeout in seconds.
        poweron_state_timeout: Power-on state timeout in seconds.
        boot_wait: Extra seconds to wait after poweredOn confirmation.

    Returns:
        Operation result dictionary.

    Raises:
        PowerOperationError: If confirm is false or the VM is suspended.
    """
    if not confirm:
        raise PowerOperationError("restart_vm_force confirm=true required")

    result = {
        "vm": vm.name,
        "moid": getattr(vm, "_moId", None),
        "before": refresh_vm_status(vm),
        "steps": [],
    }
    current_state = vm.runtime.powerState

    if current_state == vim.VirtualMachinePowerState.poweredOn:
        result["steps"].append("poweroff_task_start")
        task = _call_power_task(vm.PowerOffVM_Task)
        wait_task(task, timeout=poweroff_task_timeout)
        result["steps"].append("poweroff_task_success")
        wait_power_state(vm, vim.VirtualMachinePowerState.poweredOff, timeout=poweroff_state_timeout)
        result["steps"].append("vm_powered_off_confirmed")
    elif current_state == vim.VirtualMachinePowerState.poweredOff:
        result["steps"].append("already_powered_off_skip_poweroff")
    elif current_state == vim.VirtualMachinePowerState.suspended:
        raise PowerOperationError(f"InvalidPowerState: VM is suspended, manual handling recommended: {vm.name}")
    else:
        raise PowerOperationError(f"InvalidPowerState: unsupported VM power state: {_state_value(current_state)}")

    result["steps"].append("poweron_task_start")
    task = _call_power_task(vm.PowerOnVM_Task)
    wait_task(task, timeout=poweron_task_timeout)
    result["steps"].append("poweron_task_success")
    wait_power_state(vm, vim.VirtualMachinePowerState.poweredOn, timeout=poweron_state_timeout)
    result["steps"].append("vm_powered_on_confirmed")

    if boot_wait > 0:
        time.sleep(boot_wait)
        result["steps"].append("boot_wait_finished")

    result["after"] = refresh_vm_status(vm)
    result["result"] = "restarted"
    return result


def _call_power_task(callback: Any) -> vim.Task:
    try:
        return callback()
    except vim.fault.TaskInProgress as exc:
        raise PowerOperationError(f"TaskInProgress: {_fault_message(exc)}") from exc
    except vim.fault.InvalidPowerState as exc:
        raise PowerOperationError(f"InvalidPowerState: {_fault_message(exc)}") from exc
    except vim.fault.NoPermission as exc:
        raise PowerOperationError(f"NoPermission: {_fault_message(exc)}") from exc
    except vmodl.MethodFault as exc:
        raise PowerOperationError(_fault_message(exc)) from exc


def _fault_message(error: Any) -> str:
    if error is None:
        return "unknown error"
    message = getattr(error, "msg", None) or getattr(error, "localizedMessage", None)
    if message:
        return str(message)
    return str(error)


def _state_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
