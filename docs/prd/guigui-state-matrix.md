# 桂桂 UI 状态矩阵(2026-09-07 全边界盘点 · 2026-09-08 交互重构同步)

> 起因:用户盘点「前端业务逻辑和 UI 态一堆洞」,列出日常/首装 × 网络七场景。
> 本文档是**状态总账**:全部状态、每个视图的态、事件路由表、场景映射、修复记录。
> 2026-09-08 交互重构(docs/plans/ui-routing-rework-2026-09-08.md,P0+P1 已落地)
> 之后第 2 次同步:§0 落点列按终态收敛刷新,§1/§2 按新路由重写,§3 补验证器两行。
> 2026-09-10 第三批同步(P1-8/P1-10/P1-12/P0-7,计划 ui-interaction-rework v2):
> §0 补快登分岔注、§1 加 v-status 行、§2 路由表加 hub 调起维度重写、§3 补场景 #10/#11。
> 2026-09-11 第三批续(P1-13,计划 ui-interaction-rework v2):日常页两态化落地 —
> §0 主页呈现列改两态口径、§1 v-main 行重写、§2 v-main 行措辞、§3 #7e 补横幅②联动、§4 记录。
> 2026-09-11 第三批续二(P1-14):🔑 检验自适应服务落地 — §0 加 🔑 补注、§1 v-status 行
> contra 口径改(进入检测走 🔑)、§2 表尾加 vt2 注、§3 #12、§4 记录。
> 2026-09-11 第三批续三(P1-16/P1-17):成功页矩阵 + 任务①②生命周期 — §0 彩带口径
> 与 NET_UNREACHABLE 行、§1 v-success 行重写、§3 #13、§4 记录。
> 2026-09-11 第三批续四(P1-15):故障带自愈四链分层落地 — §0 加巡检五维消费
> 与 🔔 对账/契约缺口注、§1 v-boot/v-main/v-status 行补分诊与 3 败、§3 #14、§4 记录。
> 活的形式见 `guigui/app/static/dev/state-gallery.html`(陈列矩阵 + 场景流程 + 网络切换器)。

## 0. 两轴状态模型

### 网络态(后端 probe / net:state 事件,契约 §2.1)

| state | 含义 | 前端 mainState(内部语境:未配置首装分流 / boot 心境;P1-13 起不再驱动主页渲染) | 主页呈现(P1-13 两态) |
|---|---|---|---|
| `logged_in` | 已认证在线 | `ok` | ①全部正常:问候语标题,无横幅(hubRaised 随 logged_in 清) |
| `not_logged_in` | 服务器可达、未认证 | `out` | 标题恒问候语;「网络」行如实「X · 还没登录」;网态问题走横幅⑧→状态页(drop) |
| `unreachable` | 认证服务器够不着 | `down` | 同上(wait);「网络」行「10.1.2.3 · 连不上」;未配置走旧路 v-guide |
| `waiting` | 网络栈未就绪(刚开机/WiFi 在连) | `down`(P0-3 起前端映射层压平 waiting≡unreachable,唯一落点 v-guide) | 同 unreachable |

### 登录结果(login 信封,契约 §2.3;前端落点 = 2026-09-08 终态收敛后)

完成是全有或全无:彩带只给「真验证通过 + 定时任务在岗」;客观验不了的诚实叫「保存配置」。
**P1-16 成功页矩阵(2026-09-11,拍板⑯)**:彩带 = **用户在场的验证通过**(首装链 + 日常改密,`submitLadder` 唯一入口;明早无人值守成功**不弹彩带**——后端通知 + 日常页状态,GUI 在场时 net:state 只重渲主页);okpg2 保存配置页 = 配置模式建成,不可达语境唯一出口「回排查页」(白板出边,按当前状态)。

