# ESXi Power MCP Server

轻量级 ESXi / vSphere MCP Server，专注资源巡检和虚拟机电源管理。只暴露 7 个工具：列出虚拟机、查询 VM 状态、列出宿主机、查询宿主机资源、开机、强制关机、强制重启。

## 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 配置

复制模板并编辑 `config.yaml`：

```bash
cp config.yaml.template config.yaml
```

支持两种密码配置方式：

### 方式一：明文密码（简单场景）

```yaml
vsphere:
  hosts:
    esxi-example:
      host: "172.16.0.x"
      port: 443
      username: "root"
      password: "your-password-here"
      insecure_ssl: true
```

### 方式二：环境变量（推荐生产使用）

```yaml
vsphere:
  hosts:
    esxi-example:
      host: "172.16.0.x"
      port: 443
      username: "root"
      password_env: "VSPHERE_PASSWORD_ESXI_EXAMPLE"
      insecure_ssl: true
```

```bash
export VSPHERE_PASSWORD_ESXI_EXAMPLE='your-password'
```

> 优先读取 `password` 字段，未配置则从 `password_env` 指定的环境变量获取。密码不要提交到 git。

### 安全控制

电源操作受 `safety.allow_power_ops`（白名单）和 `safety.deny_power_ops`（黑名单）控制。黑名单优先级高于白名单，空白名单阻止所有电源操作。

## 运行

```bash
python3 server.py
```

服务使用 FastMCP 通过 stdio 通信，通过 pyVmomi 连接 vCenter 或直连 ESXi。

## Docker

### 构建镜像

```bash
docker build -t esxi-mcp .
```

### 直接运行

```bash
docker run -i \
  --network host \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v esxi-logs:/app/logs \
  esxi-mcp
```

`-i` 标志必须保留 — MCP Server 通过 stdio 通信，stdin 必须保持打开。`--network host` 确保容器能访问内网 ESXi 主机。

### Docker Compose

```bash
docker-compose up -d
```

配置文件以只读方式挂载，审计日志持久化在 `esxi-logs` 卷中。

### MCP 客户端配置（Claude Desktop / Hermes）

```json
{
  "mcpServers": {
    "esxi-power-mcp": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--network", "host", "-v", "/path/to/config.yaml:/app/config.yaml:ro", "-v", "esxi-logs:/app/logs", "esxi-mcp"]
    }
  }
}
```

## 工具清单

### 只读工具

- `list_vms(keyword=None, power_state=None, target=None)` — 省略 `target` 时并行查询所有主机，每条结果包含 `source` 字段
- `get_vm_status(vm_name=None, uuid=None, moid=None, target=None)`
- `list_hosts(keyword=None, target=None)`
- `get_host_resource(host_name, target=None)`

### 写操作工具

- `power_on_vm(vm_name=None, uuid=None, moid=None, target, task_timeout=300, state_timeout=900)`
- `power_off_vm(vm_name=None, uuid=None, moid=None, target, confirm=False, task_timeout=300, state_timeout=900)`
- `restart_vm_force(vm_name=None, uuid=None, moid=None, target, confirm=False, poweroff_task_timeout=300, poweroff_state_timeout=900, poweron_task_timeout=300, poweron_state_timeout=900, boot_wait=30)`

`target` 在写操作中**必填**。读操作可省略 `target` 以查询所有主机并合并结果。`power_off_vm` 和 `restart_vm_force` 必须传 `confirm=true`。所有写操作必须匹配白名单、不匹配黑名单、且精确定位到唯一 VM。

## VM 查找优先级

1. `moid`（精确）
2. `uuid`（精确）
3. `vm_name`（必须唯一，重名时报错）

建议先调用 `list_vms` 获取 `moid` 和 `uuid` 用于精确操作。

## 审计日志

所有写操作尝试（成功、阻止、失败）都会以 JSON Lines 格式记录到 `logs/audit.log`。日志超过 10 MiB 时自动轮转为 `audit.log.1`。

## 测试

```bash
python3 -m unittest discover -s tests
python3 -m compileall .
```
