# ESXi Power MCP Server

Lightweight MCP server for ESXi / vSphere resource inspection and VM power recovery. It intentionally exposes only seven tools: VM listing, VM status, host listing, host resources, VM power on, forced VM power off, and forced VM restart.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Configure

Edit `config.yaml`:

```yaml
vsphere:
  hosts:
    vcenter-main:
      host: "vcenter.example.com"
      port: 443
      username: "svc_mcp_vsphere"
      password_env: "VSPHERE_PASSWORD_VC_MAIN"
      insecure_ssl: true
    # esxi-bj:
    #   host: "192.168.1.10"
    #   port: 443
    #   username: "root"
    #   password_env: "VSPHERE_PASSWORD_ESXI_BJ"
    #   insecure_ssl: true
```

Set each password in the environment. Do not put passwords in `config.yaml`.

```bash
export VSPHERE_PASSWORD_VC_MAIN='your-password'
# export VSPHERE_PASSWORD_ESXI_BJ='your-password'
```

Power operations are controlled by `safety.allow_power_ops` and `safety.deny_power_ops`. The deny list wins over the allow list, and an empty allow list blocks all VM power operations.

## Run

```bash
python3 server.py
```

The server uses FastMCP over stdio and connects to vCenter or directly to ESXi through pyVmomi.

## Docker

Build the image:

```bash
docker build -t esxi-mcp .
```

Run with config mounted and password from environment:

```bash
docker run -i \
  -e VSPHERE_PASSWORD_VC_MAIN='your-password' \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v esxi-logs:/app/logs \
  esxi-mcp
```

The `-i` flag is required — the MCP server communicates over stdio and stdin must stay open.

### Docker Compose

Create a `.env` file with your password:

```bash
echo 'VSPHERE_PASSWORD_VC_MAIN=your-password' > .env
```

Then start:

```bash
docker-compose up -d
```

Config is mounted read-only from the host. Audit logs persist in the `esxi-logs` named volume.

### MCP client config (Claude Desktop / Hermes)

```json
{
  "mcpServers": {
    "esxi-power-mcp": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "VSPHERE_PASSWORD_VC_MAIN", "-v", "/path/to/config.yaml:/app/config.yaml:ro", "-v", "esxi-logs:/app/logs", "esxi-mcp"]
    }
  }
}
```

## Tools

### Read-only

- `list_vms(keyword=None, power_state=None, target=None)` — query all targets in parallel when `target` is omitted; each item includes a `source` field
- `get_vm_status(vm_name=None, uuid=None, moid=None, target=None)`
- `list_hosts(keyword=None, target=None)`
- `get_host_resource(host_name, target=None)`

### Write operations

- `power_on_vm(vm_name=None, uuid=None, moid=None, target, task_timeout=300, state_timeout=900)`
- `power_off_vm(vm_name=None, uuid=None, moid=None, target, confirm=False, task_timeout=300, state_timeout=900)`
- `restart_vm_force(vm_name=None, uuid=None, moid=None, target, confirm=False, poweroff_task_timeout=300, poweroff_state_timeout=900, poweron_task_timeout=300, poweron_state_timeout=900, boot_wait=30)`

`target` is **required** for all write operations. Read operations accept an optional `target` — omit it to query all configured hosts and merge results. `power_off_vm` and `restart_vm_force` require `confirm=true`. All write operations must match `allow_power_ops`, must not match `deny_power_ops`, and must resolve to exactly one VM.

## VM lookup priority

1. `moid`
2. `uuid`
3. `vm_name` only when unique

Use `list_vms` first to discover `moid` and `uuid` for exact operations.

## Audit logs

All write attempts are recorded as JSON Lines in `logs/audit.log` by default, including successful, blocked, and failed operations. The log is rotated to `audit.log.1` when it grows beyond 10 MiB.

## Test

```bash
python3 -m unittest discover -s tests
python3 -m compileall .
```