| result / code | 语义 | 前端落点 |
|---|---|---|
| `success` + verified + task_ok | 真验证通过且任务在岗 | 彩带终态页(四行文案 + 彩带三波) |
| `success` + verified + task_ok=false | 登上了但定时任务被拦 | 拦截终态页(只留「重建定时任务」;rebuild ok+verified 才重渲为彩带放行) |
| `already` | 已在线(线上是本人) | verified=true → 彩带;verified=false → 保存配置终态(降级存入文案) |
| `stored` / reason=before_open | 06:50 前被拒,不判密码错,存未验证 | 保存配置终态页(锚前文案);主页重登返 stored → lede 如实「时间还没到,密码先存着」,不撒花(P0-3 开门文案已下线) |
| `AUTH_REJECTED` reason=`wrong_password` | 密码不对,不存 | 表单页统一警告块(B 基准:与密码空同一组件同一位置) |
| `AUTH_REJECTED` reason=`wrong_account` | 学号/运营商选错 | 同上(identify 误抓室友学号的自纠出口) |
| `AUTH_REJECTED` reason=`bound` | 密码对但绑定被拦 | 同上,「自助服务平台」六字内联可点 |
| `AUTH_REJECTED` reason=`limit_users` | 学号在别的设备在线 | 同上(不冤枉密码) |
| `AUTH_REJECTED` reason=`throttled` | 节流,≠密码错,不存 | 中性 note「让等 N 秒再试」;不进警告框 |
| `NET_UNREACHABLE` | 够不着服务器 | 提交路径:密码已存 → **任务①分流(P1-17)**——信封不带 task_ok(契约 1.5.0 不动),补一次只读 `taskStatus` 秒回复询:建成 → okpg2 保存配置页(P1-16:标题「保存配置成功,今天/明早 HH:MM 见」时间动态,唯一出口「回排查页」;查询失败按建成放行,横幅②兜底);没建成 → 拦截终态页。空密码只跳 v-guide;主页重登 → 跳 v-guide |
| `NOT_CONFIGURED` | 没存凭据 | 主页重登 → 跳 v-form(login 语境,P0-4 先给警告块再跳) |
| `INTERNAL` / `BRIDGE_MISSING` | 兜底 | 三提交函数 + quickLogin 就地报原话,不静默 |

> **快登分岔补注(2026-09-10 P1-12)**:状态页「快速登录」走 `login({})` 存库凭据,复用上表同一信封,但落点归状态页语境:成功/already → `statusResolved` 回日常(全部正常,不撒彩带,lede 闪「登好了,网的事继续交给我 ✓」)/ stored → 状态行转已登录 + note;throttled → 中性 note 留页可再试;AUTH_REJECTED → 沮丧心境(sad)+ 互斥出口(凭据类 → 去登录页改并预填;绑定/别设备 → 换账号?);NET_UNREACHABLE → 等网心境(wait)+ note;NOT_CONFIGURED → 直开 v-form(save 语境)。
>
> **🔑 检验自适应服务(2026-09-11 P1-14,拍板⑫,实现一份)**:后端 `_login_stored_credential` 自适应语义 — 未登录→真登;已登录→chkstatus 对账(线上是自己=already 通过不冒领,他人=改走真登);**禁注销全量**(共享会话/断网风险);对账验不了密码的盲区由下一未登录时刻(掉线/明早任务/网恢复)自然暴露,走五态。前端三入口同一函数 `statusQuickLogin(btn,auto)`:①状态页「快速登录」②矛盾态「进入检测」(contra,不再走 v-diag 五步)③vt2 网恢复·未验证库自动验证(auto=true)。auto 语境:成功不拽人(页面迁移交 net:state 的 ROUTE,formDirty 豁免天然成立)、already 静默不冒领(verified 不翻,横幅①留)、被拒不在状态页时只横幅①(白板 vdo→vb1,在状态页就地转 sad)、vt2Busy 防叠发。vt1(明早 07:00 任务首试)在任务侧。
>
> **巡检五维消费口径(2026-09-11 P1-15,拍板⑬;契约 1.5.0 面内可消费的三维 + 两维缺口)**:
> - **网** = 📡 探测结果(P1-8 常驻,巡检「网」维度不另查);
> - **任务** = taskStatus(启动静默体检)/ schedule:changed / rebuildTask — 重建链闭环(白板 intercept2→re3):后端 rebuildTask 单次点击内自带 3 轮 reconcile 重试环(信封 ok=false 即一轮 3 败);前端拦截页+横幅②共用计数 `S.rebuildFails`,三连败换反馈出口(附诊断包),**点击反馈出口即复位计数复原重建入口**(加白杀软后的再试通路不断,再 3 败反馈入口再现);重建成功信封 ok = reconcile 内 is_task_current 判定,即「回巡检复查」的结论,前端不另复询;
> - **日志** = recentResult 启动分诊(白板 logskip→diag 三路):configured ∧ 当下 logged_in ∧ 今早 outcome=fail → contra 状态页(「进入检测」=🔑);②没登录→drop / ③网不通→wait 已由网态调起接管(P0-7/P1-8);silent(假期静默有意不打扰)与 throttled(中性,任务下拍自会重试)不分诊;recentResult 查询失败宁可漏报;
> - **程序 / 库** = **契约 1.6.0 缺口,单独拍板**(G 章既有条目):两维无只读信封方法(程序侧现仅 diagnose 第 5 步/crashlog 显式体检可查;库侧 vault 的 keyring→advapi32 两层降级是既有行为,无备份库 JSON/降级状态可见性)。库链(备份库 JSON/自动重建×3/降级+🔔)与程序链「自动修复(自校验还原)」整体挂起 — 打包形态下 exe 损坏进程不起,现有 BRIDGE_MISSING 仪式页(P1-9 重试)+ crashlog 入诊断包即现实解。
> - **🔔 J 章表逐行对账(P1-15 验收)**:已兑现 = 任务最终失败·凭据类(FAILED 每日≤1)/拦截要求加白(task_blocked,保存/开关/重建路径)/任务失联(task_lost,ensure 静默自检每日≤1);缺口(随 1.6.0 拍板)= 库降级通知、程序修复失败附重装指引、例行任务成功默认开、任务失败·连不上纯诊断(后两项涉 ensure/notify 语义重写,且「连不上也发」与假期静默拍板有冲突,需用户裁决);通知冷却(同类 30 分钟合并/每类每天≤1)现为「每日≤1」粒度,完整冷却是 1.6.0 范围。

