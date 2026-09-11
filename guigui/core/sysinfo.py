"""进程内系统信息查询(ADR-0003)— WMI 与 .NET BCL 的共用采集 seam。

- 查系统状态不 shell-out:ManagementObjectSearcher(进程内 WMI)与
  NetworkInterface.GetAllNetworkInterfaces() 是正规软件的惯例路径,替换
  tasklist/ipconfig/route 的「外部命令 + 文本解析」反模式(审计 S1)。
- 两个 seam 都折成纯 Python 数据(list[dict]),调用方零 .NET 类型泄漏,
  测试注入 dict 假应答即可;失败抛异常,由各采集器按 in-band 语义消化。
- 程序集解析:System.Management 是 .NET Framework GAC 程序集,clr.AddReference
  运行时从 GAC 解析 — PyInstaller 无需(也无法)收集,见 guigui.spec 注释。
- netsh wlan 不在此列(wifictl 明示保留,ADR-0003 决策表)。
"""

from __future__ import annotations

import ipaddress


def wmi_rows(wql: str, scope: str = r"root\cimv2") -> list[dict]:
    """WMI 查询 → list[dict](列名 → 值);任何失败抛异常。"""
    import clr                                    # noqa: F401 — System.* 魔法模块须先装 pythonnet 钩子
    clr.AddReference("System.Management")
    from System.Management import ManagementObjectSearcher
    return [{p.Name: p.Value for p in mo.Properties}
            for mo in ManagementObjectSearcher(scope, wql).Get()]


def net_interfaces() -> list[dict]:
    """全部网卡摘要(NetworkInformation 进程内枚举,含虚拟/断开)。

    dict 键:name/description/type_id/is_wireless/is_up/ipv4/dns/index;
    ipv4 取第一个单播 IPv4(无则 None);index 是 IPv4 接口索引
    (Win32_IP4RouteTable.InterfaceIndex 反查网卡名用),拿不到为 None。
    """
    import clr                                    # noqa: F401
    from System.Net.NetworkInformation import NetworkInterface, OperationalStatus
    out: list[dict] = []
    for ni in NetworkInterface.GetAllNetworkInterfaces():
        props = ni.GetIPProperties()
        ipv4 = None
        for ua in props.UnicastAddresses:
            s = str(ua.Address).split("%")[0]     # IPv6 可能带 zone(%N)
            try:
                if ipaddress.ip_address(s).version == 4:
                    ipv4 = s
                    break
            except ValueError:
                continue
        try:
            index = int(props.GetIPv4Properties().Index)
        except Exception:
            index = None
        out.append({
            "name": str(ni.Name),
            "description": str(ni.Description),
            "type_id": int(ni.NetworkInterfaceType),
            "is_wireless": int(ni.NetworkInterfaceType) == 71,   # Wireless80211
            "is_up": ni.OperationalStatus == OperationalStatus.Up,
            "ipv4": ipv4,
            "dns": [str(a) for a in props.DnsAddresses],
            "index": index,
        })
    return out
