from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyVmomi import vim

import server
from safety import SafetyError


class Runtime:
    powerState = vim.VirtualMachinePowerState.poweredOn
    connectionState = "connected"
    host = None
    bootTime = None


class Guest:
    ipAddress = "192.0.2.10"
    toolsStatus = "toolsOk"


class Config:
    instanceUuid = "instance-uuid-1"
    uuid = "bios-uuid-1"
    hardware = type("Hardware", (), {"numCPU": 2, "memoryMB": 4096})()


class FakeVM:
    name = "test-vm-01"
    _moId = "vm-123"
    runtime = Runtime()
    guest = Guest()
    config = Config()


class ServerWriteOperationTests(unittest.TestCase):
    def test_successful_write_operation_records_success_audit(self) -> None:
        vm = FakeVM()
        audit_entries: list[dict[str, object]] = []

        with _patched_server(vm, audit_entries):
            result = server._run_write_operation(
                "power_on_vm",
                "vc-main",
                vm.name,
                None,
                None,
                "power_on",
                False,
                lambda resolved_vm: {
                    "vm": resolved_vm.name,
                    "before_power_state": "poweredOff",
                    "after_power_state": "poweredOn",
                    "result": "powered_on",
                },
                0.0,
            )

        self.assertEqual(result["result"], "powered_on")
        self.assertEqual(audit_entries[0]["result"], "success")
        self.assertEqual(audit_entries[0]["tool"], "power_on_vm")
        self.assertEqual(audit_entries[0]["vm"], "test-vm-01")
        self.assertEqual(audit_entries[0]["before_power_state"], "poweredOff")
        self.assertEqual(audit_entries[0]["after_power_state"], "poweredOn")

    def test_safety_error_records_blocked_audit(self) -> None:
        vm = FakeVM()
        audit_entries: list[dict[str, object]] = []

        with _patched_server(vm, audit_entries, safety_error=SafetyError("VM matched deny_power_ops")):
            with self.assertRaisesRegex(SafetyError, "VM matched deny_power_ops"):
                server._run_write_operation(
                    "power_off_vm",
                    "vc-main",
                    vm.name,
                    None,
                    None,
                    "power_off",
                    True,
                    lambda resolved_vm: {"result": "powered_off"},
                    0.0,
                )

        self.assertEqual(audit_entries[0]["result"], "blocked")
        self.assertEqual(audit_entries[0]["reason"], "VM matched deny_power_ops")

    def test_operation_error_records_failure_audit(self) -> None:
        vm = FakeVM()
        audit_entries: list[dict[str, object]] = []

        def fail_operation(_: FakeVM) -> dict[str, object]:
            raise RuntimeError("TaskInProgress: another task is running")

        with _patched_server(vm, audit_entries):
            with self.assertRaisesRegex(RuntimeError, "TaskInProgress"):
                server._run_write_operation(
                    "restart_vm_force",
                    "vc-main",
                    vm.name,
                    None,
                    None,
                    "restart_force",
                    True,
                    fail_operation,
                    0.0,
                )

        self.assertEqual(audit_entries[0]["result"], "failure")
        self.assertIn("TaskInProgress", str(audit_entries[0]["reason"]))

    def test_duplicate_name_blocks_write_and_records_audit(self) -> None:
        vm = FakeVM()
        audit_entries: list[dict[str, object]] = []

        with _patched_server(vm, audit_entries, unique=False):
            with self.assertRaisesRegex(SafetyError, "VM name duplicated"):
                server._run_write_operation(
                    "power_on_vm",
                    "vc-main",
                    vm.name,
                    None,
                    None,
                    "power_on",
                    False,
                    lambda resolved_vm: {"result": "powered_on"},
                    0.0,
                )

        self.assertEqual(audit_entries[0]["result"], "blocked")
        self.assertIn("VM name duplicated", str(audit_entries[0]["reason"]))

    def test_moid_lookup_checks_safety_against_resolved_vm_name(self) -> None:
        vm = FakeVM()
        audit_entries: list[dict[str, object]] = []
        safety_calls: list[tuple[str, str, bool, bool]] = []

        def capture_safety(vm_name: str, action: str, confirm: bool, config: dict[str, object], unique: bool) -> dict[str, object]:
            safety_calls.append((vm_name, action, confirm, unique))
            return {"allowed": True}

        with _patched_server(vm, audit_entries, safety_func=capture_safety):
            server._run_write_operation(
                "power_on_vm",
                "vc-main",
                None,
                None,
                "vm-123",
                "power_on",
                False,
                lambda resolved_vm: {
                    "result": "already_powered_on",
                    "before_power_state": "poweredOn",
                    "after_power_state": "poweredOn",
                },
                0.0,
            )

        self.assertEqual(safety_calls, [("test-vm-01", "power_on", False, True)])


def _patched_server(
    vm: FakeVM,
    audit_entries: list[dict[str, object]],
    safety_error: SafetyError | None = None,
    unique: bool = True,
    safety_func: object | None = None,
):
    def safety(vm_name: str, action: str, confirm: bool, config: dict[str, object], unique: bool) -> dict[str, object]:
        if safety_error is not None:
            raise safety_error
        if not unique:
            raise SafetyError(f"VM name duplicated: {vm_name}; use uuid or moid")
        return {"allowed": True, "vm": vm_name, "action": action, "unique": unique}

    fake_client = MagicMock()
    fake_client.get_service_instance.return_value = object()

    return patch.multiple(
        server,
        POOL=MagicMock(get=MagicMock(return_value=fake_client)),
        find_vm=lambda service_instance, vm_name=None, uuid=None, moid=None: vm,
        is_vm_name_unique=lambda service_instance, vm_name: unique,
        check_power_permission=safety_func or safety,
        write_audit_log=lambda config, entry: audit_entries.append(entry),
    )


if __name__ == "__main__":
    unittest.main()