### 验证阶梯(提交密码时线上已有人)

`logged_in` + 提交密码 → `logging_out` 事件(线上他人学号打码注明)→ 注销 → 等翻转 → 真登一次:

- 真登成功 → 存 verified ✓
- 真登被拒 → **旧凭据尽力把网接回**,信封带「已用旧密码把网接回来了,改对再点一次」/「网先断着,输对马上通」
- 真登被节流 → 同样尽力接回(原先直接 return,用户网断着+密码没存+被节流三重伤害,commit 9217f94)
- 注销无配置/未翻转 → 降级存入 already verified=false → 保存配置终态
- 中途不可达 → 尽力接回 + 存未验证 + NET_UNREACHABLE → 保存配置终态(不可达文案)+ 主页横幅①

## 1. 视图 × 状态总表(2026-09-08 重写)

| 视图 | 状态 |
|---|---|
| v-boot | 仪式检查中(sleep)/ BRIDGE_MISSING(bootWait 等门页已随 P0-3 删,waiting 落点同 unreachable);仪式期间静默任务体检(configured 时并行,只读秒回、2s 超时保护,用户无感)+ **日志维度分诊(P1-15)**:configured ∧ probe=logged_in ∧ 今早 outcome=fail → 仪式后直接落状态页 contra(矛盾态,「进入检测」在场;silent/throttled 不分诊;recentResult 失败宁可漏报照常回日常) |
| v-form(2026-09-10 P2-1 合一,原 v-ok + v-login 并为一张 DOM) | **一套表单三语境**,由 `formMode(ctx)` 派生头部/按钮/状态行:**firstRun**(首装已连已登:问候标题+tagline+「开启每日自动登录」,密码必填,提交先落触发时间)/ **login**(未登录落地 / 改密 / 验证器结论预填:「登录校园网。」+「立即登录」)/ **save**(v-guide ③ 路径,按钮=「保存配置」,空密码可提交);共用状态:firstRun 学号已识别 / 验证中 busy / 注销告知 / 密码空警告(仅 firstRun)/ 被拒五态(wrong_password / wrong_account / bound / limit_users / throttled)/ 场景4 注销后失败两变体(网先断着 / 已接回);换学号确认框已删(密码迁移静默,验证不过当场自纠);提交走同一条 `submitLadder()`;停留断网:空表单直跳 v-guide(表单数据保留,回来还在),**已键入学号/密码(A3 formDirty,P2-2)不跳**——状态行就地转 danger、提交照常(保存配置语义允许断网提交);返回键=来路栈(首装期 body.setup 由 CSS 隐藏) |
| v-diag(2026-09-08 新,契约 1.5.0) | 进入即自动开跑(不用点开始) / 跑步中(diag:progress 逐拍上屏,running 脉冲) / 全绿 exit=ok / 凭据败 exit=login / 任务败 exit=task_blocked / 程序败 exit=app_fault(就地说明,无出口按钮) / net_down;页底固定小出口「排查也没解决?说给桂桂听 →」 |
| v-success | **两成功页矩阵 + 拦截 + 反馈二(共用舞台,2026-09-11 P1-16 定稿)**:彩带 okpg(在场验证通过:首装链/日常改密,双出口「完成,回主页」+「高级设置」)/ 保存配置 okpg2(不可达存入 = 配置模式:时间锚标题 + 「回排查页」唯一出口、无高级设置,出口对齐白板;锚前/降级两变体保持「配置已保存。」+ 完成回主页)/ 拦截页(可达路径信封 task_ok=false + **断网存配置复询 taskStatus 分流(P1-17)**;双出口重建/先不管;重建成功 → verified 走彩带、未验证走 okpg2+「定时任务已修好 ✓」;**重建 3 败(P1-15)**主按钮换「3 次没建成,带上诊断包反馈」,点击=复位+重渲+跳反馈页,返回拦截页时「重建定时任务」已恢复);反馈收到(工单号在文案行)/ 没发出去(bot sad;立刻重发=草稿回填 + 完成等待自动补发) |
| v-status(2026-09-10 新,P1-10 问题中枢) | 大 bot 舞台四心境:**wait** 等网(琥珀染,bot 思考脸,「去排查网络」)/ **drop** 登录掉了(红染,bot 哭脸,「快速登录」主按钮)/ **contra** 日志与现状矛盾(紫染,「进入检测」=🔑 检验同一实现,P1-14;已登录时点它=对账不触发登录,未登录=真登;**入口=P1-15 启动分诊**:今早 fail ∧ 当下全好,开机自动落)/ **sad** 被拒(红染加重,互斥出口:凭据类 → 去登录页改+预填;bound/limit_users → 换账号?揭示「换一个账号/不换」);实时状态行三态(已登录✓ / 已连通·还没登录 / 还不通);快登五态(P1-12,见 §0 补注);恒有「带横幅回日常」次级出口;系统调起去重 `S.hubRaised`(同问题只弹一次,v-form 已键入豁免,v-guide 等网中不抢)→ 主页横幅⑧ 点开重进;在页迁移 `statusNetMood`(wait↔drop 就地换境,sad 只刷状态行,logged_in → `statusResolved` 清旗回日常) |
| v-guide | 不可达落地(琥珀加强状态条:danger+⚠+脉冲;greet 布局 + bot 哭脸) / 重新检测 busy(真调 probe,通了自动分流) / 日常开机落地(可返回,主页 down 态保留) / ③ 保存配置路径(P0-7 改口径:先保存配置,连上后一键就登);事件自动跳:恢复 not_logged_in → reProbe → configured ? 状态页 : v-form(login),他设备登好 → v-main |
| v-main | **两态(2026-09-11 P1-13,拍板⑪)**:①全部正常(问候语标题+基线 lede,无横幅)②带横幅(状态页/故障页返回自带);out/down 大字分支链已删(标题恒问候语,网络事实由「网络」行呈现 = netText 三态由 📡 探测喂;`#main-status` 状态条与 st-warn/st-down 随删);按钮恒「立即重新登录」(断网时 login→NET_UNREACHABLE→v-guide 诚实路由);bot 心境只认总开关(on=idle/off=sleep,动作 flash 临时覆盖);总开关关=桂桂睡觉(auto-desc「已关 · 想让我开工随时说」;`S.master` 镜像);横幅语义定稿(白板图例口径):**①未验证/验证失败提醒**(P0-5 条件,点击→📄 v-form)/ **②拦截态·master 开关联动**(关=任务停用+拦截解除,横幅即时隐退——toggleAuto 即刷+taskStatus 关=ok 双保险;开=点击就地重建 busy,后端单轮内自带 3 轮重试;连败计数 `S.rebuildFails`≥3 → 横幅换「重建 3 次没成 — 带上诊断包反馈」(P1-15,白板 re3;点击=复位计数+跳反馈页,返回后横幅回「点此重建」— 加白杀软后的再试通路不断))/ **③反馈相关**(再登连败 ≥2 → v-diag;文案拟稿)/ **⑧网态问题中枢入口**(hubRaised 在场即显,等网/未登录两文案,点击进 v-status;logged_in 自动消失);重登中 busy / 成功就地 flash / stored 如实;再登被拒 → 跳改密页预填;「今早没登上」横幅已删(最近结果行已显示) |
| v-log | 正常历史 / 含失败日 / 假期静默日 |
| v-settings | 默认(系统区含「立即体检」→ v-diag) / WiFi 兜底展开;「定时任务被拦」行已删(归主页横幅②) |
| v-feedback | 问题 / 建议 / 校验错误 / 发送中 / pending 行;两终态(复用 v-success 舞台):收到 / 没发出去(草稿回填重发 + 等待自动补发) |

