from __future__ import annotations

import unittest

from pyVmomi import vim

from vm_power import PowerOperationError, power_off_vm_impl, power_on_vm_impl, restart_vm_force_impl


class Runtime:
    def __init__(self, power_state: object) -> None:
        self.powerState = power_state
        self.connectionState = "connected"
        self.host = None
        self.bootTime = None


class Guest:
    ipAddress = "192.0.2.10"
    toolsStatus = "toolsOk"


class Config:
    uuid = "uuid-1"
    hardware = type("Hardware", (), {"numCPU": 2, "memoryMB": 4096})()


class TaskInfo:
    def __init__(self) -> None:
        self.state = vim.TaskInfo.State.success
        self.error = None


class Task:
    def __init__(self) -> None:
        self.info = TaskInfo()


class FakeVM:
    def __init__(self, name: str, power_state: object) -> None:
        self.name = name
        self._moId = "vm-123"
        self.config = Config()
        self.runtime = Runtime(power_state)
        self.guest = Guest()
        self.calls: list[str] = []

    def PowerOnVM_Task(self) -> Task:
        self.calls.append("power_on")
        self.runtime.powerState = vim.VirtualMachinePowerState.poweredOn
        return Task()

    def PowerOffVM_Task(self) -> Task:
        self.calls.append("power_off")
        self.runtime.powerState = vim.VirtualMachinePowerState.poweredOff
        return Task()


class PowerLogicTests(unittest.TestCase):
    def test_power_on_vm_impl_powers_off_vm_on_and_confirms_state(self) -> None:
        vm = FakeVM("test-vm-01", vim.VirtualMachinePowerState.poweredOff)

        result = power_on_vm_impl(vm, task_timeout=1, state_timeout=1)

        self.assertEqual(result["result"], "powered_on")
        self.assertEqual(result["before_power_state"], "poweredOff")
        self.assertEqual(result["after_power_state"], "poweredOn")
        self.assertEqual(
            result["steps"],
            [
                "poweron_task_start",
                "poweron_task_success",
                "vm_powered_on_confirmed",
            ],
        )
        self.assertEqual(vm.calls, ["power_on"])

    def test_power_off_vm_impl_powers_on_vm_off_and_confirms_state(self) -> None:
        vm = FakeVM("test-vm-01", vim.VirtualMachinePowerState.poweredOn)

        result = power_off_vm_impl(vm, task_timeout=1, state_timeout=1)

        self.assertEqual(result["result"], "powered_off")
        self.assertEqual(result["before_power_state"], "poweredOn")
        self.assertEqual(result["after_power_state"], "poweredOff")
        self.assertEqual(
            result["steps"],
            [
                "poweroff_task_start",
                "poweroff_task_success",
                "vm_powered_off_confirmed",
            ],
        )
        self.assertEqual(vm.calls, ["power_off"])

    def test_restart_vm_force_powers_off_then_on(self) -> None:
        vm = FakeVM("test-vm-01", vim.VirtualMachinePowerState.poweredOn)

        result = restart_vm_force_impl(
            vm,
            confirm=True,
            poweroff_task_timeout=1,
            poweroff_state_timeout=1,
            poweron_task_timeout=1,
            poweron_state_timeout=1,
            boot_wait=0,
        )

        self.assertEqual(result["result"], "restarted")
        self.assertEqual(result["before"]["power_state"], "poweredOn")
        self.assertEqual(result["after"]["power_state"], "poweredOn")
        self.assertEqual(
            result["steps"],
            [
                "poweroff_task_start",
                "poweroff_task_success",
                "vm_powered_off_confirmed",
                "poweron_task_start",
                "poweron_task_success",
                "vm_powered_on_confirmed",
            ],
        )
        self.assertEqual(vm.calls, ["power_off", "power_on"])

    def test_restart_vm_force_starts_powered_off_vm_without_poweroff(self) -> None:
        vm = FakeVM("test-vm-01", vim.VirtualMachinePowerState.poweredOff)

        result = restart_vm_force_impl(
            vm,
            confirm=True,
            poweroff_task_timeout=1,
            poweroff_state_timeout=1,
            poweron_task_timeout=1,
            poweron_state_timeout=1,
            boot_wait=0,
        )

        self.assertEqual(result["steps"][0], "already_powered_off_skip_poweroff")
        self.assertEqual(vm.calls, ["power_on"])

    def test_restart_vm_force_rejects_suspended_vm(self) -> None:
        vm = FakeVM("test-vm-01", vim.VirtualMachinePowerState.suspended)

        with self.assertRaisesRegex(PowerOperationError, "manual handling recommended"):
            restart_vm_force_impl(
                vm,
                confirm=True,
                poweroff_task_timeout=1,
                poweroff_state_timeout=1,
                poweron_task_timeout=1,
                poweron_state_timeout=1,
                boot_wait=0,
            )


if __name__ == "__main__":
    unittest.main()
