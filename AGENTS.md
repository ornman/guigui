# AGENTS.md — Agent 工作约定

## Git 管理规范

**偏好:每次修改后必须 git 提交**

每次修改文件或完成任务后,必须执行 git 操作:

1. 如果项目已有 git 仓库:修改完后立即 `git add` 相关文件、`git commit`(写有意义的提交信息)。
2. 如果项目没有 git 仓库:先 `git init` 初始化仓库,再按第 1 条执行。
3. 提交信息应简明扼要,说明修改的内容和原因。

**Why:** 确保所有变更都有版本记录,便于回溯和协作。

**How to apply:** 在任何本工作区的项目中,每完成一个功能点或一组文件修改后,立即执行 git add + git commit。首次发现项目无 .git 时,先 git init 再继续。

## 改动纪律(不确定不动手)

**偏好:用户所指的 UI 元素在代码里找不到时,先问清落点,绝不凭推测改**

1. 用户报告 UI 问题或指某段文字时,先定位到用户所指的**确切节点**再动手。
2. 静态 HTML 里 grep 不到那段文字 ≠ 不存在:文案可能来自后端信封 / JS 动态渲染(错误提示、状态文案、日志),先搜数据源(后端 message、mock、JS 的 textContent 赋值点)再下结论。
3. 定位不到就停下向用户确认,不要选一个「看起来合理」的位置自己发挥;改错位置等于改了两次。

**Why:** 2026-09-06 自助服务平台链接:用户指的是登录被拒提示里的「去自助服务平台看看绑定」(drcom.rejection_text 经信封 reason='bound' 动态渲染),agent 在静态 HTML 里 grep 不到该文字,便自作主张在设置页加了一整行入口,被用户打回重做。

**How to apply:** 动 UI 前先走完定位链:静态 HTML → 动态文案(JS / 后端 / mock)→ 仍找不到 → 问用户。宁可多问一句,不猜着改。

## 设计品味(Design Taste)

桂桂营销页阶段已装五条前端 skill(Source: `Leonxlnx/taste-skill`,落地于 `C:\Users\ASUS\.agents\skills\`):

- `gpt-taste` — AIDA + GSAP ScrollTrigger + 巨间距 + bento
- `imagegen-frontend-web` — 每 section 一独立横图,共用调色板
- `high-end-visual-design` — 双壳嵌套 + 浮岛导航 + $150k agency 美学
- `design-taste-frontend` — 反 slop 通用哨兵,不动风格,只挡通用稿
- `image-to-code` — 视觉重要任务先出图再写码

**调用顺序**(每次做营销页或大视觉改动):

1. 出图分析 → `image-to-code` / `imagegen-frontend-web`
2. 视觉细节 → `high-end-visual-design`
3. 整体节奏 → `gpt-taste`
4. 最后防 slop 自检 → `design-taste-frontend`

**Why:** 五条已实测可被 Skill 工具加载;源 `npx skills add` 需要 TTY 多选,在本环境只能手动 git clone 后拷贝。

**How to apply:**

- **gpt-taste 与 high-end-visual-design 互有张力**:两者都禁通用字体/线性缓动(一致),但在"间距大小"与"按钮嵌套"上会拉扯。每次产出前先选一个为主调,另一个降级为参考,避免 ZCode 来回拉锯。
- **high-end-visual-design 不管中文字体**——它只锁拉丁字体(禁 Inter/Roboto/Geist/Clash Display 等),中文审美仍需项目层自己定(推荐伴侣:得意黑 + 思源宋体,待定)。
- **imagegen-frontend-web 与 image-to-code 都假设"先出图再写码"**——ZCode 本环境无生图工具,这两条目前产出会落到"图描述 + 设计规范",图本身得另做。
- **imagegen-frontend-web 强制每 section 一独立横图**,不适合密集短 section 共用背景的页面——那种需求需要先放宽这条。
- **严格遵循 AGENTS.md 的 Git 规范**:新增/修改了 skill 引用说明后,立即 `git add` + `git commit`。
- **产品主原型(8 视图 / 表单 / 设置 / 日志)不在 design-taste-frontend 的「适用」范围**(见该 skill §13 — NOT for dense product UI / dashboards)。它针对的是 marketing landing 与 portfolio。**产品原型阶段的修复只用其「哨兵」子集**:§9.G em-dash 全禁 / §6.B prefers-reduced-motion 全清 / §6.A 只动 transform+opacity / §4.5 button contrast / §9.A 禁纯黑纯白 / §9.F 禁版本号徽标 / §9.F 禁 scroll cue / §4.4 shape consistency。**跳过**:Hero 适配 / bento / GSAP sticky-stack / logo wall / serif discipline / premium-consumer palette(那些针对 marketing 页)。2026-08-31 PRD bot 拆分(commit dae62fd ~ 0ccf93e)即按此口径自检通过。

## 图表工具(archify)

`archify`(MIT,Source: `tt-a1i/archify`)已装于 `C:\Users\ASUS\.agents\skills\archify`(2026-09-06 安装;本机 git 代理 127.0.0.1:7890 失效时 GitHub 直连不通,经 `gh-proxy.com` 镜像 clone)。

**用法**:写类型化 JSON(workflow v2 / lifecycle / architecture / sequence / dataflow,schema 在 `skills/archify/schemas/`)→ `node bin/archify.mjs validate <type> <json> --quality showcase --json` 迭代到 0 诊断 → `deliver <type> <json> <html> --quality showcase`(产物=自包含交互 HTML,冻结规格并记 SHA-256 收据)。桂桂业务流程图源在 `docs/prd/flows/*.json`(2026-09-06 三张全 showcase)。

**踩坑记录**(2026-09-06 实测):

- lifecycle 的「事件/终态泳道」列号是**相对映射**:事件列 0..2 对齐主轨列 2..4 正下方,不当绝对列用;异常态挂在其源状态正下方、回环走页边距是渲染器最吃的布局语言。
- workflow 泳道+列决定落位;col4-5 走廊最易拥堵,删低价值边永远优先于加路由控制。
- via 角点必须与端口坐标**逐像素对齐**(差 2px 就出斜线段被 orthogonal-arrows 拦下);`labelAt` 是中心点语义,标签放泳道间空带最稳。
- `visual-check` 需要本机 Chrome,本机没有 → 按交付契约如实记「环境跳过」,不强求。
