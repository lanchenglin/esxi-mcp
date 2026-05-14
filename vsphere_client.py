from __future__ import annotations

import atexit
import os
import socket
import ssl
import threading
from pathlib import Path
from typing import Any

import yaml
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")
CONNECT_TIMEOUT_SECONDS = 30


class VSphereConfigError(RuntimeError):
    """Raised when vSphere configuration is invalid."""


class VSphereClient:
    """Manages a pyVmomi connection to vCenter or a direct ESXi host."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initializes the client from a loaded configuration dictionary.

        Args:
            config: Parsed config.yaml contents.
        """
        self.config = config
        self._service_instance: vim.ServiceInstance | None = None
        self._register_atexit: bool = True
        self._connect_lock = threading.Lock()

    @classmethod
    def from_config_file(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "VSphereClient":
        """Creates a client from a YAML config file.

        Args:
            path: Path to config.yaml.

        Returns:
            Configured vSphere client.
        """
        return cls(load_config(path))

    def connect(self) -> vim.ServiceInstance:
        """Connects to vCenter or ESXi and returns the service instance.

        Returns:
            pyVmomi service instance.

        Raises:
            VSphereConfigError: If required config or password env var is missing.
            RuntimeError: If SmartConnect fails.
        """
        if self._service_instance is not None:
            return self._service_instance

        with self._connect_lock:
            if self._service_instance is not None:
                return self._service_instance

            vsphere_config = self.config.get("vsphere", {})
            host = _required_string(vsphere_config, "host")
            username = _required_string(vsphere_config, "username")
            password = vsphere_config.get("password")
            if not password:
                password_env = _required_string(vsphere_config, "password_env")
                password = os.getenv(password_env)
                if not password:
                    raise VSphereConfigError(f"Environment variable {password_env} is required")

            port = int(vsphere_config.get("port", 443))
            context = _build_ssl_context(bool(vsphere_config.get("insecure_ssl", True)))
            previous_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(CONNECT_TIMEOUT_SECONDS)
            try:
                self._service_instance = SmartConnect(
                    host=host,
                    user=username,
                    pwd=password,
                    port=port,
                    sslContext=context,
                )
            except vim.fault.InvalidLogin as exc:
                raise RuntimeError(f"NoPermission or invalid login for vSphere user {username}") from exc
            except Exception as exc:
                raise RuntimeError(f"Failed to connect to vSphere host {host}:{port}: {exc}") from exc
            finally:
                socket.setdefaulttimeout(previous_timeout)

            if self._register_atexit:
                atexit.register(self.disconnect)
            return self._service_instance

    def disconnect(self) -> None:
        """Disconnects from vCenter or ESXi if connected."""
        if self._service_instance is None:
            return
        Disconnect(self._service_instance)
        self._service_instance = None

    def get_service_instance(self) -> vim.ServiceInstance:
        """Returns a connected service instance, connecting if needed.

        Returns:
            pyVmomi service instance.
        """
        return self.connect()


class VSphereClientPool:
    """Manages multiple VSphereClient instances keyed by target name."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._clients: dict[str, VSphereClient] = {}
        self._build_clients()
        atexit.register(self.disconnect_all)

    def _build_clients(self) -> None:
        hosts = self._config.get("vsphere", {}).get("hosts")
        if not hosts:
            raise ValueError("config vsphere.hosts is empty")
        for target, host_config in hosts.items():
            sub_config = {**self._config, "vsphere": host_config}
            client = VSphereClient(sub_config)
            client._register_atexit = False
            self._clients[target] = client

    def connect_all(self) -> None:
        """Connects all targets. Rolls back on failure."""
        connected: list[str] = []
        try:
            for target, client in self._clients.items():
                client.connect()
                connected.append(target)
        except Exception:
            for t in connected:
                self._clients[t].disconnect()
            raise

    def disconnect_all(self) -> None:
        """Disconnects all targets."""
        for client in self._clients.values():
            client.disconnect()

    def get(self, target: str) -> VSphereClient:
        """Returns the client for a given target name."""
        if target not in self._clients:
            raise KeyError(
                f"target '{target}' not found, available: {list(self._clients.keys())}"
            )
        return self._clients[target]

    def all_clients(self) -> dict[str, VSphereClient]:
        """Returns all {target: client} for read parallelism."""
        return dict(self._clients)

    @property
    def target_names(self) -> list[str]:
        """Returns available target names."""
        return list(self._clients.keys())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Loads project YAML configuration.

    Args:
        path: Path to config.yaml.

    Returns:
        Parsed configuration dictionary.

    Raises:
        VSphereConfigError: If the file is missing or invalid.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise VSphereConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise VSphereConfigError("Config file must contain a YAML mapping")
    return data


def _required_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise VSphereConfigError(f"vsphere.{key} is required")
    return value


def _build_ssl_context(insecure_ssl: bool) -> ssl.SSLContext | None:
    if not insecure_ssl:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
