## 任务：排查 172.16.0.251 连接失败原因

### 背景
- `test_vsphere_connectivity.py` 扫描 .172-.251，27/28 台连接成功，仅 .251 报"密码错误"
- 但用户本地 vSphere Client 连接 .251 正常，密码 Gillion@168 是正确的
- 所以不是密码问题，而是 pyvmomi 连接方式兼容性问题

### 已知环境信息
- 密码：Gillion@168（已确认正确）
- 用户名：root（同上）
- 该环境 ESXi 版本未知（请通过多种方式探测）
- 项目中已有 TLS 降级逻辑应对 ESXi 5.1（PROTOCOL_SSLv23 fallback）

### 需要排查的方向（逐一尝试）

1. **SSL/TLS 版本探测**
   - 尝试不同的 SSL 版本：PROTOCOL_TLS_CLIENT, PROTOCOL_SSLv23, PROTOCOL_TLSv1, PROTOCOL_TLSv1_1, PROTOCOL_TLSv1_2
   - 尝试完全跳过 SSL 验证的不同方式
   - 可能 .251 是更老的版本需要更激进的 SSL 降级

2. **连接参数变体**
   - 尝试不同的 API 端口（443, 902, 9443）
   - 尝试 HTTP 直连（不经过 HTTPS）
   - 尝试不同的连接超时

3. **pyvmomi 连接方式**
   - 尝试 SmartConnect 不同参数组合
   - 尝试直接用 SoapStubAdapter
   - 尝试 Disconnect 后重连

4. **认证方式**
   - 确认是否开启了 Lockdown Mode
   - 尝试不同的认证机制

5. **版本探测**
   - 尝试通过 HTTPS 请求 /sdk 端点看返回头中的版本信息
   - 尝试 curl 探测
   - 尝试 openssl s_client 看 TLS 握手情况

### 输出要求
- 每尝试一种方式，记录结果
- 最终要么连接成功（更新 hosts-inventory.md 和 config.yaml），要么给出明确的失败原因
- 无论成功失败，更新 docs/hosts-inventory.md 中的 .251 条目
