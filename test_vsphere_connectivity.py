"""ESXi vSphere API connectivity test — 172.16.0.x hosts."""

from __future__ import annotations

import socket
import ssl
import sys

from pyVim.connect import SmartConnect
from pyVmomi import vim


HOSTS = [
    "172.16.0.192",
    "172.16.0.193",
    "172.16.0.194",
    "172.16.0.195",
    "172.16.0.200",
    "172.16.0.172",
    "172.16.0.241",
    "172.16.0.242",
    "172.16.0.243",
]

KNOWN_51 = {"172.16.0.193", "172.16.0.194"}

PASSWORDS_ALL = ["zkgillion368", "zkGillion@368"]
PASSWORD_51 = ["zkgillion368"]

TCP_TIMEOUT = 5
CONNECT_TIMEOUT = 15

SSL_PROTOCOLS = [
    ssl.PROTOCOL_TLS_CLIENT,
    ssl.PROTOCOL_TLSv1,
    ssl.PROTOCOL_SSLv23,
]


def _ssl_context(protocol: int) -> ssl.SSLContext:
    ctx = ssl.SSLContext(protocol)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    return ctx


def _tcp_reachable(host: str, port: int = 443) -> bool:
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return True
    except (socket.timeout, OSError):
        return False


class ConnectResult:
    """Typed result from a connection attempt."""

    def __init__(
        self,
        si: vim.ServiceInstance | None = None,
        ssl_error: str | None = None,
        login_error: str | None = None,
        other_error: str | None = None,
    ) -> None:
        self.si = si
        self.ssl_error = ssl_error
        self.login_error = login_error
        self.other_error = other_error


def _try_connect(host: str, password: str, ctx: ssl.SSLContext) -> ConnectResult:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(CONNECT_TIMEOUT)
    try:
        si = SmartConnect(
            host=host, user="root", pwd=password, port=443, sslContext=ctx
        )
        return ConnectResult(si=si)
    except vim.fault.InvalidLogin:
        return ConnectResult(login_error="密码错误")
    except (ssl.SSLError, ConnectionRefusedError, socket.timeout, OSError) as exc:
        return ConnectResult(ssl_error=str(exc))
    except vim.fault.VimFault as exc:
        return ConnectResult(other_error=str(exc))
    except Exception as exc:
        return ConnectResult(other_error=str(exc))
    finally:
        socket.setdefaulttimeout(prev)


def _test_host(host: str) -> dict:
    print(f"  [{host}] TCP probe ...", end=" ", flush=True)

    if not _tcp_reachable(host):
        print("不通")
        return {"host": host, "status": "TCP不通"}

    print("通 → pyVmomi ...", end=" ", flush=True)

    passwords = PASSWORD_51 if host in KNOWN_51 else PASSWORDS_ALL
    last_ssl_err: str | None = None

    for protocol in SSL_PROTOCOLS:
        ctx = _ssl_context(protocol)
        last_ssl_err = None
        login_failed = False
        for pwd in passwords:
            result = _try_connect(host, pwd, ctx)
            if result.si is not None:
                return _read_host_info(host, result.si, pwd)
            if result.login_error:
                login_failed = True
                continue
            if result.other_error:
                print(f"错误: {result.other_error}")
                return {"host": host, "status": result.other_error}
            last_ssl_err = result.ssl_error
            break
        if login_failed and last_ssl_err is None:
            print(f"密码错误 ({', '.join(passwords)})")
            return {"host": host, "status": "密码错误"}

    print(f"SSL握手失败 ({last_ssl_err})" if last_ssl_err else "连接失败")
    return {"host": host, "status": "SSL握手失败"}


def _read_host_info(host: str, si: vim.ServiceInstance, password: str) -> dict:
    try:
        content = si.RetrieveContent()
        about = content.about
        version = about.fullName or about.version
        host_name = about.name

        vms = []
        for child in content.rootFolder.childEntity:
            if isinstance(child, vim.Datacenter):
                vms = _collect_vms(child.vmFolder)
                break

        vm_names = [vm.name for vm in vms]
        print(f"✓ {host_name} ({version}), {len(vms)} VMs")
        return {
            "host": host,
            "status": "✓ 连接成功",
            "version": version,
            "password": password,
            "vm_count": len(vms),
            "vm_names": vm_names,
        }
    except Exception as exc:
        print(f"连接成功但读取失败: {exc}")
        return {"host": host, "status": "读取失败", "password": password}


def _collect_vms(folder: vim.Folder) -> list[vim.VirtualMachine]:
    vms: list[vim.VirtualMachine] = []
    for child in folder.childEntity:
        if isinstance(child, vim.VirtualMachine):
            vms.append(child)
        elif isinstance(child, vim.Folder):
            vms.extend(_collect_vms(child))
    return vms


def main() -> None:
    print("ESXi vSphere API 连接测试\n")
    results = [_test_host(host) for host in HOSTS]

    print()
    print(f"{'主机':<18}{'状态':<14}{'版本':<40}{'密码':<18}{'VM数':<6}")
    print("-" * 96)
    for r in results:
        print(
            f"{r['host']:<18}"
            f"{r.get('status', '-'):<14}"
            f"{r.get('version', '-'):<40}"
            f"{r.get('password', '-'):<18}"
            f"{r.get('vm_count', '-'):<6}"
        )

    for r in results:
        if r.get("vm_names"):
            print(f"\n{r['host']} VMs:")
            for name in r["vm_names"]:
                print(f"  - {name}")

    sys.exit(0)


if __name__ == "__main__":
    main()
