# 前端交互重构计划(审计修复 + 交互规范 + 架构收口)2026-09-09

> **状态**:已拍板,待执行。
> **输入**:2026-09-09 四视角审计(产品/交互工程/用户/UX)+ 内置浏览器逐场景实测,10 个实锤问题(4 P0 / 4 P1 / 2 P2 级)。
> **拍板记录**(2026-09-09,用户四问拍板):
> ① waiting 态修法 = **排查页感知 waiting**(不新增主页第四态);
> ② 架构收口范围 = **三件全做**(表单合一 / 路由数据化 / store 收口),不拆文件;
> ③ 拦截终态页 = **加 quiet 次按钮「先不管,回主页」**;
> ④ 事件打断策略 = **填表中不打断**(表单有已键入内容时,unreachable 事件不拽人去排查页,就地状态行;终态页/详情页维持统一跳)。
> **用户追加要求**:交互工程师视角必须详细到可执行——本文 A 章(交互规范八条)即该要求落成的「宪法层」,B/C/D 执行项逐条挂靠 A 章。
> **拍板记录第二批**(2026-09-09 晚,用户业务流程图评审):
> ⑤ **开门判断全局删除**——waiting 前端视同不可达,唯一落点 v-guide;bootWait 等门页删除,06:50 文案全部下线(P0-3 改写,P0-8 作废);
> ⑥ 节流分支由 agent 补进流程正本(B);
> ⑦ 登录页保留返回键;日常被拒分流:密码不对/学号运营商错→提示进登录页;绑定受限/学号在别设备→状态页提示「是否更换账号?」,不换→返回日常页(C);
> ⑧ **大头状态页(非首装独有,全屏红,bot 沮丧)与横幅并存**,登录页返回落点=带错误横幅的日常页;5s 探测=10.1.2.3 连通性检查不触发登录(D/P1-10);
> ⑨ 验证器专用计划任务机制**先不管**(park,G 章);后端 diagnose 已做过,入口不重做;
> ⑩ 用户业务流程图(飞书白板 PDF 矢量解析)作为前端业务流程**正本**;agent 画的 as-is 图降级为审计底稿;白板节点颜色语义=淡紫「页面显示」/灰「状态·后端动作」/黄「决策注释」/线上小胶囊「边标签」。

---

## 执行约定(新对话零上下文必读)

