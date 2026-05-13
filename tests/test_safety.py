import unittest

from safety import SafetyError, check_power_permission


CONFIG = {
    "safety": {
        "require_confirm_for_poweroff": True,
        "require_confirm_for_restart": True,
        "allow_power_ops": ["test-vm-01", "app-*"],
        "deny_power_ops": ["app-prod-*", "vcenter*"],
    }
}


class CheckPowerPermissionTests(unittest.TestCase):
    def test_allows_whitelisted_power_on_without_confirm(self) -> None:
        result = check_power_permission(
            "test-vm-01",
            action="power_on",
            confirm=False,
            config=CONFIG,
            unique=True,
        )

        self.assertEqual(
            result,
            {
                "allowed": True,
                "action": "power_on",
                "vm": "test-vm-01",
                "reason": "VM matched allow_power_ops",
            },
        )

    def test_requires_confirm_for_poweroff(self) -> None:
        with self.assertRaisesRegex(SafetyError, "confirm=true required"):
            check_power_permission(
                "test-vm-01",
                action="power_off",
                confirm=False,
                config=CONFIG,
                unique=True,
            )

    def test_deny_list_overrides_allow_list(self) -> None:
        with self.assertRaisesRegex(SafetyError, "VM matched deny_power_ops"):
            check_power_permission(
                "app-prod-01",
                action="restart_force",
                confirm=True,
                config=CONFIG,
                unique=True,
            )

    def test_rejects_empty_allow_list(self) -> None:
        config = {"safety": {"allow_power_ops": [], "deny_power_ops": []}}

        with self.assertRaisesRegex(SafetyError, "No allow_power_ops configured"):
            check_power_permission(
                "test-vm-01",
                action="power_on",
                confirm=False,
                config=config,
                unique=True,
            )

    def test_rejects_non_unique_vm(self) -> None:
        with self.assertRaisesRegex(SafetyError, "VM name duplicated"):
            check_power_permission(
                "test-vm-01",
                action="power_on",
                confirm=False,
                config=CONFIG,
                unique=False,
            )


if __name__ == "__main__":
    unittest.main()
