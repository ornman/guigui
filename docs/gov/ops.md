# Ops 手册(构建 / 发版 / 运行时 / 坑表)

> 治理文档之一。让「构建、发版、装机、排障」四件事在任意会话零上下文可复现。配套:SPEC §2 架构基线、`docs/adr/`(重大取舍)。

## 1. 构建链

`guigui/build_guigui.bat`(仓库根运行,一条链到安装器):

```
venv 自建(.venv-guigui,仓库根)→ pip 安装(requirements + pyinstaller + pytest)
→ pytest 门禁(guigui/tests,不过即停)→ PyInstaller(guigui.spec,onedir,无 UPX)
→ Inno Setup(ISCC 双路径探测:Program Files(x86) 或 per-user LocalAppData)
→ 产物:dist\guigui\guigui.exe + guigui\Output\guigui-setup-*.exe
```

- **bat 必须 CRLF**(cmd 不认 LF-only,曾踩)。
- **ISCC 探测不到 = 跳过安装器不报错**——发安装包前确认 Output/ 有新产物,别被「BUILD OK」骗过。
- 签名步骤未接(挂 ADR-0005):当前 exe 与安装器均未签名。

## 2. 发版

1. 版本号:改 `guigui/setup.iss` 的 `MyAppVersion`(产物名随之);契约版本独立治理,**只有前后端接口变更才 bump 契约**(docs/tech/guigui-bridge-api-v1.md + 变更记录登记)。
2. 走构建链出安装器 → 装机验证(装 → 开启自动登录 → 卸载,四任务应全删,ADR-0004 起)。
3. 官网/反馈侧发布(独立链,site 仓,发布正本 = guigui-guat.pages.dev)。
4. 发版后:动态验收跑一遍(SPEC §3)。

## 3. 运行时面(装机后都在哪)

| 什么 | 在哪 |
|---|---|
| 配置/状态/日志/崩溃记录 | `%LOCALAPPDATA%\GuiGui`(config_v2.json、ensure state、日志、crashlog) |
| 密码 | Windows 凭据管理器,目标名 `学号@GuiGui`(keyring 格式;卸载时 `--clear-creds` 清) |
| 定时任务 | 四个 per-user 任务:`GuiGui`(日历 6 拍)/`GuiGui-Boot`(登录触发)/`GuiGui-Wake`(唤醒触发)/`GuiGui-Patrol`(巡逻);正本语义见 scheduler.py |
| 通知 | WinRT 主通道,powershell 兜底;点击经 `guigui://` 协议唤回 |
| 诊断 | diagnose 信封(采集已进程内化:WMI/NetworkInformation/COM;残余 netsh wlan) |

## 4. 坑表(踩过一次就记,新坑入表)

| 坑 | 症状/教训 | 解法 |
|---|---|---|
| schtasks 输出是 GBK | 中文系统乱码/解码错 | `encoding="gbk"`(代码已处理;COM 主通道后触发更少) |
| 任务 XML 编码 | schtasks 报「无法切换编码」 | UTF-16 带 BOM,声明与文件一致(scheduler.py 注释在案) |
| pytest 不从仓库根跑 | import 失败/夹具不生效 | 一律仓库根 + `.venv-guigui` |
| WinRT 无 IDispatch | InvokeMember 迟绑定调 Toast 失败 | 走早绑定:`Type.GetType("<类>,<winmd>,ContentType=WindowsRuntime")`(ADR-0002 spike 结论) |
| COM LastRunTime 从未运行哨兵 | 文档说 1601,实测 **1999-11-30** | `_fmt_com_time` 按实测哨兵判 None(有测试锁定) |
| 测试真弹 Toast / 真连任务计划 | 跑测试打扰真机 | conftest 安全网:`_toast_never_fires`/`_winrt_toast_off`/`_com_channel_off`,新增通道时补同款 |
| mock 注缝 | 直接赋值 `GG.api.xxx` 无效(GG.api 是 Proxy) | 注缝点 `GGMock.login` 等 mock 自有入口 |
| Mimosa 闸门史 | 2026-09-10 曾拦全部 git commit(客户端 SSRF 误报) | 当日已关;闸门再现先分新账旧账 |
| git 无远程 | push 无处可推 | 本地仓库即正本;重要节点靠 commit 链回溯 |
| 摆拍/截图验收 | show() 后立即 emit 不渲染 | 250ms 延迟后 emit 才算数;pose 帧用独占 scene |

## 5. 回滚

- 代码:git(本地 master 即正本,`git revert`/checkout 到 commit 链节点);**配置与数据不随仓库**——回滚代码不影响 `%LOCALAPPDATA%\GuiGui`。
- 任务:重装/回滚后开一次 GUI,启动对齐(reconcile)自动把任务对到新 rev;对不上时设置页「点此重建」。
