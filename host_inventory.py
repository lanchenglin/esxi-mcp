from __future__ import annotations

import re
from typing import Any

from pyVmomi import vim


class HostInventoryError(RuntimeError):
    """Raised when host inventory lookup fails."""


def list_hosts(
    service_instance: vim.ServiceInstance,
    keyword: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lists ESXi hosts with optional name filtering.

    Args:
        service_instance: Connected pyVmomi service instance.
        keyword: Optional case-insensitive host name substring.

    Returns:
        Dictionary with an items list.
    """
    items: list[dict[str, Any]] = []
    for host in _iter_hosts(service_instance):
        name = getattr(host, "name", "")
        if keyword and keyword.lower() not in name.lower():
            continue
        summary = getattr(host, "summary", None)
        hardware = getattr(summary, "hardware", None) if summary else None
        runtime = getattr(host, "runtime", None)
        items.append(
            {
                "name": name,
                "connection_state": _enum_value(getattr(runtime, "connectionState", None) if runtime else None),
                "power_state": _enum_value(getattr(runtime, "powerState", None) if runtime else None),
                "maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)) if runtime else None,
                "cpu_cores": getattr(hardware, "numCpuCores", None) if hardware else None,
                "memory_total_gb": _bytes_to_gb(getattr(hardware, "memorySize", None) if hardware else None),
            }
        )
    return {"items": items}


def get_host_resource(service_instance: vim.ServiceInstance, host_name: str) -> dict[str, Any]:
    """Returns CPU, memory, and VM count for an ESXi host.

    Args:
        service_instance: Connected pyVmomi service instance.
        host_name: Exact host name.

    Returns:
        Host resource dictionary.

    Raises:
        HostInventoryError: If the host is not found.
    """
    host = _find_host(service_instance, host_name)
    summary = getattr(host, "summary", None)
    hardware = getattr(summary, "hardware", None) if summary else None
    quick_stats = getattr(summary, "quickStats", None) if summary else None
    runtime = getattr(host, "runtime", None)
    vm_list = list(getattr(host, "vm", []) or [])

    return {
        "name": getattr(host, "name", None),
        "connection_state": _enum_value(getattr(runtime, "connectionState", None) if runtime else None),
        "maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)) if runtime else None,
        "cpu_total_mhz": _cpu_total_mhz(hardware),
        "cpu_used_mhz": getattr(quick_stats, "overallCpuUsage", None) if quick_stats else None,
        "memory_total_mb": _bytes_to_mb(getattr(hardware, "memorySize", None) if hardware else None),
        "memory_used_mb": getattr(quick_stats, "overallMemoryUsage", None) if quick_stats else None,
        "vm_count": len(vm_list),
    }


def _find_host(service_instance: vim.ServiceInstance, host_name: str) -> vim.HostSystem:
    matches = [host for host in _iter_hosts(service_instance) if host.name == host_name]
    if not matches:
        raise HostInventoryError(f"Host not found: {host_name}")
    if len(matches) > 1:
        raise HostInventoryError(f"Host name duplicated: {host_name}")
    return matches[0]


def _iter_hosts(service_instance: vim.ServiceInstance) -> list[vim.HostSystem]:
    content = service_instance.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _cpu_total_mhz(hardware: Any) -> int | None:
    if hardware is None:
        return None
    hz = getattr(hardware, "cpuMhz", None)
    cores = getattr(hardware, "numCpuCores", None)
    if hz is None or cores is None:
        return None
    return int(hz) * int(cores)


def _bytes_to_mb(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value // 1024 // 1024)


def _bytes_to_gb(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value // 1024 // 1024 // 1024)


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    return getattr(obj, attr, default) if obj is not None else default


def _pct(used: float | int | None, total: float | int | None) -> float | None:
    if used is None or total is None or total == 0:
        return None
    return round(float(used) / float(total) * 100, 1)


_SENSOR_ALERT_PATTERNS = [
    (re.compile(r"Drive Fault(?!\s*-\s*Deassert)", re.I), "critical", "磁盘故障"),
    (re.compile(r"Predictive Failure(?!\s*-\s*Deassert)", re.I), "warning", "磁盘预故障"),
    (re.compile(r"In Critical Array(?!\s*-\s*Deassert)", re.I), "critical", "RAID 阵列降级"),
    (re.compile(r"In Failed Array(?!\s*-\s*Deassert)", re.I), "critical", "RAID 阵列失败"),
    (re.compile(r"Rebuild In Progress(?!\s*-\s*Deassert)", re.I), "warning", "RAID 重建中"),
    (re.compile(r"Rebuild Aborted(?!\s*-\s*Deassert)", re.I), "critical", "RAID 重建中止"),
    (re.compile(r"Parity Check In Progress(?!\s*-\s*Deassert)", re.I), "warning", "RAID 一致性检查"),
    (re.compile(r"(?:Drive|Disk|Array|RAID|PERC).*Config Error(?!\s*-\s*Deassert)", re.I), "warning", "存储配置错误"),
    (re.compile(r"Battery.*(?:Failed|Low)(?!\s*-\s*Deassert)", re.I), "warning", "RAID 电池异常"),
    (re.compile(r"Cache.*(?:Failed|Degraded)(?!\s*-\s*Deassert)", re.I), "warning", "RAID 缓存异常"),
]

_SENSOR_TYPE_MAP = {
    "temperature": "温度",
    "fan": "风扇",
    "power": "电源",
    "voltage": "电压",
    "storage": "存储",
    "battery": "电池",
}

_DISK_SENSOR_EXCLUDE = re.compile(
    r"Software Components|scsi-megaraid|scsi-aacraid|scsi-megaraid-mbox|"
    r"scsi-megaraid2|misc-drivers|driver\s|^CPU\d",
    re.I,
)


def _analyze_sensors(sensors: list[Any]) -> dict[str, Any]:
    """Analyzes IPMI/BMC numeric sensors, returns alerts and category summaries."""
    alerts: list[dict[str, str]] = []
    categories: dict[str, int] = {}
    for s in sensors:
        name = _safe_get(s, "name") or ""
        stype = str(_safe_get(s, "sensorType") or "").lower()
        reading = _safe_get(s, "currentReading", 0)
        if _DISK_SENSOR_EXCLUDE.search(name):
            continue
        cat_key = _SENSOR_TYPE_MAP.get(stype, stype)
        categories[cat_key] = categories.get(cat_key, 0) + 1
        if stype == "temperature" and reading and "Temp" in name:
            temp_c = reading / 100.0
            if temp_c > 80:
                alerts.append({"severity": "critical", "category": "温度", "message": f"{name}: {temp_c:.0f}°C"})
            elif temp_c > 70:
                alerts.append({"severity": "warning", "category": "温度", "message": f"{name}: {temp_c:.0f}°C"})
        if stype == "fan" and reading is not None and reading == 0 and "RPM" in name:
            alerts.append({"severity": "critical", "category": "风扇", "message": f"{name}: 0 RPM (故障)"})
        if stype == "power" and reading is not None and reading == 0:
            if "Current" in name and "- Deassert" not in name and "--- Normal" not in name:
                alerts.append({"severity": "warning", "category": "电源", "message": f"{name}: 0A (可能离线)"})
        for pattern, severity, label in _SENSOR_ALERT_PATTERNS:
            if pattern.search(name):
                alerts.append({"severity": severity, "category": "磁盘阵列", "message": f"{name}"})
                break
    return {"alerts": alerts, "sensor_categories": categories}


def _analyze_disk_luns(scsi_luns: list[Any]) -> list[dict[str, Any]]:
    """Analyzes SCSI LUNs for operational state anomalies."""
    disk_issues: list[dict[str, str]] = []
    for lun in scsi_luns:
        device_name = _safe_get(lun, "deviceName", "")
        if "cdrom" in device_name:
            continue
        op_states = list(_safe_get(lun, "operationalState") or [])
        if not all(s == "ok" for s in op_states):
            disk_issues.append({
                "device": device_name,
                "model": _safe_get(lun, "model", "?"),
                "operational_state": ", ".join(op_states) if op_states else "unknown",
            })
    return disk_issues


def get_host_health(
    service_instance: vim.ServiceInstance,
    host_name: str,
) -> dict[str, Any]:
    """Returns comprehensive health status for one ESXi host.

    Args:
        service_instance: Connected pyVmomi service instance.
        host_name: Exact host name.

    Returns:
        Host health dictionary.
    """
    host = _find_host(service_instance, host_name)
    summary = _safe_get(host, "summary")
    hardware = _safe_get(summary, "hardware")
    quick_stats = _safe_get(summary, "quickStats")
    runtime = _safe_get(host, "runtime")

    cpu_total_mhz = _cpu_total_mhz(hardware)
    cpu_used_mhz = _safe_get(quick_stats, "overallCpuUsage")
    mem_total_bytes = _safe_get(hardware, "memorySize")
    mem_used_mb = _safe_get(quick_stats, "overallMemoryUsage")
    mem_total_mb = _bytes_to_mb(mem_total_bytes)

    uptime_seconds = _safe_get(quick_stats, "uptime")

    alarms = []
    for alarm_state in _safe_get(host, "triggeredAlarmState") or []:
        alarm_info = _safe_get(alarm_state, "alarm")
        alarms.append({
            "name": _safe_get(alarm_info, "info", {}).get("name") if alarm_info else None,
            "severity": _enum_value(_safe_get(alarm_state, "overallStatus")),
            "description": _safe_get(alarm_info, "info", {}).get("description") if alarm_info else None,
            "triggered_time": str(_safe_get(alarm_state, "time")) if _safe_get(alarm_state, "time") else None,
        })

    vm_list = list(_safe_get(host, "vm") or [])
    vm_powered_on = 0
    vm_powered_off = 0
    vm_suspended = 0
    for vm_obj in vm_list:
        state = str(_safe_get(_safe_get(vm_obj, "runtime"), "powerState", ""))
        if state == "poweredOn":
            vm_powered_on += 1
        elif state == "poweredOff":
            vm_powered_off += 1
        elif state == "suspended":
            vm_suspended += 1

    # Config issues (e.g. SSH enabled events)
    config_issues = []
    for ci in _safe_get(host, "configIssue") or []:
        config_issues.append({
            "type": type(ci).__name__,
            "message": _safe_get(ci, "fullFormattedMessage") or str(ci),
        })

    # Hardware sensor alerts (temperature, fan, power, disk/RAID)
    health_runtime = _safe_get(runtime, "healthSystemRuntime")
    sensor_info = _safe_get(_safe_get(health_runtime, "systemHealthInfo"), "numericSensorInfo")
    sensor_result = _analyze_sensors(list(sensor_info or []))

    # Disk LUN operational state
    storage_system = _safe_get(_safe_get(host, "configManager"), "storageSystem")
    scsi_luns = _safe_get(_safe_get(storage_system, "storageDeviceInfo"), "scsiLun")
    disk_issues = _analyze_disk_luns(list(scsi_luns or []))

    return {
        "name": _safe_get(host, "name"),
        "overall_status": _enum_value(_safe_get(host, "overallStatus")),
        "config_status": _enum_value(_safe_get(host, "configStatus")),
        "config_issues": config_issues,
        "alarms": alarms,
        "hardware_alerts": sensor_result["alerts"],
        "sensor_categories": sensor_result["sensor_categories"],
        "disk_issues": disk_issues,
        "cpu": {
            "used_mhz": cpu_used_mhz,
            "total_mhz": cpu_total_mhz,
            "usage_percent": _pct(cpu_used_mhz, cpu_total_mhz),
            "cores": _safe_get(hardware, "numCpuCores"),
            "threads": _safe_get(hardware, "numCpuThreads"),
            "packages": _safe_get(hardware, "numCpuPkgs"),
            "model": _safe_get(hardware, "cpuModel"),
        },
        "memory": {
            "used_mb": mem_used_mb,
            "total_mb": mem_total_mb,
            "usage_percent": _pct(mem_used_mb, mem_total_mb),
        },
        "uptime_seconds": uptime_seconds,
        "uptime_days": round(uptime_seconds / 86400, 1) if uptime_seconds else None,
        "boot_time": str(_safe_get(runtime, "bootTime")) if _safe_get(runtime, "bootTime") else None,
        "vm_count": {
            "powered_on": vm_powered_on,
            "powered_off": vm_powered_off,
            "suspended": vm_suspended,
            "total": len(vm_list),
        },
        "hardware": {
            "vendor": _safe_get(hardware, "vendor"),
            "model": _safe_get(hardware, "model"),
            "num_nics": _safe_get(hardware, "numNics"),
            "num_hbas": _safe_get(hardware, "numHBAs"),
        },
        "maintenance_mode": bool(_safe_get(runtime, "inMaintenanceMode", False)) if runtime else None,
    }


def get_host_storage(
    service_instance: vim.ServiceInstance,
    host_name: str,
) -> dict[str, Any]:
    """Returns storage/Datastore usage for one ESXi host.

    Args:
        service_instance: Connected pyVmomi service instance.
        host_name: Exact host name.

    Returns:
        Host storage dictionary.
    """
    host = _find_host(service_instance, host_name)
    datastores = []
    total_cap = 0.0
    total_used = 0.0

    for ds in _safe_get(host, "datastore") or []:
        ds_summary = _safe_get(ds, "summary")
        if ds_summary is None:
            continue
        cap_bytes = _safe_get(ds_summary, "capacity")
        free_bytes = _safe_get(ds_summary, "freeSpace")
        used_bytes = (cap_bytes - free_bytes) if cap_bytes and free_bytes else None
        cap_gb = _bytes_to_gb(cap_bytes)
        used_gb = _bytes_to_gb(used_bytes) if used_bytes else None
        free_gb = _bytes_to_gb(free_bytes)
        datastores.append({
            "name": _safe_get(ds_summary, "name"),
            "type": _safe_get(ds_summary, "type"),
            "capacity_gb": cap_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "usage_percent": _pct(used_bytes, cap_bytes),
            "accessible": _safe_get(ds_summary, "accessible"),
        })
        if cap_gb:
            total_cap += cap_gb
        if used_gb:
            total_used += used_gb

    total_free = total_cap - total_used if total_cap and total_used else None
    return {
        "name": _safe_get(host, "name"),
        "datastores": datastores,
        "summary": {
            "total_gb": round(total_cap, 1) if total_cap else None,
            "used_gb": round(total_used, 1) if total_used else None,
            "free_gb": round(total_free, 1) if total_free is not None else None,
            "usage_percent": _pct(total_used, total_cap),
        },
    }


def inspect_hosts_single(
    service_instance: vim.ServiceInstance,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """Returns condensed health summary for all hosts on one service instance.

    Args:
        service_instance: Connected pyVmomi service instance.
        status_filter: Filter by status: "green", "yellow", "red", or "not_green".

    Returns:
        Dictionary with items list.
    """
    items: list[dict[str, Any]] = []
    for host in _iter_hosts(service_instance):
        overall_status = _enum_value(_safe_get(host, "overallStatus"))
        if status_filter:
            if status_filter == "not_green":
                if overall_status == "green":
                    continue
            elif overall_status != status_filter:
                continue

        summary = _safe_get(host, "summary")
        hardware = _safe_get(summary, "hardware")
        quick_stats = _safe_get(summary, "quickStats")
        runtime = _safe_get(host, "runtime")

        cpu_total_mhz = _cpu_total_mhz(hardware)
        cpu_used_mhz = _safe_get(quick_stats, "overallCpuUsage")
        mem_total_mb = _bytes_to_mb(_safe_get(hardware, "memorySize"))
        mem_used_mb = _safe_get(quick_stats, "overallMemoryUsage")
        uptime_seconds = _safe_get(quick_stats, "uptime")

        ds_total = 0.0
        ds_used = 0.0
        for ds in _safe_get(host, "datastore") or []:
            ds_summary = _safe_get(ds, "summary")
            if ds_summary is None:
                continue
            cap = _safe_get(ds_summary, "capacity")
            free = _safe_get(ds_summary, "freeSpace")
            if cap:
                ds_total += cap
            if cap and free:
                ds_used += (cap - free)

        alarms_count = len(_safe_get(host, "triggeredAlarmState") or [])
        vm_list = list(_safe_get(host, "vm") or [])

        items.append({
            "name": _safe_get(host, "name"),
            "overall_status": overall_status,
            "alarms_count": alarms_count,
            "cpu_usage_percent": _pct(cpu_used_mhz, cpu_total_mhz),
            "memory_usage_percent": _pct(mem_used_mb, mem_total_mb),
            "storage_usage_percent": _pct(ds_used, ds_total) if ds_total else None,
            "uptime_seconds": uptime_seconds,
            "uptime_days": round(uptime_seconds / 86400, 1) if uptime_seconds else None,
            "vm_count": len(vm_list),
            "maintenance_mode": bool(_safe_get(runtime, "inMaintenanceMode", False)) if runtime else None,
        })
    return {"items": items}

