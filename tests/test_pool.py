from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from vsphere_client import VSphereClient, VSphereClientPool


MULTI_HOST_CONFIG = {
    "vsphere": {
        "hosts": {
            "vc-main": {
                "host": "vcenter.example.com",
                "port": 443,
                "username": "admin",
                "password_env": "VC_MAIN_PWD",
                "insecure_ssl": True,
            },
            "esxi-bj": {
                "host": "192.168.1.10",
                "port": 443,
                "username": "root",
                "password_env": "ESXI_BJ_PWD",
                "insecure_ssl": True,
            },
        }
    },
    "timeouts": {"task_timeout": 300},
    "safety": {"allow_power_ops": ["*"]},
}


class VSphereClientPoolBuildTests(unittest.TestCase):
    def test_builds_client_per_target(self) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        self.assertEqual(sorted(pool.target_names), ["esxi-bj", "vc-main"])

    def test_empty_hosts_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "vsphere.hosts is empty"):
            VSphereClientPool({"vsphere": {"hosts": {}}})

    def test_missing_hosts_key_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "vsphere.hosts is empty"):
            VSphereClientPool({"vsphere": {}})


class VSphereClientPoolGetTests(unittest.TestCase):
    def test_get_returns_client_for_valid_target(self) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        client = pool.get("vc-main")
        self.assertIsInstance(client, VSphereClient)

    def test_get_raises_key_error_for_unknown_target(self) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        with self.assertRaisesRegex(KeyError, "unknown.*available"):
            pool.get("unknown")

    def test_all_clients_returns_dict(self) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        clients = pool.all_clients()
        self.assertIsInstance(clients, dict)
        self.assertEqual(set(clients.keys()), {"vc-main", "esxi-bj"})


class VSphereClientPoolConnectTests(unittest.TestCase):
    @patch.object(VSphereClient, "connect")
    def test_connect_all_succeeds(self, mock_connect: MagicMock) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        pool.connect_all()
        self.assertEqual(mock_connect.call_count, 2)

    @patch.object(VSphereClient, "connect")
    @patch.object(VSphereClient, "disconnect")
    def test_connect_all_rollback_on_failure(
        self, mock_disconnect: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_connect.side_effect = [None, RuntimeError("connection failed")]
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        with self.assertRaises(RuntimeError):
            pool.connect_all()
        mock_disconnect.assert_called_once()

    @patch.object(VSphereClient, "disconnect")
    def test_disconnect_all(self, mock_disconnect: MagicMock) -> None:
        pool = VSphereClientPool(MULTI_HOST_CONFIG)
        pool.disconnect_all()
        self.assertEqual(mock_disconnect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
