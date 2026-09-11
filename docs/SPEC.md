# 桂桂 · 项目总纲(SPEC)

> **地位**:项目的最高整合文档——产品是什么、系统长什么样、质量线在哪、哪些决策已锁定。各领域的**正本**另有其文(见 §5 文档地图),本文不重复细节,只做基线与入口。任何会话(agent 或人)接手本项目,读完本文即具备全局上下文。
>
> **性质**:常青文档,改即生效;重大取舍不在本文讨论,走 ADR(见 `docs/adr/README.md`)。
> **基线日期**:2026-09-11 · 后端测试 322 绿 · 契约 v1.6.0 · 杀软整改批 ADR-0001~0004 已落地。

---

## 1. 产品是什么

**桂桂**是桂林航天工业学院学生的校园网自动登录工具:用户配置一次学号+密码,此后每天起床时段(默认 07:00,认证服务器 06:50 开门)自动完成 Dr.COM 认证登录,失败时以 Windows 通知如实告知。

- **定位**:桂航学子专属的「复杂小软件」——场景分类 + 冗余设计,不是通用工具。
- **非目标**:不做通用校园网工具、不做托盘常驻、不做 AI 写作类功能(2026-09-10 拍板:伪需求已拆)、不追求跨校适配。
- **用户画像是同一个人**:装机的是学生本人,免管理员、低打扰、可信是硬要求。

## 2. 系统架构基线

```
任务计划程序(per-user,4 任务:GuiGui 日历拍/Boot 登录触发/Wake 唤醒触发/Patrol 巡逻)
   │ 拉起短进程 guigui.exe --ensure --trigger <拍>(无守候、无常驻)
   ▼
core/ 业务层:ensure 状态机 → detect 路由 → wifictl(netsh wlan)→ drcom(登录)
            vault(keyring→advapi32 凭据管理器)scheduler(COM 主通道+schtasks 兜底)
            notify(WinRT 主通道+powershell 兜底)selfheal(rev 对齐)diagnostics
app/ 壳层:gui.py(pywebview/WebView2)+ api.py(js_api 桥,零监听端口)
static/ 前端:8 视图路由,GG 适配器,mock 仅 ?dev=1
分发:PyInstaller onedir(未签名,ADR-0005 待拍)→ Inno per-user 安装器
```

- **传输与集成原则**(2026-09-11 确立):系统 API 走进程内(COM/WMI/.NET,pythonnet 已随栈带入),外部命令仅兜底或无等价时保留(现存保留项:netsh wlan ×5)。
- **数据**:全部落 `%LOCALAPPDATA%\GuiGui`(config_v2.json / ensure state / 日志 / crashlog),原子写;密码只进 OS 凭据管理器,永不落盘、永不下行前端。
- **关键行为红线**:任务命令行与任务 XML 零凭据;URL(含 upass=)永不入日志/结构;学号展示一律打码(mask_uid)。

## 3. 质量基线

| 项 | 基线 | 怎么验 |
|---|---|---|
| 后端测试 | **322 测全绿**(回归底线,变更只增不减) | 仓库根:`.venv-guigui/Scripts/python.exe -m pytest guigui/tests -q` |
| 前后端契约 | docs/tech/guigui-bridge-api-v1.md **v1.6.0** | 改接口必须 bump + 登记变更记录 + 双端适配,禁静默改 |
| 动态验收 | dev/f-final runner:scene 21/21 + route 18/18 + AC 2/2 | 发布/大改后跑一遍 |
| 状态矩阵 | docs/prd/guigui-state-matrix.md | 触达视图/状态的代码改动有**同步义务** |
| QA 视角 | 每个用户承诺都要有验证链(不只验逻辑对) | 评审默认带验收视角 |

## 4. 决策基线(已拍板,不得随手推翻)

推翻任一条 = 新开 ADR + 用户明示拍板,不允许执行 agent 代拆。

| 决策 | 拍板 | 指针 |
|---|---|---|
| 调度机制 = per-user 任务计划(常驻/服务/Run 键/WMI 订阅全否) | 2026-09-07 | 审计 §5;传输层已改 COM(ADR-0001) |
| GUI 栈 = pywebview/WebView2(Qt 迁移实测内存同量级,弃) | 2026-09-06 | Qt 迁移记录 |
| GUI 低频,不托盘;感知面仅通知 | 产品定稿 | PRD §4.5 |
| 免管理员安装(PrivilegesRequired=lowest,HKCU) | 打包期 | setup.iss |
| WiFi 扫描点选,绝不手填 SSID | 产品定稿 | PRD |
| 凭据:密码永不明文落盘、永不下行;学号可下行 | 契约 §0 | bridge-api v1 |
| 首装 = 裸表单一页交钥匙(密码必填) | UX 定稿 | PRD |
| 假期静默 + 开机/唤醒拍豁免(返校日恢复点) | 2026-09-07 | 业务评审记录 |
| AI 写作类功能 = 伪需求,不主动提 | 2026-09-10 | 拆除记录 |
| 工程方向 = 单人 + 全栈 + agent 协作 | 2026-09-10 | docs/gov/ |

## 5. 文档地图(详法见 docs/gov/document-management.md)

| 位置 | 是什么 | 正本职责 |
|---|---|---|
| docs/SPEC.md | 本文 | 项目基线与入口 |
| docs/prd/ | 产品:PRD v2、状态矩阵、业务流程、反馈系统 | 产品语义正本 |
| docs/tech/guigui-bridge-api-v1.md | 前后端契约 | 通信协议正本 |
| docs/tech/ | 技术方案、审计、测试床记录 | 技术快照 |
| docs/adr/ | 架构决策记录(编号,快照) | 重大取舍正本 |
| docs/plans/ | 执行计划(带日期,快照)+ roadmap | 阶段作战文档 |
| docs/gov/ | 治理:SDLC、文档法、提示词模板、ops | 流程正本 |
| guigui/ | 产品代码(含 tests、devshell) | 代码正本 |
| site/ | 官网(独立发布链) | 发布仓正本 |
| legacy-v1/ | v1 全档,**冻结只读** | — |

## 6. 变更流程(详法见 docs/gov/sdlc.md)

需求 → 拍板(产品进 PRD/技术进 ADR)→ 计划(docs/plans/,两件套交付)→ 执行(主会话或 subagent,纯执行可自动接力)→ 验收(§3 质量基线)→ 固化(commit + MEMORY + 矩阵/契约同步)。

## 7. 当前挂账与风险

- **待拍板**:ADR-0005(签名预算)、ADR-0006(停试阈值+文案)、契约 1.6.0 余项、H 表拟稿(见 docs/plans/roadmap-2026-09.md 挂账清单)。
- **已知风险**:全链未签名(审计 S2,最大误报放大器);真机验收欠账(锚点窗口期/bind 解绑/返校日);Dr.COM 明文 HTTP 为协议固有(审计 R8,不可整改)。