## 2. net:state 事件路由表(2026-09-10 第三批重写:configured 用户带网态问题 → 系统调起状态页;未配置走旧路 v-guide;代码侧 `ROUTE`/`routeNet` 表驱动,与本表逐格对应)

| 当前视图 | unreachable(waiting 压平同格) | logged_in | not_logged_in |
|---|---|---|---|
| v-boot(configured) | `hubRaise('wait')` 调起状态页(拍板⑪:老用户开机带网态问题直接进;firstRun 同拍,深链让位) | mainState=ok → boot-cap 提示 → goDaily(900ms) | mainState=out → 900ms 后 enterStatus('drop') 调起状态页(firstRun 同拍) |
| v-boot(未配置) | 550ms 后跳 v-guide(show 直转,仪式单行道不记来路) | 留页不动(仪式等 firstRun 的 probe 分流,事件不抢路由) | 同左 |
| v-guide | 留在排查页(未配置用户的断网落点;configured 用户被 `hubRaise` 拦住不会到这页) | mainState=ok → goDaily(550ms) | reProbe 重探(550ms)→ probe:not_logged_in → configured ? 状态页 : v-form(login) |
| v-main | `hubRaise('wait')` 调起;去重拦下(已弹过同问题)→ 就地重渲(P1-13 两态:标题不换,「网络」行+横幅⑧如实) | ok 重渲 + 清 hubRaised(横幅⑧ 随消) | `hubRaise('drop')` 调起;拦下 → 就地重渲(同左两态口径) |
| v-form(2026-09-10 P2-1 合一) | **已键入(A3 formDirty)留页**:状态行就地转 danger、提交照常;空表单:configured → 调起状态页,未配置 → 直跳 v-guide(数据保留,回来还在) | 状态行实时刷新 + mainState 记对(返回主页不混搭) | 已键入留页同左;空表单:configured → 调起(drop),未配置 → 留页(等提交路径) |
| v-status | 在页迁移 `statusNetMood`:wait↔drop 就地换境(不重调起) | `statusResolved`:清旗回日常(全部正常) | 在页迁移同左 |
| 其他(v-success / v-diag / v-settings / v-log / v-feedback) | configured → 调起状态页;未配置 → 跳 v-guide(openDetail 记来路) | 记 lastNet,视图不动(返回时如实) | configured → 调起(drop);未配置 → 留页 |

