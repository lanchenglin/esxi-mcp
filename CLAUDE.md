# ESXi MCP Server

MCP (Model Context Protocol) server for VMware ESXi hypervisor management. AI agents use this server to query hosts, manage VMs, monitor datastores, and retrieve performance metrics.

## Architecture

- Language: Python 3.10+
- MCP SDK: `mcp` (Python SDK, `pip install mcp`)
- ESXi API: VMware ESXi SOAP API via `pyvmomi` (official VMware Python SDK)
- Transport: stdio (standard MCP server)

## Dependencies

- `mcp` — MCP Python SDK
- `pyvmomi` — VMware vSphere SOAP API bindings
- `requests` — HTTP (fallback for REST endpoints where available)

## MCP Tools to Implement

### 1. Host Management
- `esxi_host_info` — Get ESXi host summary (name, version, uptime, connection state, CPU model, memory)
- `esxi_host_status` — Quick health check (overall status, hardware status, sensors)

### 2. Virtual Machines
- `esxi_list_vms` — List all VMs with name, power state, guest OS, CPU/memory allocation
- `esxi_vm_info` — Get detailed info for a specific VM (by name or ID)
- `esxi_vm_power` — Power on/off/suspend/reset a VM (by name)

### 3. Datastores
- `esxi_list_datastores` — List datastores with capacity, free space, type

### 4. Performance Metrics
- `esxi_host_perf` — Get current CPU/memory/network/disk usage for the host
- `esxi_vm_perf` — Get current CPU/memory/network/disk usage for a VM

### 5. Events & Tasks
- `esxi_recent_tasks` — List recent tasks (success/failure, timestamps)

## Configuration

Server reads connection details from environment variables:
- `ESXI_HOST` — ESXi host IP or hostname
- `ESXI_USER` — Username (default: root)
- `ESXI_PASSWORD` — Password
- `ESXI_PORT` — Port (default: 443)
- `ESXI_VERIFY_SSL` — Verify SSL certificate (default: false, since ESXi uses self-signed certs)

## Project Structure

```
esxi-mcp/
├── esxi_mcp/
│   ├── __init__.py
│   ├── server.py          # MCP server entry point
│   ├── esxi_client.py     # ESXi connection and API wrapper
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── host.py        # Host-related tools
│   │   ├── vm.py          # VM-related tools
│   │   ├── datastore.py   # Datastore tools
│   │   ├── perf.py        # Performance tools
│   │   └── tasks.py       # Event/task tools
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

## Code Standards

- Type hints on all public functions
- Google-style docstrings
- 4-space indentation
- Async where MCP SDK requires it
- Handle connection errors gracefully with clear error messages
- Don't crash on individual VM/perf query failures — return partial results

## Security Notes

- Never log passwords
- Use `ssl.SSLContext` with verification disabled by default (ESXi self-signed certs)
- Validate VM names before power operations (prevent injection)
- Connection timeout: 30 seconds

## Entry Point

```python
# server.py
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server

async def main():
    server = Server("esxi-mcp")
    # Register tools...
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    asyncio.run(main())
```

## pyproject.toml

```toml
[project]
name = "esxi-mcp"
version = "0.1.0"
description = "MCP server for VMware ESXi management"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0.0",
    "pyvmomi>=8.0",
    "requests>=2.28",
]

[project.scripts]
esxi-mcp = "esxi_mcp.server:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

## Implementation Notes

- pyvmomi uses a ServiceInstance to connect: `SmartConnect(host=..., user=..., pwd=..., port=..., sslContext=...)`
- Host perf counters are accessed via `PerformanceManager` with metric IDs like `cpu.usage.average`, `mem.usage.average`
- VM list via `containerView` of type `VirtualMachine`
- Datastore list via `containerView` of type `Datastore`
- Tasks via `TaskManager.recentTask`
- Power operations: `vm.PowerOn()`, `vm.PowerOff()`, `vm.Suspend()`, `vm.ResetVM()`
