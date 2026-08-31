# 桂桂 v2 打包产物审计 — 2026-08-31

审计范围:PyInstaller 产物(dist/guigui)、Inno 安装器(setup.iss)、卸载链路、
计划任务、凭据、静态资源、安装说明。基线 commit dbb92eb,125 测试全过。
只记录不修复(audit 纪律)。

## 结论速览

| 维度 | 状态 | 关键发现 |
|---|---|---|
| 产物布局/资源 | ✅ | static 落位、dev 排除、字体/vendor/许可齐全 |
| hiddenimports | ✅ | keyring 25.7.0 / pywebview 6.2.1 后端均落地 |
| 任务 XML 生成 | ✅ | schema 顺序、UTF-16、转义、空格路径安全 |
| 卸载链路 | ⚠️ | GUI 运行中卸载/升级撞文件锁(缺 AppMutex) |
| deep link | ⚠️ | GUI 已开时点通知无效(二实例静默退出) |
| 首装守卫 | ⚠️ | saveConfig 对齐路径漏加(uid 空也建任务) |

## P1 — 发布前应修

### 1. setup.iss 缺 AppMutex,GUI 运行中卸载/升级撞锁
- 位置:`guigui/setup.iss` [Setup] 段;互斥量名在 `guigui/app/instance.py:16`(`Local\GuiGui-GUI`)
- 影响:用户开着桂桂点卸载 → guigui.exe 被进程占用,Inno 报文件占用/残留;
  覆盖安装升级(2.0.1)同样撞。卸载全删实测路径是在 GUI 关闭时过的,掩盖了这问题。
- 修:`AppMutex=GuiGui-GUI` 一行(可另加升级前提示关窗)。

## P2 — 应修

### 2. 通知点击在 GUI 已开时无效 — deep link 二实例被吞
- 位置:`guigui/app/gui.py:210-213`(抢锁失败直接 return 0);grep 确认无
  WM_COPYDATA/FindWindow/文件 handoff 任何转发机制。
- 场景:masterToggle 被火绒拦 → task_blocked toast(此时 GUI 多半开着)→
  用户点 toast「去设置」→ 系统拉起 guigui.exe "guigui://settings" →
  单实例锁抢不到 → 静默退出,主窗口毫无反应。GUI 关闭时冷启动则正常。
- 修(低成本):抢锁失败后 FindWindow + SetForegroundWindow 激活已有实例;
  (完整)写 pending-view 文件,由 FileWatcher 既有 2s 轮询消费。

### 3. saveConfig 对齐缺「已配置」守卫 — 首装表单改时间即提前建任务
- 位置:`guigui/app/api.py:224-235` `_align`;对照 `gui.py:180-201`
  `_reconcile_on_start` 有守卫(e247c7c 只加了启动侧,漏了保存侧)。
- 链路:首装 enableDaily 先 `saveConfig({trigger_time})`(index.html:830)
  后 login——保存那一刻 uid="" → reconcile 按 master=True 建任务。用户中
  途放弃表单则每天 06:30 起空跑 6 拍(无感知但违背「任务属于开启那一步」
  契约口径);若被火绒拦,首装页会弹「自动登录还没生效」误导通知。
- 修:`_align` 前同款守卫 `cfg.uid && vault.has_password(uid)`(master 关
  →删任务的逻辑保留)。

### 4. 卸载「彻底清理」只清当前学号凭据
- 位置:`guigui/__main__.py:29-39` --clear-creds 只删 config.uid 对应条目。
- 边界:先手删 %LOCALAPPDATA%\GuiGui 再卸载 → `DirExists=False` 询问都不
  弹 → 凭据无声残留;历史上多学号条目(异常路径产生)同样残留。
- 修:CredEnumerate 枚举 `*GuiGui*` 目标逐条删(win32vault),覆盖任意学号。

## P3 — 记录在案

5. **双进程同写 guigui.log 轮转竞态**(`core/logsetup.py`):GUI 长驻 +
   --ensure 短进程各挂 RotatingFileHandler 同一文件;512KB 轮转时
   os.replace 遇对方句柄 → PermissionError → stderr(无窗=丢失)。仅丢日志。
6. **api.login 重试循环内每轮重读 keyring**(`app/api.py:143`) +
   `build_login_url` 在 try 外(`core/drcom.py:70`):中途凭据管理器被锁 →
   quote(None) AttributeError → 外层兜住报 INTERNAL,不炸但文案不精确。
7. **圆角 keeper 的 GDI 句柄**(`app/gui.py:126-128`):SetWindowRgn 失败时
   CreateRoundRectRgn 的 region 未 DeleteObject,持续失败每 1.5s 泄一个。
8. **非中文 Windows 下按 GBK 解 schtasks/netsh 输出**:errors=replace 不炸,
   仅「英文系统+中文用户名」组合会让 action_target_exists 误判 → 每次启动
   重建任务。桂航定向基本不踩。
9. **WebView2 检测只认注册表**(`setup.iss:54-61`):Fixed Version 分发会误
   弹提示;不阻断,可接受。
10. **每条 toast 冷启一个 powershell.exe**(`core/notify.py`):1-2s/条,
    15min 任务时限内无风险;v1 生产验证通道,不动是对的。

## 验证通过(无需动)

- dist 布局 = `paths.static_dir()` 冻结解析逐字一致(`_internal\guigui\app\static`);
  dev/ 排除生效;fonts(含 OFL 许可)/vendor(confetti、bot 动画及 LICENSE)齐全。
- 任务 XML:RegistrationInfo→Triggers→Principals→Settings→Actions 顺序正确;
  UTF-16 带盘上写盘;全路径 escape(空格/中文用户名安全);Command 走 XML 元素
  不受命令行引号问题影响。
- 卸载顺序:usUninstall(exe 尚在)先 `--clear-creds` 再 DelTree;[UninstallRun]
  任务名与 scheduler.TASK_MAIN/TASK_PATROL 一致;「找不到」幂等删除双向匹配
  (中/英文案)。
- 原子写贯穿(config/state:mkstemp+os.replace);密码只进 keyring,API/日志/
  诊断全打码;CREATE_NO_WINDOW 覆盖全部子进程(schtasks/netsh/route/powershell)。
- 安装器与 dist 同一次构建(15:59:09→15:59:22),无陈旧安装包;.gitignore
  覆盖 dist/build/Output/.venv,无大二进制入库;安装说明无 v1 autostart 残留。
- 125 测试全过;生产 index.html 无 mock 引用,BRIDGE_MISSING 铁律未破。