> waiting 不单列:P0-3 拍板⑤起事件入口即压平为 unreachable,逐格行为一致(画廊切换器「未就绪 waiting」可验)。
> 代码侧 `ROUTE` 表在 `index.html`(`ROUTE`/`routeNet`,cell 词汇 goto/via/delay/then/render/when+else,when 链多级兜底);新增网态或视图 = 改表一行;「其他」行是默认行,新增详情视图自动继承。
> **hub 调起去重(P1-8)**:`hubRaise(kind)` 三道闸 —— 未配置不调起;`S.hubRaised` 同问题只弹一次(换问题照弹,v-guide 等网中不被 wait 抢);v-form 已键入豁免(A3)。调起被拦 ≠ 丢事件:主页就地重渲,横幅⑧(`hubRaised` 在场即显示)保留手动入口。
> **探测常驻(P1-8)**:`startProbeLoop` 每 5s 只读 probe(不触发登录),网态有变才发 net:state;`S.probeCount` 可观测。巡检「网」维度读探测结果(轮询不再各问各的)。
> **vt2 未验证库自动验证(P1-14,拍板⑫)**:`autoVerifyOnRecover(prev,next)` 挂在 net:state 处理器尾 — 迁移为「不可达→可达」∧ configured ∧ `recentResult().verified===false`(现拉真源)时自动跑 🔑(`statusQuickLogin(null,true)`);这是唯一保留的自动验证动作,已验证库的网恢复只调起状态页不自动登(P0-7);`S.vt2Busy` 防叠发;失败不在状态页时只横幅①,不调起打扰。

## 3. 用户场景映射(验收链)

