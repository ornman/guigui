# ADR-0002:通知通道 WinRT 化(pythonnet 直调,powershell 降为兜底)

- **状态**:提议(建议采纳;实施前 spike 前置,见「实施清单」第 0 步)
- **日期**:2026-09-11
- **关联**:审计 R2 / S4(自救链单点)

## 背景

全部 Toast 通知走 `powershell -ExecutionPolicy Bypass -Command <内联 PS 脚本>`(notify.py:41-76)。两个问题:

1. **每次通知起一个 powershell 子进程**——`-ExecutionPolicy Bypass` 是杀软对未签名父进程的经典启发式特征(比 schtasks 频率更高:每条通知一次)。
2. **自救链单点(S4)**:「安全软件拦住了定时任务的创建…把桂桂加入信任区」这条自救指引(task_blocked,notify.py:82-92)**本身也走 powershell**——若杀软拦的是 powershell 子进程,自救指引发不出来,只剩 log.warning,用户彻底失联。

通道本质是 v1 移植:PS 脚本里激活的也是 WinRT `Windows.UI.Notifications`——说明目标 API 从来就是 WinRT,选 powershell 只是当时零依赖的捷径。

## 决策

1. **主通道**:pythonnet 进程内直调 WinRT Toast(`ToastNotificationManager::CreateToastNotifier` + `ToastNotification`,AppId 维持 ShellExperienceHost 现值,协议点击降级逻辑不动)。
2. **兜底通道**:现 powershell 路径保留为降级(WinRT 激活失败时),通知语义「永不抛异常、失败只记日志」不变。
3. **spike 前置(第 0 步)**:pythonnet 3.x 对 WinRT 类激活的可用性**尚未实测**(与 ADR-0001 的 COM 探针不同,此处没有实证)。spike 结论回填本 ADR:
   - 若 pythonnet 直激活不通 → 备选 A:纯 ctypes 走 `combase!RoGetActivationFactory` + HSTRING(无依赖,~150 行,社区成熟范式);
   - 备选 B:vendor winsdk(正规但增体积);
   - 三者皆不通 → 维持现状并关闭本 ADR(如实记录)。

## 后果

- 正向:通知主链不再 spawn 子进程;自救指引可用性与主链解耦(powershell 只在 WinRT 失败时才用);每条通知少一个进程创建事件。
- 负向:WinRT 激活兼容面需 spike 实证(Win10 1809+ 均有 ToastNotificationManager,风险低但未证);多一层封装。
- 不变:通知种类/去重决策(decide_notify 纯函数)、文案、guigui:// 协议链。

## 实施清单

0. **spike**(半小时级):`.venv-guigui` 下验证 pythonnet 能否激活 ToastNotificationManager 并发出一条真实 Toast;不通则按备选 A 走 ctypes 探针;结论写回本节。
1. `notify.py`:`send()` 改双通道结构(主 WinRT / 兜底 powershell),`_xml_escape` 与 Toast 模板拼装复用。
2. 测试:现有 notify 相关用例全绿;新增「主通道失败 → powershell 兜底被调」单测。
3. 真机验证:dev 模式手工触发 task_blocked/recovered 各一条,通知中心可见、点击路由正确。

## 验证基准

同 ADR-0001(仓库根 pytest;279 基准)。
