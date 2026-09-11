# ADR-0004:卸载生命周期完备(补删全部四个计划任务)

- **状态**:已接受(2026-09-11 纯执行落地;commit 679dd65。安装器重编译因本机无 ISCC 跳过,setup.iss 改动已入库,下次 build_guigui.bat 全链自动生效)
- **日期**:2026-09-11
- **关联**:审计 R5;P1-7 任务拆分的遗漏收尾

## 背景

卸载器只删 2/4 任务(setup.iss:48-51:`GuiGui`、`GuiGui-Patrol`),漏掉 P1-7 拆分新增的 `GuiGui-Boot` 与 `GuiGui-Wake`。默认配置 `boot_login=True`(config.py:71)意味着**默认安装路径下,卸载后必然残留一个指向已删除 exe 的登录触发任务**:

- 产品事故级:用户已卸载,开机却仍有「桂桂」任务在报错(taskschd 面板可见);
- 杀软视角:卸载残留持久化项是安全软件事后清理与「恶意持久化」评分的把柄——与本项目「被拦截重灾区」的整体困境同向叠加。

## 决策

`[UninstallRun]` 补两行,与现有两行同款(`runhidden` + `RunOnceId`):

```
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn GuiGui-Boot /f"; Flags: runhidden; RunOnceId: "DelTaskBoot"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn GuiGui-Wake /f"; Flags: runhidden; RunOnceId: "DelTaskWake"
```

注:卸载器内用 schtasks.exe 属合理(安装器上下文、用户知情、一次性),不在 ADR-0001 的运行时传输层改造范围内。

## 后果

- 正向:默认路径卸载零残留;RunOnceId 保证幂等。
- 已知边界:历史上用旧版卸载器卸载过的机器仍会残留 Boot/Wake(旧卸载器已不存在,无法追溯清理)——接受,在新版「安装说明」不展开;新版起不再产生新的残留。

## 实施清单

1. `guigui/setup.iss` 加上述两行。
2. 重出安装器(`build_guigui.bat` 全链)。
3. 验证:装 → 开启自动登录(4 任务全建)→ 卸载 → `taskschd.msc` 面板确认 4 任务全无。