| # | 场景 | 路径 | gallery 故事 |
|---|---|---|---|
| 1 | 可达+已登录 | 首装→v-form(firstRun)/ 日常→v-main ok | S1 / S2 |
| 2 | 可达+没登录 | 首装→v-form(login)/ 日常 out | S2 / S3 |
| 3 | 不可达不登录 | →v-guide(挑网→连上→自动跳 v-form login);空表单停留断网也直跳此页(表单已键入留页转 danger,A3/§2) | S3 / S5 / S5b |
| 4 | 可达但登录有问题(阶梯注销后没回滚) | 提交→logging_out→被拒;信封带接回/断着说明;后端节流变体已修 | S4 |
| 5 | 首装测试登录时切网→不可达,还在登录页 | 空表单直跳 v-guide(表单保留;已键入留页转 danger,A3);提交路径密码已存 → 保存配置终态 + 主页 down + 横幅① | S5 / S5b |
| 6 | 不可达→又可达→密码错 | v-guide 收 not_logged_in 自动跳 v-form(login)→ wrong_password → 改对成功 | S6 |
| 7a | 门没开(06:50 前)提交 | stored/before_open → 保存配置终态(锚前文案);主页重登返 stored 如实 | S7a |
| 7b | 节流 | note「让等 N 秒」;不进密码警告框 | S7b |
| 7c | 定时任务被拦 | 首装:拦截终态页 + 重建放行;日常:启动静默体检 / 轮询 → 主页横幅② 就地重建(设置页被拦行已删) | S7c / S8 |
| 7d | identify 误抓室友学号 | 预填他人号 → 用户直接改号提交(确认框已删,密码迁移静默)→ 或被拒 wrong_account 自纠 | S7d |
| 7e | 总开关关 | 主页 sleep bot「我先歇着」;P1-13 联动:任务停用+拦截解除,横幅②即时隐退(toggleAuto 即刷,重开后按真实任务态恢复) | S7e |
| 7f | 后端没绑上 | boot 页明说 BRIDGE_MISSING | S7f |
| 8 | 主页再登连败 ≥2(2026-09-08 新) | 计数器失败 +1 成功清零,≥2 → 横幅③(文案拟稿)→ v-diag 五步 → exit 路由(login/task_blocked/ok/app_fault/net_down);排查也没解决 → 反馈兜底 | 画廊 v-main 卡横幅③帧(连败故事位已被 S9 快登故事顶替,2026-09-10) |
| 9 | 显式体检(2026-09-08 新) | 设置页「立即体检」/ 横幅③ → v-diag 进入即自动开跑;启动静默只跑 probe+taskStatus 两项只读,全量五步只在此页(第 3 步真登有副作用,必须看得见) | S8 / S9 / 画廊 v-diag 卡 |
| 10 | 老用户断网 / 网恢复(2026-09-10 新,P1-8+P0-7) | 探测常驻(5s 只读)发现网态有变 → configured 用户带问题系统调起状态页(去重:同问题一次;v-form 已键入豁免;横幅⑧ 保留手动入口);网恢复 not_logged_in → drop 心境 + 快登;logged_in → 清旗自动回日常;未配置走旧路 v-guide 不变;「连上后自动登录」承诺文案已下线 | S10 / 画廊 v-status 卡 |
| 11 | 状态页快登五态(2026-09-10 新,P1-12) | 🔑 → 成功/already → 回日常全部正常(不撒彩带)/ throttled → 中性提示留页可再试 / 密码·学号错 → 沮丧 + 去登录页改(预填)/ 绑定·别设备 → 沮丧 + 换账号?(不换 → 带横幅回日常) | S9 / 画廊 v-status 卡 |
| 12 | 🔑 检验三入口(2026-09-11 新,P1-14) | 矛盾态「进入检测」=同一 🔑(已登录→对账不触发登录,未登录→真登)/ vt2:网恢复 ∧ 未验证库 → 自动验证(唯一自动动作;成功回日常横幅①消,already 静默不翻 verified,被拒→状态页在场转 sad、否则横幅①)/ 已验证库网恢复不自动(streak 开机即状态页,快登键等手动) | S10 / S9 / 画廊 v-status 卡 |
| 13 | 任务①②链三结局(2026-09-11 新,P1-17) | **建成+登上**:断网存配置(任务①建成→okpg2)→ 网恢复 vt2 自动登 → 日常全部正常 / **建成+登录失败**:明早任务跑(GUI 在场)→ 日志落「登录被拒」+ 网态翻未登录 → 系统调起状态页·蓝变红递快登(🅛 五态分流复用);任务仍在岗 **不进拦截页**、横幅②不亮 / **建成失败**:杀软拦 → 拦截页(断网语境经 taskStatus 复询分流);加白重建成功 → okpg2+「任务已修好」;🔔 通知(成功默认开/拦截要求加白/失败带原因)全在后端 ensure/notify 侧 | S11 / S10 / 画廊 v-success 卡 |
| 14 | 巡检分诊+任务链 3 败(2026-09-11 新,P1-15) | **日志维度分诊**:今早明确失败 ∧ 当下全好 → 开机直落 contra 状态页(「进入检测」=🔑 对账收场回日常,verified 不翻横幅①留);silent/throttled 不分诊;负样本 daily/streak 开机照常 / **任务链 3 败**:后端 rebuildTask 单轮 3 次重试环;拦截页/横幅②三连败换反馈出口(附诊断包),点击复位计数复原重建入口;程序/库两维 = 契约 1.6.0 缺口(见 §0 巡检注) | S12 / S8 第 4 步 / 画廊 v-status contra 帧 + v-main 3 败帧 |

