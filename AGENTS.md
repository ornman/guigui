# AGENTS.md — Agent 工作约定

## Git 管理规范

**偏好:每次修改后必须 git 提交**

每次修改文件或完成任务后,必须执行 git 操作:

1. 如果项目已有 git 仓库:修改完后立即 `git add` 相关文件、`git commit`(写有意义的提交信息)。
2. 如果项目没有 git 仓库:先 `git init` 初始化仓库,再按第 1 条执行。
3. 提交信息应简明扼要,说明修改的内容和原因。

**Why:** 确保所有变更都有版本记录,便于回溯和协作。

**How to apply:** 在任何本工作区的项目中,每完成一个功能点或一组文件修改后,立即执行 git add + git commit。首次发现项目无 .git 时,先 git init 再继续。

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
