# ESXi Power MCP Server

轻量级 ESXi / vSphere MCP Server，只做资源巡检和电源管理。优先连接 vCenter，无 vCenter 时直连 ESXi。

## 核心定位

这不是完整 vSphere 管理 MCP，而是面向日常运维的轻量场景：
- 查询虚拟机状态
- 查询宿主机资源
- 虚拟机强制关机
- 虚拟机开机
- 虚拟机强制重启
- 关机/开机慢时自动等待状态完成

## 架构

```
AI / Hermes / Claude / Cursor
        ↓
自定义 MCP Server (stdio)
        ↓
pyVmomi
        ↓
vCenter 或 ESXi
```

## MCP 工具清单（7 个）

### 只读工具
1. `list_vms` — 列出 VM（keyword/power_state 过滤）
2. `get_vm_status` — 查询单台 VM 详细状态（uuid/moid/vm_name）
3. `list_hosts` — 列出 ESXi 宿主机
4. `get_host_resource` — 查询宿主机资源摘要（cpu/memory/vm_count）

### 写操作工具
5. `power_on_vm` — 开机（不需要 confirm）
6. `power_off_vm` — 强制关机（必须 confirm=true）
7. `restart_vm_force` — 强制重启（必须 confirm=true）

## 关键设计规则

### 只做必要功能，严禁越界
保留: list_vms, get_vm_status, list_hosts, get_host_resource, power_on_vm, power_off_vm, restart_vm_force
不暴露: delete_vm, create_vm, clone_vm, snapshot_vm, remove_snapshot, migrate_vm, reconfig_vm, edit_network, edit_disk, edit_cpu_memory

### 写操作安全控制
- `power_off_vm` 必须 `confirm=true`
- `restart_vm_force` 必须 `confirm=true`
- 黑名单优先级高于白名单
- 不允许空白名单执行 power_off/restart
- 不允许模糊匹配到多个 VM 后执行写操作
- 写操作必须精确定位到唯一 VM

### 两层等待机制
不只等 Task 成功，还要等 VM runtime.powerState 达到目标：

```
PowerOffVM_Task → wait task success → wait runtime.powerState == poweredOff
PowerOnVM_Task → wait task success → wait runtime.powerState == poweredOn
```

强制重启流程：
```
PowerOffVM_Task → wait task success → wait poweredOff → PowerOnVM_Task → wait task success → wait poweredOn → optional boot_wait
```

### 状态机（restart_vm_force）
- poweredOn → 执行 PowerOff → 等待 → 确认 poweredOff → 执行 PowerOn
- poweredOff → 跳过 PowerOff → 直接 PowerOn
- suspended → 不处理，返回需要人工确认

### 超时设计
| 参数 | 默认值 | 说明 |
|------|--------|------|
| task_timeout | 300s | vSphere Task 超时 |
| poweroff_state_timeout | 900s | 等待 poweredOff |
| poweron_state_timeout | 900s | 等待 poweredOn |
| boot_wait | 30s | 开机后额外等待 |

### 异常处理
必须返回明确错误原因：VM not found, VM name duplicated, TaskInProgress, InvalidPowerState, NoPermission, Timedout, Host not connected, Maintenance mode

## 项目结构

```
esxi-mcp/
├── server.py              # MCP Server 入口（FastMCP）
├── vsphere_client.py      # vCenter/ESXi 连接封装
├── vm_power.py            # PowerOn/PowerOff/Restart 核心逻辑
├── vm_inventory.py        # VM 查询与状态读取
├── host_inventory.py      # 宿主机资源巡检
├── safety.py              # 白名单、黑名单、confirm 校验
├── audit.py               # 操作审计日志（JSON Lines）
├── config.yaml            # 运行配置
├── requirements.txt       # 依赖
├── docs/
│   └── esxi_vsphere_mcp_power_plan.md  # 本设计文档
├── logs/
│   └── audit.log
└── tests/
    ├── test_safety.py
    └── test_power_logic.py
```

## 配置文件 (config.yaml)

```yaml
vsphere:
  host: "vcenter.example.com"
  port: 443
  username: "svc_mcp_vsphere"
  password_env: "VSPHERE_PASSWORD"    # 密码从环境变量读取
  insecure_ssl: true

mcp:
  name: "esxi-power-mcp"
  readonly_default: true

timeouts:
  task_timeout: 300
  poweroff_state_timeout: 900
  poweron_state_timeout: 900
  boot_wait: 30

safety:
  require_confirm_for_poweroff: true
  require_confirm_for_restart: true
  allow_power_ops:       # 白名单（支持通配符）
    - "test-vm-01"
    - "app-*"
    - "dev-*"
  deny_power_ops:        # 黑名单（优先级高于白名单）
    - "vcenter*"
    - "vcsa*"
    - "db-prod-*"
    - "mysql-prod-*"
    - "postgres-prod-*"
    - "redis-prod-*"
    - "k8s-master-*"

audit:
  enabled: true
  file: "./logs/audit.log"
```

