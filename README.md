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

默认通过 stdio 通信。设置环境变量 `MCP_TRANSPORT=sse` 可切换为 HTTP/SSE 模式，通过 `MCP_PORT` 指定端口（默认 8000）。

```bash
# stdio 模式（默认）
python3 server.py

# SSE 模式（远程访问）
MCP_TRANSPORT=sse MCP_PORT=8000 python3 server.py
```

## Docker

### 构建镜像

```bash
docker build -t esxi-mcp .
```

### 直接运行

```bash
# stdio 模式（默认，本地使用）
docker run -i \
  --network host \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v esxi-logs:/app/logs \
  esxi-mcp

# SSE 模式（远程访问）
docker run -d \
  --network host \
  -e MCP_TRANSPORT=sse \
  -e MCP_PORT=8000 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v esxi-logs:/app/logs \
  esxi-mcp
```

stdio 模式下 `-i` 标志必须保留，SSE 模式下无需 `-i`。`--network host` 确保容器能访问内网 ESXi 主机。

### Docker Compose

```bash
# stdio 模式（默认）
docker-compose up -d

# SSE 模式
MCP_TRANSPORT=sse docker-compose up -d
```

通过环境变量 `MCP_TRANSPORT` 和 `MCP_PORT` 控制传输模式，配置文件以只读方式挂载，审计日志持久化在 `esxi-logs` 卷中。

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
