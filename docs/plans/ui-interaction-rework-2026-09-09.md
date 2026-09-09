# 前端交互重构计划(审计修复 + 交互规范 + 架构收口)2026-09-09

> **状态**:已拍板,待执行。
> **输入**:2026-09-09 四视角审计(产品/交互工程/用户/UX)+ 内置浏览器逐场景实测,10 个实锤问题(4 P0 / 4 P1 / 2 P2 级)。
> **拍板记录**(2026-09-09,用户四问拍板):
> ① waiting 态修法 = **排查页感知 waiting**(不新增主页第四态);
> ② 架构收口范围 = **三件全做**(表单合一 / 路由数据化 / store 收口),不拆文件;
> ③ 拦截终态页 = **加 quiet 次按钮「先不管,回主页」**;
> ④ 事件打断策略 = **填表中不打断**(表单有已键入内容时,unreachable 事件不拽人去排查页,就地状态行;终态页/详情页维持统一跳)。
> **用户追加要求**:交互工程师视角必须详细到可执行——本文 A 章(交互规范八条)即该要求落成的「宪法层」,B/C/D 执行项逐条挂靠 A 章。

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

## B. P0 行为正确性(5 项——用户路径上撒谎/吞反馈的洞)

### P0-1 flash 体系落地(挂靠 A1)
- 位置:`quickLogin`、`renderMain`、`setAuto`。
- 修法:按 A1 实现 `flashMainLede` + 基线守卫;`quickLogin` 三处直写改道。
- 验收:AC-1。

### P0-2 `already` 分支假成功
- 位置:`quickLogin` 的 `r.ok` 分支(现只判 `result==='stored'`,其余一律成功文案)。
- 修法:识别 `r.data.result==='already'` → `flashMainLede('你已经在网上了,桂桂没动')(拟稿)` + `mood(gb,'idle')`,**不冒领**;`mainState` 不动。
- 边界:`enableDaily`/`loginNow` 的 already 路径(已在线首装 → 「保存配置」终态)**语义正确,不动**。
- 验收:scene=ok 主页点「立即重新登录」→ 文案如实;不再出现「把网接回来」。

### P0-3 waiting 态贯穿(拍板①:排查页感知)
- 病灶:`net:state` 处理器三处三元把 waiting 压进 down;排查页给出「像热点,挑一个校园网」的错误建议;「重新检测」对 waiting 说「还是连不上」——而 bootWait 页明明写着「06:50 才开门」。同一条知识在文件里写了两次、漏了第三次。
- 修法(全部按 `lastNet.state==='waiting'` 分支,不新增 mainState 值):
  - `renderGuide`:状态行「10.1.2.3 · 还没就绪」;①行整段换成 waiting 文案(拟稿:「可能刚开机或还没到点。校园网 06:50 开门,桂桂在等:」);**隐藏挑网列表** `#guide-wifi`;②行保留;
  - `reProbe`:waiting 时按钮文案「门还没开,再等等(拟稿)」,不进「还是连不上」分支;
  - `renderMain` down 态:waiting 时标题「网络还没就绪。」、lede「可能刚开机,还没到点,桂桂在等开门。」(拟稿);
  - `netText` 加 waiting 分支「网络还没就绪」;`syncLoginStatusLine`/`syncOkStatusLine` waiting →「· 还没就绪」;
  - `bootWait`(v-boot 等门页)不动——它本来就对。
- 验收:`_setNet('waiting')` 分别打在主页/排查页/登录页,三处均不再出现「不可达」「像热点」字样;`_setNet('logged_in')` 后开门链路照旧进日常页。

### P0-4 `NOT_CONFIGURED` 静默跳转 + 防重(挂靠 A2)
- 位置:`quickLogin` 的 `NOT_CONFIGURED` 分支(裸 `openDetail('v-login')`,零解释)。
- 修法:跳转前 `showLoginErr('还没存过密码,先填一次')(拟稿)`;配合 A2 的 `minMs` 堵零延迟路径。
- 验收:AC-2 双击样本;落地登录页带警告块解释。

### P0-5 横幅①条件收口(挂靠 A7)
- 位置:`renderBanners`。
- 修法:横幅①条件追加「当前非已在线」守卫;文案不动。
- 验收:AC-7。

---

## C. P1 终态·文案·可达性(5 项)

### P1-1 拦截页加出口(拍板③)
- 位置:`renderSuccess` 的 `!taskOk` 分支(`stageEnter` actions 数组)。
- 修法:actions 追加 `{label:'先不管,回主页', quiet:true, fn:()=>backFrom('v-success')(拟稿)}`。回主页后横幅②「自动登录还没生效,点此重建」在场(`setTaskBlocked` 单点已保证),状态不丢,用户随时可回来重建。
- 验收:scene=blocked 全链走通:拦截页两按钮并存;「先不管」回主页见横幅②;横幅②重建成功后横幅消失。

### P1-2 时间文案 time-aware
- 位置:`setAuto` 的「明早 HH:MM 替你登」、`renderSuccess` 的「明早 HH:MM 开始」。
- 修法:新增 `whenWord(t)`:`t<12:00 → '明早'`,`<18:00 → '今天'`,否则 `'今晚'`(拟稿);两处替换。实测现状:错输 99 被钳到 23:00 落盘后,主页显示「明早 23:00 替你登」。
- 边界:时间钳制行为(99→23)**保持现状**(所见即所存,输入框显示 23:00、存 23:00,无欺骗),只修「明早」错位。
- 验收:设 23:00 → 主页「今晚 23:00 替你登」;07:00 → 「明早 07:00」不变。