1. **对象文件**:`guigui/app/static/index.html`(下称「主文件」,1689 行:CSS ~469 / HTML ~265 / JS ~950)、`app.js`(桥接,60 行,基本不动)、`dev/mock.js`(契约 mock,只读参照)、`dev/state-gallery.html`(摆拍画廊,同步义务)。
2. **定位方式**:本计划引用的行号是 2026-09-09 审计时点,**执行时以函数名定位**(如 `quickLogin` / `renderBanners` / `net:state` 处理器);动手前先重读主文件相关段——**用户会亲手改文件试文案,以磁盘上现状为准**。
3. **测试基准**:
   - 内置浏览器(或 devshell)开 `http://…/index.html?dev=1&scene=<场景>`;mock 场景全集见 `dev/mock.js` 头注(ok/out/down/waiting/daily/rejected/bind/limit/throttled/blocked/fbdg/other/unverified/ladder_fail/ladder_back/beforeopen/diag_ok/diag_cred/diag_task/diag_app/streak);
   - `dev/state-gallery.html`(http 打开,非 file://)全帧过目;**改到的帧必须重拍**;
   - 网络切换用 `GGMock._setNet(state, ssid?)` 全链真跑(改 mock 数据源,后续 login/probe 随动)。
4. **契约纪律**:桥接契约 1.5.0 **本轮不动**,0 行 Python。执行中若发现必须动契约(如需要新信封字段),停下单独拍板,不顺手改。
5. **不顺手修**:只修本计划列出的问题;过程中发现新洞记到本文 G 章 backlog,不动手。
6. **文案拟稿制**:标「拟稿」的文案执行时先落拟稿,全部完成后**汇总一张表请用户过目定稿**(先例:5bd0910 横幅③拟稿)。拟稿汇总见本文 H 章。
7. **git**:每完成一项(或一组强相关小项)立即 `git add` + `git commit`,直接提交 master,信息格式 `fix(ui)/refactor(ui): 条目号 一句话(计划 ui-interaction-rework-2026-09-09)`。
8. **摆拍铁律**:`show()` 的 `.on` 有 250ms 延迟,**emit/断言必须延后 250ms**;pose 帧用独占 scene;画廊依赖全局函数入口(白名单见 D.3)。
9. **视觉不变原则**:P2 架构重构**不得改变任何像素级渲染**;重构前后 gallery 同帧截图对照。
10. **验收总门**见 F 章,全部通过才算闭环。

---

## A. 交互设计工程规范(宪法层——B/C/D 执行项的依据)

> A 章不是独立执行项,而是把审计中暴露的「洞为什么会长出来」固化成规则。每条 = 病灶(实测/代码定位)→ 规范 → 实现落点 → 验收。

### A1 反馈生命周期(main-lede 所有权)

- **病灶**:`main-lede` 有 4 个写入者(`renderMain` / `setAuto` / `quickLogin` 三处),无所有权约定,后写者胜。实测:点「立即重新登录」成功文案「刚刚把网帮你接回来啦 ✓」在 **82ms** 出现、**162ms** 被 `renderMainData→setAuto` 回写覆盖——成功反馈等效不存在。这正是 937b8a0 修过的「点击即切假成功」的残留变体:当时修了「提前切」,没修「切了被数据回填吃掉」。
- **规范**:lede 消息只分两类——
  1. **基线态**:由 `mainState` + 配置派生(「网的事交给我,你放心忙~」),唯一写入者是 `renderMain`/`setAuto`;
  2. **瞬时反馈(flash)**:动作结果的直接回话(成功/已在线/出错),默认 **4s**,后到覆盖先到,到期自动回基线。
  任何写入者在写基线前必须检查 flash 是否未过期;flash 未过期时**基线让位**。
- **实现**:新增 `flashMainLede(text, ms=4000)` 唯一入口:写 lede + 记 `S.flashUntil`(P2-3 落地前进全局变量)+ `setTimeout` 到期调 `renderMain()` 恢复基线;`renderMain` 与 `setAuto` 写 lede 前置守卫 `if(Date.now()<flashUntil) return`。`quickLogin` 的三处 lede 直写全部改走 `flashMainLede`。
- **验收(AC-1)**:「再登一次」成功 → 成功文案稳定显示 ≥4s;期间手推 `net:state` 不吞它;4s 后自动回基线;逐帧采样不再出现 <200ms 消失。

### A2 忙碌/防重矩阵

- **病灶**:防重现状一张纸糊——有 busy:`main-btn`/`login-btn`/v-ok 主按钮/`reProbe`/成功页重建/`fb-send`;**无 busy:`pickWifi`(SSID 点击可连点)、横幅②就地重建(只换文案)**。且 busy 窗口靠响应延迟撑着:`NOT_CONFIGURED` 路径 mock 零延迟返回,实测快速双击 login 调用 ×2——防重靠时序巧合,不是逻辑保证。
- **规范**:
  1. 凡 `await GG.api.*` 的点击入口必须过 `setBusy`;
  2. `setBusy` 增加 `minMs=400`:恢复时若实际 busy 时长不足则补足——**防重是时间下限保证,不赌网络延迟**;
  3. 视图转场期间(`show()` 的 250ms 窗口)旧视图 `pointer-events:none`(`.leaving` 类补这条),消灭「转场动画期连点穿页」。
- **实现**:`setBusy(btn,on,text,minMs)`;`pickWifi` 点击后给 `.ssid` 项加 busy 样式至 `connectWifi` 返回;`rebuildTaskBanner` 同理;`.v.leaving{pointer-events:none}`。
- **验收(AC-2)**:NOT_CONFIGURED 场景双击 `main-btn`,`GGMock.login` 调用计数 = 1;down 场景连点 SSID,`connectWifi` 调用 = 1。

### A3 事件打断策略(net:state 何时允许换页)

- **病灶**:统一路由(09-08 拍板「断网统一落 v-guide」)的副作用:**用户填表填到一半,unreachable 事件把人拽去排查页**。表单数据虽保留,但心流和「填到一半」的位置感已断——系统事件打断用户任务,交互反模式。
- **规范(拍板④细化)**:引入 `formDirty` 维度(表单合一后 = 学号或密码框任一非空):
  - `unreachable` + `formDirty` + 表单视图 → **不跳页**;状态行就地转 danger「10.1.2.3 · 连不上」(`syncLoginStatusLine` 已具备),提交按钮照常(保存配置语义本就允许断网提交);
  - `unreachable` + 空表单 / 终态页 / 详情页 → 维持统一跳 v-guide(09-08 拍板不动);
  - `waiting` → **任何视图都不跳**,按 B-P0-3 文案规范就地渲染(P0-3 是 A3 的第一个受益者)。
- **实现**:此规范在 P2-2 数据化时固化为路由表的一列;P0 阶段先在 `net:state` 处理器加 `formDirty` 早退分支(注明「P2-2 迁移」)。
- **验收(AC-3)**:v-form 填入学号后 `_setNet('unreachable')` → 停留表单、状态行 danger、可提交保存配置;清空表单后同样事件 → 跳排查页。

### A4 出口完备性(死胡同审计)

- **病灶**:拦截终态页唯一出口「重建定时任务」,失败无限循环,唯一逃生是标题栏 11px 小字(无视觉暗示可点)。
- **规范**:每个视图 ≥1 个**可见**出口;终态页 = 主出口(动作)+ 可选次出口(退出);自绘下拉补 **Escape 关闭**(外点关闭已有)。
- **实现**:拦截页加 quiet 次按钮(C-P1-1,拍板③);`document` keydown Escape → 收起 `.dd.open` 并把焦点还给 `.dd-btn`。
- **验收(AC-4)**:gallery 每帧可见出口 ≥1;dd 打开后按 Escape 收起、焦点回按钮。

### A5 焦点管理

- **病灶**:`show()` 换视图零焦点处理;键盘/读屏用户不知道页面换了,Tab 从头开始摸。
- **规范**:视图切换完成后把焦点移到新视图 h1(补 `tabindex="-1"`,CSS 去掉该聚焦 outline);控件补齐 aria 态:密码眼睛 `aria-pressed`、下拉按钮 `aria-expanded`。
- **实现**:`show(id)` 的 250ms 回调尾部 `$('…h1').focus()`(各视图 h1 统一加类 `.v-title` 便于选择);`togglePw` 同步 `aria-pressed`;dd 开合同步 `aria-expanded`。
- **验收(AC-5)**:切换视图后 `document.activeElement` 是目标视图 h1;读屏播报新页标题。

### A6 键盘可达

- **病灶**:43 个 inline `onclick` 里混着 `div onclick`(三条主页横幅、SSID 项)——键盘永远够不到「重建定时任务」「完整排查」这两个关键动作;自绘下拉无 Escape。
- **规范**:`div onclick` 的可点元素一律 `button` 化(浏览器默认样式重置回同形);dd 菜单项本就是 button(Tab 可达),补 Escape 即可。**明确不做**:完整 ARIA combobox roving-tabindex 模式——本产品 6 项静态菜单,过度设计。
- **实现**:横幅容器输出 `<button class="banner">`(样式微调去默认边框底色);SSID 项保持 div 但补 `role="button" tabindex="0"` + Enter/Space 键处理(列表项语义比按钮合适)。
- **验收(AC-6)**:Tab 遍历主页,三条横幅均聚焦可达、Enter 触发;SSID 列表键盘可选。

### A7 状态可见性(同屏信号矛盾消解)

- **病灶**:scene=ok 回主页同屏四信号打架——横幅①「密码还没验证过,去改一下」+ 最近结果「今早第一次就登好了 ✓」+ 网络行「已连上 ✓」+ 日志「已登录」。根因:`renderBanners` 只看 `rec.verified`,不看当前网态;契约 mock 的 `already` 路径 `verified` 不翻转 → **长期在线用户横幅①永挂**,每天被劝做最贵的动作(重输密码)。
- **规范(叙事分层)**:标题=现在的结论;状态行=证据;横幅=待办;最近结果=历史。同一屏不允许两条「现在」互相拆台。落地为一条判定规则:**横幅描述的「待办」必须与当前网态自洽——已在线时不存在「密码没验证」的待办**(验证需要把自己踢下线,不是待办是自残)。
- **实现**:`renderBanners` 横幅①条件追加 `&& !(lastNet && lastNet.state==='logged_in')`;横幅③文案口径见 C-P1-4。
- **验收(AC-7)**:scene=ok 主页无横幅①;scene=streak 主页标题(掉线)/状态行(还没登录)/最近结果(今早✓,历史)三者时态自洽。

### A8 动画时序单源

- **病灶**:转场 250ms 写了两份——JS `setTimeout 250` + CSS `.leaving{animation:fadeout .25s}`。改任何一边,另一边静默烂掉;而 state-gallery 的摆拍铁律(250ms 后 emit)又耦合在这个时序上——**测试基建和实现细节三重耦合**。
- **规范**:250ms 唯一源 = JS 常量 `VIEW_MS=250`;CSS 侧时长改读 CSS 变量 `var(--view-ms)`,由 JS 启动时 `setProperty` 注入。改一处,三处(JS/CSS/画廊约定)随动。
- **实现**:`const VIEW_MS=250` + `document.documentElement.style.setProperty('--view-ms', VIEW_MS+'ms')`;`.v{animation:fadein var(--view-ms)}…` 相应改写;`show()` 的 setTimeout 直接用 VIEW_MS。
- **验收(AC-8)**:grep 文件内不再有裸 `250`/`.25s` 时序魔法数(动画缓动曲线里的数值除外);把 VIEW_MS 改 500 目测转场同步无撕裂,改回。

---

## B. P0 行为正确性(8 项——用户路径上撒谎/吞反馈/基准失真/老用户被当新用户的洞)

### P0-1 flash 体系落地(挂靠 A1)
- 位置:`quickLogin`、`renderMain`、`setAuto`。
- 修法:按 A1 实现 `flashMainLede` + 基线守卫;`quickLogin` 三处直写改道。
- 验收:AC-1。

### P0-2 `already` 分支假成功
- 位置:`quickLogin` 的 `r.ok` 分支(现只判 `result==='stored'`,其余一律成功文案)。
- 修法:识别 `r.data.result==='already'` → `flashMainLede('你已经在网上了,桂桂没动')(拟稿)` + `mood(gb,'idle')`,**不冒领**;`mainState` 不动。
- 边界:`enableDaily`/`loginNow` 的 already 路径(已在线首装 → 「保存配置」终态)**语义正确,不动**。
- 验收:scene=ok 主页点「立即重新登录」→ 文案如实;不再出现「把网接回来」。

### P0-3 waiting 态处理(拍板⑤改写:全局删除开门判断)
- 原方案(waiting 文案贯穿/排查页感知)**作废**;等门页 bootWait **删除**,「校园网 06:50 才开门」系文案全部下线。
- 新行为:`net:state` 的 `waiting` 一律视同 `unreachable`——唯一落点 v-guide;`netText`/状态行/首装分流同步两态化(可达/不可达)。
- 后端不动:detect 四态保留,前端映射层压平(waiting→down)。
- 验收:mock `_setNet('waiting')` 打在任意视图 → 与 unreachable 行为完全一致;bootWait 函数与等门帧删除,gallery 对应帧移除。

### P0-6 mock 契约对齐:「线上他人」已存凭据路径(09-09 二轮补验实锤)
- 病灶:mock 与真后端在「线上是他人学号」的**已存凭据重登**路径上行为相反——
  真后端([api.py:189-199](guigui/app/api.py#L189)):`logged_in` 时先 `chkstatus_uid` 核对,线上是他人 → **不报 already,改走真登录**(注释原文「别人的成功不冒领」);
  mock([mock.js:146](guigui/app/static/dev/mock.js#L146)):`logged_in` 一律 `return OK({result:'already'})`,阶梯只在带 password 时走。
  后果:前端在 mock 的 other/ladder_back 场景练的「主页重登 = already」在真机不存在(真机会真登/被拒/节流三态);mock 自称「可执行规范、两边逐字段一致」却停在旧版,后续所有前端验收都建立在错误基准上。
- 修法:mock 的 `login` 无 password 分支对齐后端——other/ladder_back 场景 `logged_in` 时模拟 chkstatus 他人 → 走「注销他人 → 真登」阶梯(发 `login:progress` 事件,返回 success+attempts=1);线上是自己 → already(现状)。P0-2 的 already 文案修复不受影响(真后端 already 只在自己在线时发生,文案恰好准确)。
- 纪律:这是把 mock 对齐既有后端行为,**契约文档不动、后端 0 行改动**;mock 头注的场景说明同步更新;state-gallery 若有帧依赖旧 already 行为需同步重拍。
- 验收:scene=other 主页「立即重新登录」→ 等待行出现注销告知 → 真登成功;scene=daily(自己在线)→ already 文案「你已经在网上了,桂桂没动」。

### P0-4 `NOT_CONFIGURED` 静默跳转 + 防重(挂靠 A2)
- 位置:`quickLogin` 的 `NOT_CONFIGURED` 分支(裸 `openDetail('v-login')`,零解释)。
- 修法:跳转前 `showLoginErr('还没存过密码,先填一次')(拟稿)`;配合 A2 的 `minMs` 堵零延迟路径。
- 验收:AC-2 双击样本;落地登录页带警告块解释。

### P0-5 横幅①条件收口(挂靠 A7;条件 09-09 二轮补验后修正)
- 位置:`renderBanners`。
- 修法:横幅①条件改为 **`verified===false && (lastNet && lastNet.state!=='logged_in' || 最近结果 outcome==='fail')`**。
  ⚠️ 初版守卫「已在线即隐藏」太粗,二轮补验 scene=unverified(已在线+未验证+**今早真失败**)时被否——这时密码大概率真错,横幅①是有信息的,一刀切会错杀。精确语义:**「未验证且(不在网 或 最近失败过)」才显示**;「未验证+已在线+从没失败」(scene=ok / beforeopen 存入型)才静默。
- 验收:AC-7;补 scene=unverified → 横幅①**在场**;scene=ok → 横幅①**不在场**。

### P0-7 网恢复自动重登 + 兑现「连上后自动登录」承诺(09-09 三轮链级评估入册,D1+D2 合并;用户拍板直接进 plan)
- 病灶(实测):已配置用户断网后网恢复——排查页路径被拉去**空密码表单**(实测 `f-pwd-login` 长度 0,刚存过的密码视而不见);保存配置页路径**完全静默**(实测仍停在「配置保存成功！」)。而该页文案承诺「连上校园网后,桂桂自动执行登录」——GUI 非常驻、巡逻默认关、GUI 自己不探网,承诺的唯一执行者是明早任务。**系统明知用户有凭据(`configured && hasPwd`),却把老用户当新用户。**
- 修法:`net:state` 处理器 `not_logged_in` 分支加配置态分岔——
  1. `configured && hasPwd` 且**不在表单页**(A3 填表豁免不动)→ 触发 `autoRelogin()`(quickLogin 的自动版,无按钮):成功 flash「网回来了,顺手帮你登好了(拟稿)」;`AUTH_REJECTED` → 跳改密页带警告(与手点同路);`stored` → flash 锚前文案;
  2. 未配置 → 现状表单路径不变;
  3. 生效视图:v-guide / v-success(保存页)/ v-main——三处统一走同一分岔;挑网 `connectWifi` 成功后的 `not_logged_in` 事件同路径自动受益。
- 契约纪律:0 行 Python;`autoRelogin` 是前端对既有 `login({})` 的复用。
- 验收:down 场景 ③存配置 → 保存页 → `_setNet('not_logged_in')` → **自动登上**,不再见空表单;排查页(configured)网恢复 → 自动登;未配置网恢复 → 表单照旧;表单页填表中网恢复 → 状态行更新不自动登(A3 优先)。

### P0-8 (已作废,拍板⑤取代)
- 原「首装+waiting 专属等门」随开门判断全局删除而作废:首装 waiting 与 unreachable 同路落 v-guide,不建新等门页。保留编号占位防错引。

### P1-8 状态页 5s 连通性探测(拍板⑧改写)
- 原等门自轮询方案随等门页删除而移途:5s 探测挂**大头状态页**(P1-10),探测内容=系统能否连上 10.1.2.3(纯连通性,不触发登录)。
- 结果路由:通了 → 日常页(或触发后端重查状态);不通 → 停留状态页。定时器随页面离开清理。
- 验收:mock 下断/通切换,状态页 5s 内自动迁移;无泄漏定时器。

### P1-9 后端缺席页加重试(09-09 三轮入册,D5;用户拍板直接进 plan)
- 病灶:`BRIDGE_MISSING` → 仪式页文字劝「重启桂桂;反复出现请重装」,无重试按钮——A4 出口完备性漏了仪式页,死胡同。
- 修法:boot-cap 下加 quiet 按钮「再试一次(拟稿)」→ 重新走 firstRun 探测;`GG.ready`/dispatch 机制现成支持。
- 验收:dev 下断 mock 注入模拟 BRIDGE_MISSING → 点重试 → 恢复后正常分流;连续失败文案如实。

---

### P1-10 大头状态页(拍板⑧新增;来源:用户流程图)
- 定义:**非首装独有**的全屏问题态页面——复用成功页舞台(大头 bot),背景蓝变红,bot 沮丧;与主页横幅**并存**,不互斥。
- 入口:静默探测「有网但状态没登录」/「自动登录测试」后端返回四分支。
- 动作分流(拍板⑦):密码不对/学号运营商错 → 提示进入登录页(带返回,返回落点=带错误横幅的日常页);绑定受限/学号已在别的设备 → 提示「是否更换账号?(拟稿)」——换 → 登录页;不换 → 返回日常页(错误横幅在场);5s 连通性探测自动恢复(P1-8)。
- 验收:gallery 新增状态页帧(红变体);四分支各自落点正确;返回后横幅在场。

## D. P2 架构收口(3 项,拍板②;视觉零变化)

### D.1 P2-1 表单合一
- **范围**:`v-ok` + `v-login` → 单视图 `v-form`;`enableDaily` + `loginNow` 两条验证阶梯(throttled / AUTH_REJECTED / NET_UNREACHABLE / already / 兜底,各写一遍)合并为 `submitLadder(ctx)`,`ctx ∈ {firstRun, login, save}`(v-guide ③)。
- **参数化差异**:标题(早上好/登录校园网)、lede、按钮文案(开启每日自动登录/立即登录/保存配置)、警告块 id、状态行来源、`formDirty` 判定——全部由 ctx 派生,一套 DOM。
- **执行纪律**:
  1. 动手前把两页现渲染截图存档(`docs/plans/assets/` 或临时目录),合并后逐像素对照(视觉不变原则);
  2. `ok-note`/`login-note` 合并为 `#form-note` —— **state-gallery 的 `notePose` 帧引用这两个 id,必须同步改**(见 E 章);
  3. 双份运营商下拉(`#op-dd`/`#op-dd-login`)随合一自然消失,`pickedOperator`/`setOperatorPick` 去掉 selector 参数。
- **验收**:gallery 的 v-ok/v-login 全部故事帧重拍通过;三条提交路径(首装/登录/保存配置)mock 全场景回归。

### D.2 P2-2 路由总表数据化
- **范围**:`net:state` 处理器 28 行 if 链 + 3 处重复的 `mainState` 三元压缩 → 表驱动:
  - `netToMain(state)`:四态 → ok/out/down 的**唯一**压缩点(waiting 列按 B-P0-3 规范落文案,不再裸压 down);
  - `ROUTE[view][netState] = {stay|goto|render}` 查表,含 A3 的 `formDirty` 豁免维度(表单行单独一列或 `when(formDirty)` 谓词);
  - `show`/`openDetail`/`backFrom` 签名不变(画廊依赖)。
- **收益断言**:新增一个网态或一个视图 = 改表一行,不再人肉对 4-6 处;`waiting` 列自然在表里。
- **验收**:gallery 全故事行为等价重跑;矩阵文档错误路由总表与代码表逐格对得上(E 章)。

### D.3 P2-3 store 收口
- **范围**:13 个散全局(`mainState/configured/hasPwd/lastNet/curCfg/taskBlocked/loginFailStreak/successState/fbKind/fbDraft/diagState/currentTriggerTime` + A1 新增 `flashUntil`)→ 单一 `S` 对象;函数**保持全局**(画廊白名单依赖),但状态读写一律走 `S.x`。
- **验收**:`grep -nE '^(let|const) ' index.html` 的 JS 段仅剩 `S`、常量(`VIEW_MS/MAIN_LOG_KEEP/DIAG_KEYS` 等)与函数;`bots` 映射可保留。
- **画廊兼容白名单**(重构中不许破坏,每改一处同步核对该清单):
  - 函数:`show` `openDetail` `backFrom` `mood` `fbPickKind` `greet` `renderGuide` `renderMain` `renderMainData` `fillLoginLanding` `loadFeedback` `loadSettings` `loadLogs` `startDiag` `win` `minimize` `closeWin`;
  - id:`boot-bot` `boot-cap` `main-h1` `main-lede` `main-btn` `main-banners` `main-log-entries` `diag-*` `fb-*` `success-*`(`ok-note`/`login-note` 随 D.1 迁移为 `form-note`,画廊同步);
  - 时序:`VIEW_MS`(A8)——画廊摆拍铁律跟着这一个常量走。

---

## E. state-gallery 重拍清单 + 矩阵文档同步义务

- **必重拍帧**:v-ok 全帧、v-login 全帧(D.1 表单合一);排查页帧 + **新增 waiting 态排查帧**(B-P0-3);拦截页帧(C-P1-1 两按钮);主页横幅帧(①新显示条件、③新文案);「发送中」「必填空」帧(id 迁移);**新增体检过期帧**(P1-6,断网返回后灰化+重跑);**other/ladder_back 主页重登帧**(P0-6,阶梯告知)。
- **新增故事**:「填表中收到断网:不跳页,状态行转 danger」(A3/AC-3)——画廊新增帧,证明豁免逻辑。
- **矩阵文档**(`docs/prd/guigui-state-matrix.md`):
  1. 错误路由总表补 waiting 行(P0-3);
  2. 填表豁免例外注记(A3,拍板④);
  3. 横幅①显示条件更新(P0-5);
  4. 拦截页出口更新(P1-1);
  5. `v-ok`/`v-login` → `v-form` 的帧结构变更(P2-1)。
- **交互路由全景图**(`docs/prd/flows/guigui-frontend-routing.workflow.json`,2026-09-09 落盘):as-is/to-be 双焦点视图;**每修完一项把图上对应「拟」节点/边转正**(删 as-is 问题标注),图与代码同步是交付义务。

## F. 验收总门(全部通过才闭环)

1. **审计对账**:2026-09-09 审计 10 洞逐条对账关闭(P0-1~5 → 洞 1/2/3/4/8/9;P1-1~5 → 洞 5/6/7/9/10;A 章规范挂靠齐全)。
2. **mock 全场景**:内置浏览器 21 个 scene 跑一遍,无新洞、无回归(重点:already 假成功、waiting 贯穿、填表豁免、双击防重)。
2a. **事件路由格全走查**:对 `net:state` 四态 × 主要视图(v-main / v-form / v-guide / v-settings / v-log / v-feedback / v-diag / v-success / v-boot)逐格 `_setNet` 验证落点(P2-2 落地后按 ROUTE 表逐格对)。已代验格子见 I 章补验记录,未代验格(v-log / v-feedback / v-success 收 unreachable;各视图收 waiting)执行时补。
3. **gallery 全帧**过目 + 必重拍帧更新;矩阵文档同步完成。
4. **双击复测样本**:NOT_CONFIGURED 场景 login 调用 = 1;成功 flash ≥4s(AC-1/AC-2 数据化复测)。
5. **读屏抽查**:bot aria 全部桂桂口吻;横幅 Tab 可达。
6. **文案定稿**:H 章拟稿表请用户过目,定稿后如有改动统一替换再提交。

## G. Backlog(本轮不做,发现新洞也记这里)

- **D4|identify 误抓的归因误导(待用户拍板,涉 1.4.3 已否旁注)**:首装在线回填他人学号(「已识别✓」背书)→ 阶梯注销他人 → 被拒「密码不对」→ 用户归因自己密码死循环;自纠依赖服务器文案区分 wrong_account。可选缓解:首装被拒 ≥2 次时警告块附「也核对下学号是不是你自己的」——是否采纳由用户定。
- **E park|验证器专用计划任务机制(拍板⑨先不管)**:用户图中「创建一次性验证任务→验完删除」的端到端验证机制,涉及契约新方法与 schtasks 拦截误报风险,本轮不做;现有后端 diagnose 保持不动、入口不重做。
- **D6|改密路径 lede 文案错位(待用户拍板,涉用户手写文案)**:设置→账号修改 → v-login 的 lede「还没登录,填一次…」是首装语境,对改密用户是谎话;该句为用户亲手改定(2026-09-07),按来路(origin)换文案需用户点头并定稿措辞。

- `recentResult` 信封加 `fail_streak`(横幅③真历史计数)——契约 1.6.0,需后端配合;
- 主文件拆分(css/js 出去)——打包零成本(`static.rglob` 全量),但破坏「与 PRD 原型逐字节一致」fidelity 口径,等 store 收口后重新评估;
- 时间输入 ↑↓ 微调;完整 combobox 键盘模式(已判过度设计);
- 时间钳制 err 态延迟落盘(现行为所见即所存,保留);
- `waiting` 若未来需要「距开门的倒计时」,再议主页第四态(本轮拍板不加)。

## H. 文案拟稿汇总(执行完统一请用户过目)

| 位置 | 现文案 | 拟稿 |
|---|---|---|
| P0-2 already 反馈 | 刚刚把网帮你接回来啦 ✓ | 你已经在网上了,桂桂没动 |
| P0-4 NOT_CONFIGURED | (无) | 还没存过密码,先填一次 |
| P0-3 waiting 主页标题 | 现在连不上校园网。 | 网络还没就绪。 |
| P0-3 waiting 主页 lede | 现在够不着校园网,我陪你查查看。 | 可能刚开机,还没到点,桂桂在等开门。 |
| P0-3 waiting 排查页① | ① 当前连的是「X」,像热点。挑一个校园网: | 可能刚开机或还没到点。校园网 06:50 开门,桂桂在等: |
| P0-3 reProbe waiting | 还是连不上,再试一次 | 门还没开,再等等 |
| P0-3 netText waiting | X · 连不上 | 网络还没就绪 |
| P1-1 拦截页次按钮 | (无) | 先不管,回主页 |
| P1-2 时间前缀 | 明早(写死) | 明早/今天/今晚(按时刻) |
| P1-3 SSID 当前标记 | (无) | 当前 · 连着 |
| P1-4 横幅③ | 试了几次还没登上?完整排查 | 反复登录都被拒?完整排查 |
| P1-6 体检过期提示 | (无) | 网络刚变过,结果可能过期,重跑一次 |
| P1-7 拦截页标题(验证器路径) | 密码存好了,自动登录还差一步。 | 密码没问题,自动登录还差一步。 |
| P0-7 网恢复自动登 flash | (无,拉空表单) | 网回来了,顺手帮你登好了 |
| P0-8 首装等门文案 | 这条路今天不通。(误用) | 网络还没就绪,等它一下…连上就带你登录 |
| P1-8 (行为项,无文案) | — | — |
| P1-9 缺席页重试按钮 | (无) | 再试一次 |
| P1-5 bot aria | 小匠文档助手,待命 等 | 桂桂在待命/桂桂在想事/桂桂很开心/桂桂有点急/桂桂睡着了 |
| P1-10 换账号提示 | (无) | 这个账号在别处登着,换一个账号试试? |
| ~~P0-3 等门系文案~~ | 06:50 才开门,桂桂在门口等着… 等 | 随开门判断全局删除一并在 UI 下线(拍板⑤) |

---

## I. 补验记录(2026-09-09 第二轮,交互链全走查)

> 用户质询「交互链你真的全部验证过吗」后补跑。以下为**已实测走通**的链(执行时作回归基线);标注⚠的为本轮新发现、已入计划。

| 链 | 场景 | 结果 |
|---|---|---|
| 首装在线+识别回填+空密码警告+保存终态 | ok | ✓(一轮) |
| 主页重登 already 假成功+80ms 吞文案 | ok/daily | ✓(一轮)⚠P0-1/P0-2 |
| 重登被拒→登录页→连败×2→横幅③→验证器→exit=login | streak | ✓(一轮) |
| 断网→排查页→③保存配置→填表中网恢复就地更新→提交彩带 | down | ✓(一轮) |
| 拦截页死胡同→重建放行彩带 | blocked | ✓(一轮) |
| 等门→开门→日常页 | waiting | ✓(一轮)⚠P0-5(横幅①又在场) |
| waiting 压成 down+排查页「像热点」误导 | daily+_setNet | ✓(一轮)⚠P0-3 |
| 反馈必填→断网入队→立刻重发回填 | down | ✓(一轮) |
| 设置时间钳制→「明早 23:00」 | daily | ✓(一轮)⚠P1-2 |
| 主页重登 already(mock 旧基准) | other | ✓⚠P0-6(mock/后端偏离实锤) |
| 阶梯翻车两幕:他人学号回填→注销他人→被拒「网先断着」→改对成功 | ladder_fail | ✓ |
| 阶梯回滚:改密被拒「已用旧密码接回来」→网恢复 | ladder_back | ✓ |
| 节流:等待行中性文案,不进密码警告 | throttled | ✓ |
| bind 被拒:自助平台六字内联链接渲染 | bind | ✓ |
| limit 被拒:教育文案 | limit | ✓ |
| 锚前存入:重登如实「还没开门,密码先存着」 | beforeopen | ✓ |
| 未验证+今早失败:横幅①在场(显示条件需精化) | unverified | ✓⚠P0-5 修正 |
| 验证器任务败:exit=task_blocked→拦截页 | diag_task | ✓⚠P1-7 标题口径 |
| 验证器程序败:出口按钮隐藏+就地结论 | diag_app | ✓ |
| 反馈降级:submitted_degraded 按「收到」处理 | fbdg | ✓ |
| master 开关联动:拦截态横幅②/关闭后消失 | blocked | ✓(「关闭后残留」经查后端是幽灵任务故意告警,非洞) |
| 体检中断网:拽排查页正确;返回后旧结果过期 | daily+diag | ✓⚠P1-6 |
| 挑网自动路由:guide→连网→v-login | down | ✓(一轮) |

**未代验、执行时必须补**:v-log/v-feedback/v-success 收 unreachable 的落点;各视图收 waiting(除已验三格);bind 内联链接点击后新标签页打开(openSelfService);applyLaunch 深链(creds/settings);`log:appended` 在 v-log 页的追加。

**三轮补验(2026-09-09,链级设计评估)**:D1 排查页(configured)网恢复 → 实测落 v-login 且密码框空;D1b 保存配置页网恢复 → 实测完全静默(仍「配置保存成功！」);D7 GUI 侧无自轮询 → 代码查证(gui.py FileWatcher 注释,net:state 全部翻译自 ensure 落盘)。46 条链全景评估结论:21 健康 / 12 bug 级(已入册)/ 7 链级设计问题(D1-D7,其中 D1+D2/D3/D7/D5 已入册为 P0-7/P0-8/P1-8/P1-9,D4/D6 待拍板在 G 章)/ 6 待验待裁决。

## 建议执行顺序与 commit 粒度


1. **第一批(P0,一个对话可完成)**:P0-1(A1 flash 体系)→ P0-2 → P0-5 → P0-3(waiting)→ P0-4(A2 minMs)→ P1-2/P1-3/P1-4(小文案)→ P1-1(拦截页)→ P1-5(可达性包)。每项一 commit;A8(VIEW_MS 单源)作为独立小项插在 P0 后。
2. **第二批(P2,建议独立对话)**:P2-1 表单合一(最大,先截图存档)→ P2-2 路由数据化 → P2-3 store 收口;每项一 commit,画廊/矩阵同步随项走。
3. **收尾**:F 章验收总门 + H 章文案过目。