## 环境变量

```bash
export VSPHERE_PASSWORD='your-password'
```

密码绝不写入配置文件。

## 审计日志格式（JSON Lines）

成功：
```json
{"time":"2026-05-13T09:30:00+08:00","operator":"mcp-user","tool":"restart_vm_force","vm":"test-vm-01","moid":"vm-123","before_power_state":"poweredOn","after_power_state":"poweredOn","result":"success","duration_seconds":186}
```

失败/被阻止：
```json
{"time":"2026-05-13T09:35:00+08:00","operator":"mcp-user","tool":"power_off_vm","vm":"db-prod-01","result":"blocked","reason":"VM matched deny_power_ops"}
```

## VM 查找优先级

1. `moid`（精确）
2. `uuid`（精确）
3. `vm_name`（必须唯一，重名时报错要求使用 uuid/moid）

## 核心函数参考（来自设计文档）

### 等待 Task
```python
def wait_task(task, timeout=300, interval=2):
    # 轮询 task.info.state
    # success → return True
    # error → raise Exception with msg
    # timeout → raise TimeoutError
```

### 等待电源状态
```python
def wait_power_state(vm, target_state, timeout=900, interval=5):
    # 轮询 vm.runtime.powerState
    # 达到 target_state → return True
    # timeout → raise TimeoutError
```

### 刷新 VM 状态
```python
def refresh_vm_status(vm) -> dict:
    # 返回 name, power_state, connection_state, host, boot_time, ip, tools_status
```

### 强制重启核心逻辑
```python
def restart_vm_force(vm, confirm=False, poweroff_task_timeout=300, ...):
    # 1. confirm 检查
    # 2. 记录 before 状态
    # 3. 如果 poweredOn → PowerOffVM_Task → wait_task → wait_power_state(poweredOff)
    # 4. 如果 poweredOff → 跳过关
    # 5. 如果 suspended → raise Exception(需要人工处理)
    # 6. PowerOnVM_Task → wait_task → wait_power_state(poweredOn)
    # 7. boot_wait
    # 8. 返回 before/after/steps/result
```

## MCP Server 入口 (FastMCP 风格)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("esxi-power-mcp")

@mcp.tool()
def list_vms(keyword: str = None, power_state: str = None): ...

@mcp.tool()
def get_vm_status(vm_name: str = None, uuid: str = None, moid: str = None): ...

@mcp.tool()
def list_hosts(keyword: str = None): ...

@mcp.tool()
def get_host_resource(host_name: str): ...

@mcp.tool()
def power_on_vm(vm_name: str = None, uuid: str = None, moid: str = None,
                task_timeout: int = 300, state_timeout: int = 900): ...

@mcp.tool()
def power_off_vm(vm_name: str = None, uuid: str = None, moid: str = None,
                 confirm: bool = False, task_timeout: int = 300,
                 state_timeout: int = 900): ...

@mcp.tool()
def restart_vm_force(vm_name: str = None, uuid: str = None, moid: str = None,
                     confirm: bool = False, poweroff_task_timeout: int = 300,
                     poweroff_state_timeout: int = 900,
                     poweron_task_timeout: int = 300,
                     poweron_state_timeout: int = 900,
                     boot_wait: int = 30): ...
```

## 依赖

```
pyvmomi
mcp
pyyaml
pydantic
```

## 代码标准

- Python 3.10+
- Type hints on all public functions
- Google-style docstrings
- 4-space indentation
- 连接超时 30s
- 不记录密码到日志
- 使用 ssl.SSLContext 并默认禁用证书验证（ESXi 自签名证书）
- 读操作返回部分结果不崩溃
- 写操作错误必须返回明确原因

## 实施路线

按文档第 16 节，先实现功能再用 MCP 封装，最后加安全控制。但本阶段直接全部实现：

1. vsphere_client.py — 连接和断开
2. vm_inventory.py — list_vms, get_vm_status, find_vm, refresh_vm_status
3. host_inventory.py — list_hosts, get_host_resource
4. vm_power.py — wait_task, wait_power_state, power_on_vm_impl, power_off_vm_impl, restart_vm_force_impl
5. safety.py — 白名单/黑名单匹配, check_power_permission
6. audit.py — write_audit_log (JSON Lines)
7. server.py — FastMCP 入口，注册所有 7 个 tool
8. config.yaml — 默认配置模板

## 重要参考

完整设计文档：`docs/esxi_vsphere_mcp_power_plan.md`（1379 行，含伪代码、状态机、MCP 工具定义、异常处理表、验证流程等）—— 在实现前请通读此文档。