## 4. 修复记录

| 日期 | commit | 内容 |
|---|---|---|
| 2026-09-07 | 9217f94 | 后端:阶梯节流拒到底补 `_restore_network` + 回归测试 |
| 2026-09-07 | 613b4df | 前端:net:state 六洞(v-login/v-ok 状态行实时、boot 开门按实际态、v-guide logged_in 接住等);mock 补 ladder_fail / ladder_back / beforeopen |
| 2026-09-08 | 4eb6666 | P0:错误路由统一(断网唯一落点 v-guide)+ 终态收敛三态 + 反馈两终态 + 换学号确认框删 + 横幅重做(删「今早没登上」) |
| 2026-09-08 | 0acdc60 | P1:diagnose 验证器(契约 1.4.3→1.5.0,§2.18 + diag:progress 事件)+ v-diag 页 + 两入口(设置页「立即体检」/ 横幅③)+ 登录页结论预填 + 失败计数 |
| 2026-09-08 | (本提交) | P2:矩阵/画廊同步 — mock streak 场景(重登连败)、画廊 v-diag 卡、横幅③ 帧(拟稿待用户过目)、S8 启动静默任务体检 / S9 连败→排查→反馈 两故事 |
| 2026-09-10 | 633435f | P2-1 表单合一:v-ok + v-login 并为 v-form 一套 DOM 三语境(formMode/submitLadder/syncFormStatus 唯一实现);画廊两卡并一卡 17 帧;本表 §1/§2/§3 与 NOT_CONFIGURED 行同步;视觉不变经三语境截图对照验证(基准存 dev/p2-1-before/) |
| 2026-09-10 | (本提交) | P2-2 路由数据化:net:state if 链 → `ROUTE` 查表 + `netToMain` 唯一压缩(4 处三元收口);A3 formDirty 豁免落地(表单已键入断网不跳页、状态行转 danger、提交照常,AC-3 两半实测);画廊 S5b 故事 + v-form 留页帧 + netctl/S5 注记;§1/§2 重写为与代码表逐格对应;视觉零变化经同会话 A/B 验证(0.137% < 噪声底 0.359%,证据存 dev/p2-2-before/、p2-2-after/、p2-2-abtest/) |
| 2026-09-10 | (本提交) | 第三批 P1-8/P1-10/P1-12/P0-7:探测常驻(5s 只读,net:state 只在网态有变时发)+ 大头状态页 v-status(四心境/实时状态行/互斥出口)+ 快登五态 + 网恢复系统调起(hubRaise 三道闸去重,横幅⑧ 手动入口);mock 对齐后端 unreachable 存未验证 + `_setRej` 驱动钩子;补 angry botIn 入场规则(此前 drop/sad 心境 bot 停 opacity:0)+ sad 红染加重(24%);画廊 v-status 卡 7 帧 + 横幅⑧ 2 帧 + S9 重写 + S10 新增;本表 §0 补注/§1 v-status 行/§2 重写/§3 #10#11 |
| 2026-09-11 | (本提交) | 第三批 P1-13 日常页两态化:renderMain 删 out/down 分支链(标题恒问候语,网络事实归「网络」行=📡探测喂;`#main-status` 状态条/st-warn/st-down CSS/wakeProblem 随删);按钮恒「立即重新登录」(mainAction 去分支,断网走 NET_UNREACHABLE→v-guide);总开关联动(`S.master` 镜像 setAuto 唯一写入,横幅②加 master!==false 条件,toggleAuto 即刷横幅);横幅①②③语义定稿注记;画廊 v-main 卡重拍 13 帧(两态①②、①+⑧并存、②联动隐退;out/down 帧删)+ S5/S9 故事文案跟进;本表 §0/§1/§2/§3 同步 |
| 2026-09-11 | (本提交) | 第三批 P1-14 🔑 检验自适应服务:`statusQuickLogin(btn,auto)` 收为三入口同一实现(状态页快登/矛盾态「进入检测」改道不再走 v-diag/vt2 自动验证);`autoVerifyOnRecover` 挂 net:state 尾(不可达→可达 ∧ configured ∧ verified=false 现拉 recentResult → 自动跑 🔑,vt2Busy 防叠发);auto 语境:成功不拽人交 ROUTE、already 静默不冒领(verified 不翻)、被拒不在状态页只横幅①;实测 9 组全绿(对账仅 probe 无真登/真登成功/两负样本/失败两分支/already 静默竞态修复/主页重登+手动 sad 回归/down 存配置全链);画廊 contra 帧注记+S9 补已验证库不自动+S10 第 4 步改 vt2;本表 §0 补注/§1 contra/§2 vt2 注/§3 #12 |
| 2026-09-11 | (本提交) | 第三批 P1-16/P1-17 成功页矩阵 + 任务①②生命周期:okpg2 定稿(不可达语境标题「保存配置成功,今天/明早 HH:MM 见」时间动态 + 「回排查页」唯一出口、高级设置出口收掉对齐白板;锚前/降级变体不动);彩带口径收口(=用户在场的验证通过,无人值守成功不弹彩带——实测 GUI 在场任务成功停 v-main);submitLadder 不可达分支补 taskStatus 只读复询分流拦截页(任务①建成失败落点,信封不带 task_ok 故复询;查询失败按建成放行);任务②侧零结构改动(明早任务跑=FileWatcher 翻译的 net:state/log:appended 走既有 ROUTE/横幅管线,登录失败不进拦截页——实测);mock 加 `_setTaskOk`/`_runMorningTask` 驱动钩子;画廊 v-success 卡 8 帧(新增拦截变体+重建放行)+ S5/S10 文案跟进 + S11 新故事;本表 §0/§1/§3 #13 同步 |
| 2026-09-11 | (本提交) | 第三批 P1-15 故障带自愈四链(契约纪律分层):**日志链** — 启动巡检日志维度分诊(firstRun configured∧logged_in 拉 recentResult,今早 fail → contra 状态页,P1-10 contra/P1-14「进入检测」自此接通真实入口;silent/throttled 不分诊;②③两路已由网态调起接管);**任务链** — rebuildTask 后端 3 轮重试环(api.py,信封 ok=false 即 3 败,pytest +2=281 全绿)+ 前端拦截页/横幅② 3 败反馈出口(S.rebuildFails 共用计数、renderBanners 正式渲染、点击反馈出口即复位计数复原重建入口);**程序/库链** — 契约 1.6.0 缺口列单待拍板(§0 巡检注含 🔔 J 章表逐行对账);mock `_setTaskOk` 加 sticky;实测 10 组全绿(分诊正负样本/两入口 3 败/反馈出口复原/成功清零/blocked 回归);画廊 contra 帧改 unverified 真开机 + v-main unverified 两帧适配 + 3 败帧 + S8 补第 4 步 + S12 分诊故事(十七→十八);本表 §0/§1/§3 #14 同步 |

## 5. 执行约定(零上下文可续:新对话或 subagent 接力同规,2026-09-11 拍板)

- 测试基准:仓库根 `python -m pytest guigui/tests -q`(当前 281 全绿);前端语法 `node -e "new Function(提取的 script)"`。
- 契约变更走 `docs/tech/guigui-bridge-api-v1.md` 版本号,前端 mock(`static/dev/mock.js`)与后端(`guigui/app/api.py`)同场景逐字一致。
- 状态画廊:`guigui/app/static/dev/state-gallery.html`(仅 dev,打包排除 `static/dev/`;10 视图 × 全部状态帧 + 十八故事,须 http 打开;2026-09-10 P2-1 后 v-ok/v-login 并为 v-form,第三批加 v-status 卡);新增状态必须同步画廊帧,否则美术看不到。
- 摆拍约定:走产品全局函数/事件入口(quickLogin/openDetail/guiguiEmit 等),let 变量(mainState/loginFailStreak)不可跨窗口直赋。
- 不顺手修:画廊/矩阵之外的风格问题单独开任务,别混提交。
