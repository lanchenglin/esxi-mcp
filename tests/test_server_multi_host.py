from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import server
from vsphere_client import VSphereClient, VSphereClientPool


class FakeClient:
    def __init__(self, target: str) -> None:
        self.target = target
        self._si = MagicMock()

    def get_service_instance(self) -> MagicMock:
        return self._si


def _make_pool(targets: list[str]) -> VSphereClientPool:
    pool = MagicMock(spec=VSphereClientPool)
    pool.target_names = targets
    clients = {t: FakeClient(t) for t in targets}
    pool.get.side_effect = lambda t: clients[t]
    pool.all_clients.return_value = clients
    return pool


class MultiHostReadTests(unittest.TestCase):
    @patch("server.list_vms_impl")
    def test_list_vms_without_target_merges_all(
        self, mock_list_vms: MagicMock
    ) -> None:
        mock_list_vms.side_effect = [
            {"items": [{"name": "vm-a", "power_state": "poweredOn"}]},
            {"items": [{"name": "vm-b", "power_state": "poweredOff"}]},
        ]
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.list_vms()

        self.assertEqual(len(result["items"]), 2)
        sources = [item["source"] for item in result["items"]]
        self.assertIn("vc-main", sources)
        self.assertIn("esxi-bj", sources)

    @patch("server.list_vms_impl")
    def test_list_vms_with_target_returns_single_source(
        self, mock_list_vms: MagicMock
    ) -> None:
        mock_list_vms.return_value = {"items": [{"name": "vm-a"}]}
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.list_vms(target="vc-main")

        self.assertEqual(result["items"][0]["source"], "vc-main")

    @patch("server.list_vms_impl")
    def test_list_vms_partial_failure_returns_errors(
        self, mock_list_vms: MagicMock
    ) -> None:
        def side_effect(si, **kwargs):
            if si is not pool.get("esxi-bj")._si:
                return {"items": [{"name": "vm-a"}]}
            raise RuntimeError("Connection refused")

        mock_list_vms.side_effect = side_effect
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.list_vms()

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["target"], "esxi-bj")

    @patch("server.get_vm_status_impl")
    def test_get_vm_status_without_target_returns_all_matches(
        self, mock_get_status: MagicMock
    ) -> None:
        mock_get_status.side_effect = [
            {"name": "vm-a", "power_state": "poweredOn"},
            {"name": "vm-a", "power_state": "poweredOff"},
        ]
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.get_vm_status(vm_name="vm-a")

        self.assertEqual(len(result["items"]), 2)

    @patch("server.list_hosts_impl")
    def test_list_hosts_without_target_merges_all(
        self, mock_list_hosts: MagicMock
    ) -> None:
        mock_list_hosts.side_effect = [
            {"items": [{"name": "host-a"}]},
            {"items": [{"name": "host-b"}]},
        ]
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.list_hosts()

        self.assertEqual(len(result["items"]), 2)

    @patch("server.get_host_resource_impl")
    def test_get_host_resource_without_target_merges(
        self, mock_get_resource: MagicMock
    ) -> None:
        mock_get_resource.side_effect = [
            {"name": "host-a", "cpu_cores": 8},
            {"name": "host-a", "cpu_cores": 16},
        ]
        pool = _make_pool(["vc-main", "esxi-bj"])

        with patch.object(server, "POOL", pool):
            result = server.get_host_resource(host_name="host-a")

        self.assertEqual(len(result["items"]), 2)


class MultiHostWriteTests(unittest.TestCase):
    def test_write_operation_without_target_raises_value_error(self) -> None:
        pool = _make_pool(["vc-main"])

        with patch.object(server, "POOL", pool):
            with self.assertRaisesRegex(ValueError, "target is required"):
                server.power_on_vm(vm_name="test-vm-01")

    def test_write_operation_with_invalid_target_raises_key_error(self) -> None:
        pool = _make_pool(["vc-main"])

        with patch.object(server, "POOL", pool):
            with self.assertRaises(KeyError):
                server.power_on_vm(vm_name="test-vm-01", target="nonexistent")


if __name__ == "__main__":
    unittest.main()