### P1-3 排查页当前 SSID 标记
- 位置:`renderWifiList`(+调用方传 `opts.currentSsid = lastNet && lastNet.ssid`)。
- 修法:匹配当前 SSID 的项:排查页(guide)场景标「当前 · 连着(拟稿)」且**禁点**(移除 onclick + `.off` 类);WiFi 兜底 pick 场景只标记不禁点(兜底选当前 SSID 是合法配置)。
- 病灶对照:down 场景引导语说「像热点,挑一个校园网」,列表里 iphone17 pro max 标「信号强」——信号最强的恰恰是错的那个,点了自己连自己还被事件路由甩去登录页。
- 验收:down 场景当前热点显示「当前 · 连着」、点击无任何路由发生。

### P1-4 横幅③文案口径
- 位置:`renderBanners` 横幅③。
- 修法:`loginFailStreak` 是内存变量,重启归零,只数**本会话手点**的失败——现文案「试了几次还没登上?」谎称历史。改为会话内口径「反复登录都被拒?完整排查(拟稿)」。真实历史连败计数(`recentResult` 加 `fail_streak`)列 G 章 backlog,本轮契约不动。
- 验收:文案不再暗示「今早自动登录的历史」。

### P1-5 可达性包(挂靠 A4/A5/A6)
- 修法清单:
  1. 三条主页横幅 `div` → `button.banner`(样式重置同形);
  2. `initBot` 创建实例后覆写 aria-label 为桂桂口吻(拟稿:`data-state` 五态映射——sleep「桂桂睡着了」/idle「桂桂在待命」/complete「桂桂很开心」/thinking「桂桂在想事」/angry「桂桂有点急」);vendor 文件本身不动(运行时覆盖,MIT 许可无碍);
  3. SSID 项补 `role="button" tabindex="0"` + Enter/Space;
  4. `togglePw` 同步 `aria-pressed`;dd 开合同步 `aria-expanded`;
  5. dd 菜单 Escape 关闭 + 焦点还按钮;
  6. 视图 h1 补 `tabindex="-1"`,`show()` 完成后 focus(挂靠 A5)。
- 验收:AC-4/5/6;读屏标签不再出现「小匠」。

---

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

- **必重拍帧**:v-ok 全帧、v-login 全帧(D.1 表单合一);排查页帧 + **新增 waiting 态排查帧**(B-P0-3);拦截页帧(C-P1-1 两按钮);主页横幅帧(①消失条件、③新文案);「发送中」「必填空」帧(id 迁移)。
- **新增故事**:「填表中收到断网:不跳页,状态行转 danger」(A3/AC-3)——画廊新增帧,证明豁免逻辑。
- **矩阵文档**(`docs/prd/guigui-state-matrix.md`):
  1. 错误路由总表补 waiting 行(P0-3);
  2. 填表豁免例外注记(A3,拍板④);
  3. 横幅①显示条件更新(P0-5);
  4. 拦截页出口更新(P1-1);
  5. `v-ok`/`v-login` → `v-form` 的帧结构变更(P2-1)。

## F. 验收总门(全部通过才闭环)

1. **审计对账**:2026-09-09 审计 10 洞逐条对账关闭(P0-1~5 → 洞 1/2/3/4/8/9;P1-1~5 → 洞 5/6/7/9/10;A 章规范挂靠齐全)。
2. **mock 全场景**:内置浏览器 21 个 scene 跑一遍,无新洞、无回归(重点:already 假成功、waiting 贯穿、填表豁免、双击防重)。
3. **gallery 全帧**过目 + 必重拍帧更新;矩阵文档同步完成。
4. **双击复测样本**:NOT_CONFIGURED 场景 login 调用 = 1;成功 flash ≥4s(AC-1/AC-2 数据化复测)。
5. **读屏抽查**:bot aria 全部桂桂口吻;横幅 Tab 可达。
6. **文案定稿**:H 章拟稿表请用户过目,定稿后如有改动统一替换再提交。

## G. Backlog(本轮不做,发现新洞也记这里)

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
| P1-5 bot aria | 小匠文档助手,待命 等 | 桂桂在待命/桂桂在想事/桂桂很开心/桂桂有点急/桂桂睡着了 |

---

## 建议执行顺序与 commit 粒度

1. **第一批(P0,一个对话可完成)**:P0-1(A1 flash 体系)→ P0-2 → P0-5 → P0-3(waiting)→ P0-4(A2 minMs)→ P1-2/P1-3/P1-4(小文案)→ P1-1(拦截页)→ P1-5(可达性包)。每项一 commit;A8(VIEW_MS 单源)作为独立小项插在 P0 后。
2. **第二批(P2,建议独立对话)**:P2-1 表单合一(最大,先截图存档)→ P2-2 路由数据化 → P2-3 store 收口;每项一 commit,画廊/矩阵同步随项走。
3. **收尾**:F 章验收总门 + H 章文案过目。
