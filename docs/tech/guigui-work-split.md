# 桂桂 v2 · 前后端工作范围划分(T0 纲领)

> **状态**:2026-08-31 定稿,用户拍板。
> **读者**:前端工作流(前端还原 + 桥接契约)与后端工作流(技术方案 + core 实现)两个对话,及后续协作者。
> **地位**:两边的总纲。任何一方开工前先读本文;与本文冲突的局部计划,以本文为准或先修订本文。
> **输入**:`docs/tech/guigui-backend-plan.md`(后端计划)、前端已批准实施计划、`docs/prd/guigui-prd-v2.md` + 原型 HTML(冻结设计基准)。

---

## 一、总原则

1. **一条产品,两条工作流**:前端工作流负责「界面 100% 还原 + 桥接契约」,后端工作流负责「技术方案 + 全部业务实现 + 打包」。两边只在**契约**处交汇。
2. **契约唯一权威** = `docs/tech/guigui-bridge-api-v1.md`(前端起草,后端照实现,用户已拍板)。后端文档 §6「JS 桥接 API」与 §14「前端对接改造清单」**引用契约,不另行定义**;方法名沿用后端计划 §三.6 已草拟的 `probe / identify / login / saveConfig / scanWifi / connectWifi / logs / masterToggle / recentResult`,前端负责补全参数/返回形状/错误码/事件并定稿。
3. **文件所有权**:每个文件/目录只有一个拥有方(见 §三)。发现问题不改对方文件——走 §五 的变更流程。
4. **设计基准冻结**:`docs/prd/guigui-prd-v2.html` 与 `guigui-prd-v2.md` 任何一方都不改。前端还原的对齐目标就是这份原型(演示道具除外,见 §四)。

## 二、产物与节奏

| | 前端工作流(本对话) | 后端工作流(另一对话) |
|---|---|---|
| 文档产物 | `guigui-bridge-api-v1.md`(契约) | `guigui-backend-v1.md`(全文技术方案,见其计划 §二) |
| 代码产物 | `guigui/app/static/**` 全部前端文件、`devshell.py`(开发壳) | `guigui/core/**`、`guigui/app/` 壳与 bridge、cli 入口、`guigui/tests/**`、打包脚本 |
| 顺序 | 契约先落(F0),后端文档 §6/§14 以契约为准对齐 | 全文方案 → 代码(其计划 §一) |

## 三、文件所有权表

| 路径 | 拥有方 | 说明 |
|---|---|---|
| `docs/tech/guigui-work-split.md` | 前端(本文) | 修订需用户确认 |
| `docs/tech/guigui-bridge-api-v1.md` | 前端 | 契约;变更走 §五 流程 |
| `docs/tech/guigui-backend-plan.md` / `guigui-backend-v1.md` | 后端 | 后端方案 |
| `guigui/app/static/**` | **前端** | `index.html`、`app.js`、`mock.js`、`fonts/`、`vendor/` |
| `devshell.py` | 前端 | 仓库根;开发验证专用,**不进打包** |
| `guigui/` 其余全部(`core/`、壳、bridge、cli、tests、spec、iss、build 脚本) | 后端 | 依其计划 §三.4 |
| `docs/prd/**`(PRD、原型、营销站) | 冻结 | 双方禁改 |
| v1 全部(`src/`、`tests/`、`main.py`、`main.spec`、`build.bat`、`setup.iss`、README/CLAUDE.md) | 冻结 | v1 每天在用不动;残留清理是后端收尾待办(其计划 §三.13) |

> 目录名若后端方案定稿时调整(如 `app/static` 改名),由发起方通知另一方做整体迁移,属机械操作不改内容。

## 四、要做 / 不做

### 前端工作流

**要做**:
1. 契约文档 v1:方法签名、参数/返回 JSON 形状、错误码枚举、事件推送(`window.guiguiEmit`)、时延承诺、版本与变更记录规则。
2. `static/dev/mock.js`:契约的可执行规范——模拟后端全部行为(三分支探测、登录成败/被拒/不可达、WiFi 扫描、事件推送、按天日志)。**仅开发**:URL 带 `?dev=1` 才被 `app.js` 动态注入,生产 `index.html` 不引用;后端打包必须整目录排除 `guigui/app/static/dev/`(契约 1.0.1)。
3. 原型移植到 `guigui/app/static/index.html`:删四件演示道具(`.demo` 按钮、假任务栏、`#pill` 胶囊、假壁纸背景),body 改透明承载无边框圆角;内嵌思源宋体 + Inter;**CSS 除 body 背景与 @font-face 外零改动**。
4. `GG` 适配器:三级探测(`window.guigui` → `window.pywebview.api` → mock),后端就位即无缝切真、前端零改动。
5. 视图动态化:硬编码 HTML 换成生成完全相同标记的渲染函数(v-ok/v-login/v-guide/v-main/v-log/v-settings/时间药丸/总开关);**删除原型预填的占位学号密码**(原型头注 P0 安全要求)。
6. 窗口控制调用走 `GG.win`(minimize/close);titlebar 挂 `pywebview-drag` 拖拽类。
7. `devshell.py`:pywebview 加载前端 + mock,验证 WebView2 下圆角/字体/拖拽保真。
8. 保真审计:8 视图 × 关键状态与原型并排比对 + 交互清单 + design-taste 哨兵子集。

**不做**:
- 不写任何业务逻辑:Dr.COM 协议、netsh/WiFi 实操、任务计划、凭据存取(keyring/DPAPI)、通知、调度语义。
- 不建 `guigui/core/`,不写生产 GUI 壳与 bridge 实现(`api.py` 属后端)。
- 不做打包:PyInstaller spec、Inno Setup、图标、版本号、WebView2 检测。
- 不定义磁盘数据格式:`config_v2.json` schema、`ensure_state.json`、日志存储(后端契约消费方决定;前端只消费桥接层形状)。
- 不实现真实窗口行为(最小化/关闭/拖拽的实际效果),只发起调用。
- 不改 PRD/原型/营销站/v1/后端两份文档。

### 后端工作流(摘其计划,以 `guigui-backend-v1.md` 全文为准)

**要做**:全文技术方案(选型论证/进程模型/目录/数据契约/协议模块/状态机/通知/壳/打包/测试/v1 复用清单);随后实现 `guigui/` 全部后端与生产壳;**bridge 严格照契约实现**。

**不做**:
- 不改 `guigui/app/static/**` 与 `devshell.py`(前端拥有);发现问题 → 走 §五。
- 不另行定义桥接 API 形状(文档 §6 引用契约;§14 的「前端改动点清单」仅作对照,实际改动由前端完成)。
- 不改 PRD/原型/营销站;其计划 §五 承诺本轮不写代码、不建 `guigui/` 目录。

## 五、协调与变更流程

1. **契约变更**:任一方要改 → 在 `guigui-bridge-api-v1.md` 改稿 + bump 版本 + 登记「变更记录」→ 通知另一方 → 对方适配完成并回注后才算生效。禁止静默改。
2. **对方文件的问题**:记入契约文档「集成待办」段或直接告知用户,由拥有方修。
3. **git**:只 add/commit 自己拥有的文件(AGENTS 规范:勤提交、有意义的信息);不代提交对方改动。
4. **集成验收**:后端 bridge 就位后,前端 adapter 自动切真(零改动);联调问题按 1/2 处理。

## 六、争议兜底

两边文档或实现冲突时:契约 > 本文 > 各自计划;仍不清 → 用户裁决。
