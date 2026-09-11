# ADR-0003:系统信息采集进程内化(外部命令仅兜底/无等价时保留)

- **状态**:提议(技术选型已定,建议采纳)
- **日期**:2026-09-11
- **关联**:审计 R3 / S1 反模式(「把系统 API 当外部命令调」);吸收 ADR-0001 未覆盖的诊断侧全部 shell-out 点

## 背景

诊断与探测层的采集方式全部 shell-out(diagnostics.py / detect.py)。其中 `tasklist /fo csv` 后匹配 `hipsdaemon/360tray/msmpeng` 等杀软进程名(diagnostics.py:215-228)是**教科书级「安全软件侦察」行为特征**——即便产品只输出布尔值,行为引擎看到的是「未签名程序枚举进程并匹配 AV 厂商名」。这是与 schtasks 同源、但观感更差的选型问题:查询系统状态,有一条正规、进程内的路(WMI / .NET BCL),却选了外部命令 + 字符串解析。

## 决策

**原则:进程内 API 优先;外部命令仅作兜底或确无等价时保留。**逐点改造:

| 现状 | 改为 | 说明 |
|---|---|---|
| `tasklist` + 杀软进程名匹配(diagnostics.py:223-227) | WMI `root\SecurityCenter2` 的 `AntiVirusProduct.displayName` | pythonnet `clr.AddReference("System.Management")` + `ManagementObjectSearcher`(进程内 WMI 查询,正规软件惯例)。displayName 映射回 `{huorong, qihoo360, defender}` 布尔,**信封结构不变**;SecurityCenter2 缺失/为空 → 空对象,**不回退 tasklist**(宁缺勿侦察) |
| `powershell Get-ScheduledTaskInfo`(diagnostics.py:332) | COM `RegisteredTask.LastRunTime/LastTaskResult/State` | 随 ADR-0001 一并落地 |
| `ipconfig /all` ×2(diagnostics.py:120/169) | `System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces()` + `IPInterfaceProperties` | 网卡/DNS 信息结构化程度更高,免 GBK 表头解析 |
| `route print -4` ×2(detect.py:40;diagnostics.py:426) | WMI `Win32_IP4RouteTable`(Destination='0.0.0.0') | 默认路由判定 + 出口网卡反查,同一次 WMI 查询覆盖两处 |
| `netsh wlan` ×5(wifictl.py:42/56/88/157/200) | **保留** | Native WiFi API(WlanApi ctypes)工程量大、收益低;netsh wlan 是普遍用法,只有 add profile/connect 是写操作且低频。明示为已接受的残余,不再动 |

## 替代方案

- **全量 shell-out 维持现状**:tasklist 侦察特征与 GBK 解析脆弱性留存——本 ADR 的动因。
- **全部改 ctypes 裸调**:每处都是一次性重写,收益与 ADR-0003 相同、成本翻倍——不选。

## 后果

- 正向:侦察特征消失;采集免文本解析(GBK 表头/CSV 切分),诊断包在非中文系统也更稳;进程创建事件再少 5 类二进制。
- 负向:WMI 查询失败面新增(SecurityCenter2 在服务器 SKU 缺失)→ 按「宁缺勿错」降级为空值;`System.Management` 程序集需确认 PyInstaller 收集(spec 加 hiddenimports 或 runtime hook)。

## 实施清单

1. `diagnostics.py`:`_env_av` 改 SecurityCenter2;`_env_adapters/_env_dns` 改 NetworkInformation;`diagnostics.py:426` 路由反查改 WMI。
2. `detect.py:36-50`:`_default_route_exists` 改 WMI(「探测失败不拦路」语义保留)。
3. `guigui.spec`:确认/添加 `System.Management` 收集。
4. 测试:279 基准全绿;新增 SecurityCenter2 → 三家布尔映射单测(含 displayName 变体);WMI 异常 → 空对象单测。
5. 真机验证:diagnose 跑一轮,诊断包 av/adapters/dns 字段与本机实际一致(对照任务管理器/网络设置人工核)。
6. 契约:无变更(信封字段与类型不变)。

## 验证基准

同 ADR-0001。
