# 桂桂 v2 后端技术方案 — 工作计划

> **状态**:范围已确认(2026-08-31)——本轮仅沉淀计划,全文技术方案按本计划下一轮展开。
> **输入**:`docs/prd/guigui-prd-v2.md`(§11 四问)+ `guigui-prd-v2.html`(8 视图原型,已定稿)+ v1 代码考古(可复用资产清单)。
> **本轮拍板**:交付物 = 技术方案文档;技术栈 = Python 3.12 + pywebview(WebView2)。

---

## 一、已锁定决策(用户拍板 + 既有约束)

- **交付物**:一份后端技术方案文档,回答 PRD §11 列的四问(选型 / 改造策略 / 打包 / 测试)。代码下一轮。
- **技术栈**:Python 3.12 + pywebview(WebView2 后端)。HTML 原型经 `js_api` 桥直接变成真 GUI。
- **架构基线**(PRD AC-05/06 锁死,继承 v1 三层分离):GUI 短进程 + Windows 任务计划触发 `--ensure` 短进程 + 文件交接(config/state/log),无守护进程、无托盘。
- **v1 共存**:v1 每天在用不动;v2 代码规划为本仓库新顶层目录 `guigui/`(文档里写明,本轮不建)。

## 二、产出文件

`docs/tech/guigui-backend-v1.md`(中文,对齐 `guigui-prd-v2.md` 的文档风格)

## 三、文档章节与每章要解决的事

1. **范围与读者** — 对应 PRD §0 的镜像声明(本文件只答"怎么做")。
2. **选型论证** — Python+pywebview 主选理由(v1 资产复用率、单用户工具迭代速度);否决项及理由:Tauri(协议重写踩坑)、C# / Electron(重写 / 体积违背 AC-05);依赖清单(pywebview、keyring、pytest、PyInstaller,登录仍走 stdlib urllib)。
3. **进程与自动化模型** — 三执行形态:GUI 短进程 / `guigui.exe --ensure` 短进程 / 文件交接。L1–L5 任务计划落地:L1 = Daily 任务起点 **T−30min** + 每 5min 重复共 6 次(06:30–06:55,任一成功即停;窗口公式按"起点语义"重定义,修复 v1 `center±window/2` 反向 bug);L2 = AtLogon;L3 = 独立巡逻任务;L5 = EventTrigger(Power-Troubleshooter 唤醒事件)+30s;L4 不是任务、是 ensure 内部策略(不可达 → 兜底 SSID)。总开关 = 任务禁用/删除 + selfheal 幂等对齐(继承 v1)。
4. **目录结构** — `guigui/` 规划:`core/`(drcom、detect、ensure、wifictl、scheduler、selfheal、notify、vault、config、logstore、instance)、`app/`(gui 壳、bridge、static 前端)、`cli` 入口、`tests/`。
5. **数据契约** — `config_v2.json` 全字段 schema(PRD §5 全部设置项 + L1–L5 开关 + 总开关 + 显示桂桂);密码存 **Windows 凭据管理器(keyring/DPAPI)**,config 不落密;`ensure_state.json` v2(通知去重 + 连续不可达天数计数 + last_result 供主页"昨晚"行);日志存储按天可分组、级别 OK/WARN/FAIL、学号打码、预留过滤/导出(AC-07)。
6. **JS 桥接 API** — `window.guigui.*` 方法签名清单(probe / identify / login / saveConfig / scanWifi / connectWifi / logs / masterToggle / recentResult …)+ 探索得出的 **24 项后端能力 → 方法 → 视图**映射表。
7. **Dr.COM 协议模块** — 复用 v1 `src/login.py:91-128` 全部细节(GET /drcom/login、JSONP、GBK、UA/Referer、`0MKKey=123456`、`result==1`);新增 `chkstatus` 学号识别 + 运营商后缀表从服务器拉取(修 v1 硬编码);错误分类(logged_in / not_logged_in / unreachable 细分 refused/timeout / 密码被拒 result!=1+msga / 维护中)。
8. **状态机与假期静默** — 连续 48h 不可达 → 降频每天 1 次 + 不通知 + 日志天头标"假期静默";回校自动恢复(AC-10)。
9. **通知** — 继承 v1 ensure 状态翻转去重;每日"断→通"仅 1 次(AC-04);连败 ×3;正常/维护/静默永不通知;点击路由激活 GUI 对应视图;实现选型(windows-toasts vs v1 PowerShell WinRT)写明取舍。
10. **GUI 壳与"胶囊"悬案** — pywebview 560×640 无边框;伪透明按原型烘焙方案落地,Mica 作可选增强(ctypes DWM);AC-08 的 0.6s 口径解释为"窗口可见后直达主面板",冷启动预算单独给。**明确解决 PRD 内部张力**:胶囊浮标需常驻 vs AC-05/06 反常驻 → 给两方案(默认:关闭=真退出,唤回=快捷方式/通知点击;可选:独立微进程胶囊)并给推荐。
11. **打包分发** — PyInstaller onedir(单 exe 双模式:`guigui.exe` / `guigui.exe --ensure`)、Inno Setup、WebView2 Runtime 检测;AC-05 内存实测口径(ensure 短进程 pythonw ~20MB)。
12. **测试与发布** — 单测(协议 mock / 新窗口公式 / 静默状态机 / 通知去重)、集成(任务 XML 生成解析)、**AC-01~AC-10 逐条映射验收步骤表**。
13. **v1 复用/重写清单**(带文件:行号)+ v1 文档残留清理项(README autostart/--silent、CLAUDE.md auto_start)列入 v2 收尾待办。
14. **开放问题** — L1 六拍止于 T−5、T~T+30 区间靠 L2 AtLogon 兜底的产品解释;日志过滤/导出 UI 回补;前端对接改造清单(原型 demo 函数/mock 换真桥接的改动点列表,仅列不做)。

## 四、收尾

- 全文文档完成后 `git add docs/tech/guigui-backend-v1.md` 单独提交,不触碰工作区其他未提交改动。

## 五、本轮不做

- 不写任何 v2 代码、不建 `guigui/` 目录、不改 PRD / 原型 / README(清理项仅记录)。
