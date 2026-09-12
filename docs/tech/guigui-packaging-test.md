# 桂桂 v2 · 打包测试报告(2026-08-31)

> 注:2026-09-12 开源脱敏,文中实测个人值已替换为同格式假值。

> 阶段:前端定稿(commit 1bb4083)后的打包测试。产物:`dist/guigui/`(onedir)。
> 结论:**打包链路可用**,双模式(--ensure / GUI)实测通过;真实首装由用户本人在打包窗口内完成并复验通过。遗留:火绒放行、Inno 未装、图标未定(见 §6)。

## 1. 构建管线(build_guigui.bat)

流程:venv(`.venv-guigui`)→ pip install(requirements.txt)→ pytest(120 passed)→ PyInstaller(guigui.spec,onedir,console=False)→ 可选 ISCC。

修了两轮才跑通,教训:

| 问题 | 现象 | 修复 |
|---|---|---|
| 行尾 | 纯 LF 的 .bat,cmd 逐行解析错乱(`'p0..'` 乱码命令) | 全文转 CRLF + `chcp 65001` 前置 |
| 转义 | python heredoc 内 `guigui\requirements.txt` 的 `\r`/`\g` 被当转义序列(`guiguiequirements.txt`、SyntaxWarning) | heredoc 改 raw string `r"""..."""` |

## 2. 产物核验

- `dist/guigui/guigui.exe` 存在,目录 ≈55MB(WebView2 运行时由系统提供,不打进包)。
- static 打进 `_internal`:GUI 正常加载(实测见 §4);`dev/` 递归排除(契约 1.0.1 要求)。
- 打包 `--ensure`(空配置):rc=0,日志一条「未配置凭据,跳过」,不弹窗、不写任务 —— 单 exe 双模式按设计工作。
- 圆角:`SetWindowRgn` 成功(guigui.log 无「圆角裁剪失败」告警);全屏截图实测四角透出桌面/IDE 内容、零白边。
  ⚠️ **窗口本体截图(capture_app)会把 RGN 裁掉的四角填纯白** —— 是捕获伪影,不是白角回归;判白角必须看全屏合成,勿看窗口直拍。
- 内存(AC-05 口径,工作集):guigui.exe ≈121MB + msedgewebview2(单子进程)≈151MB,**合计 ≈272MB**。
- × 关闭:winClose → destroy,后台任务退出码 **0**,WebView2 子进程全部回收。

## 3. 真实首装(2026-08-31 09:26,用户本人在打包窗口完成)

这不是注入的测试数据 —— 是用户拿真实学号密码走的产品流程,等效一次真机验收:

- 学号自动识别:`/drcom/chkstatus` 抓到真实学号 → 表单预填 + 「学号已识别 ✓」(契约 §2.2 identify)。
- 提交:`saveConfig`(config_v2.json 落盘,uid=2025…0001)→ `login` → 探测已登录 → 短路 settle(ensure_state:`last_result outcome=ok, tries=0`;日志「网络可达」「已登录 · 2025…0001」「今天到这就下班啦 ☕」)。
- 密码入 Windows 凭据管理器(service `GuiGui`,cmdkey 可见);**config 先写、密码先存,再走短路** —— api.login 顺序无漏洞(代码复核 + 实测一致)。
- 复验:probe → `configured:true`(下次启动直进日常页)。
- 任务注册:火绒拒绝(schtasks「拒绝访问」),selfheal 诚实记 ERROR 日志、无崩溃、无重试风暴 —— 失败路径符合设计。
- 空密码校验:同窗口先点过一次空密码 → 「密码还没填呢」警告 + 焦点回密码框,正常。

**数据迁移备忘**:该首装当时落在我测试注入的 `GUIGUI_DATA_DIR=%TEMP%\guigui-pkg`,系统清临时目录会丢;已于 09:32 复制到正式位置 `%LOCALAPPDATA%\GuiGui`(config/ensure_state/logs),vault 条目在凭据管理器、不受数据目录影响。TEMP 原件未删。

## 4. GUI 双次启动行为

| 次 | 时间 | 数据态 | 路由 | 判定 |
|---|---|---|---|---|
| 1 | ~09:15 | 无 config | (观测受跨窗口 a11y 污染,存疑) | 见 §5 |
| 2 | 09:23:26 | 无 config | v-boot → v-ok 裸表单(学号预填) | ✓ 正确 |
| — | 09:26:40 | 首装完成 | (用户操作:表单 → 庆祝) | ✓ 正确 |
| 复验 | 09:30 | config+vault | probe `configured:true` | ✓ 正确 |

## 5. 观测备忘(非阻塞,复测时别踩)

- **跨窗口 a11y 污染**:同屏存在多个 Edge 内核窗口时(另一对话的 devshell),对 pid X 的 get_app_state 会混入其他窗口的 DOM 文本 —— 曾据此误判「无配置进了 v-main」。复测(单窗口)为正确 v-ok;代码侧复核无自动路由路径(`reProbe` 仅 v-guide 手动链接调用)。**教训:桂桂窗口的 a11y 断言必须在单窗口环境做。**
- **CUA bounds 漂移**:对该圆角窗口的 bounds 读数会在 [288,288]→[416,471]→[160,160]→[1678,311] 间跳(疑似 DPI 虚拟化 + RGN 影响),以全屏截图里的实际位置为准。
- 像素点击照旧会被 bot 微动画判 stale;操作走 a11y element(AXPress/set_value)。

## 6. 遗留与下一步

| 项 | 状态 | 谁做 |
|---|---|---|
| 火绒放行 guigui.exe(建任务) | 待用户在火绒加白;放行后任意一次 saveConfig/masterToggle 会自动补建任务(selfheal) | 用户 |
| AC-01 真机全链路(任务触发登录) | 依赖上条 | 后端复测 |
| Inno Setup 6 | 未安装;`setup.iss` 已就绪,装后 `ISCC setup.iss` 出 `guigui-setup-2.0.0.exe` | 可选 |
| 应用图标 | spec `icon=None` | 待设计资产 |
| 任务计划残留 | GuiGui 系任务全机零条(创建本就被火绒拦);v1 `SchoolAutoLogin` 保留 | 已完成 ✓ |
