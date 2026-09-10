# 桂桂 UI 状态矩阵(2026-09-07 全边界盘点 · 2026-09-08 交互重构同步)

> 起因:用户盘点「前端业务逻辑和 UI 态一堆洞」,列出日常/首装 × 网络七场景。
> 本文档是**状态总账**:全部状态、每个视图的态、事件路由表、场景映射、修复记录。
> 2026-09-08 交互重构(docs/plans/ui-routing-rework-2026-09-08.md,P0+P1 已落地)
> 之后第 2 次同步:§0 落点列按终态收敛刷新,§1/§2 按新路由重写,§3 补验证器两行。
> 活的形式见 `guigui/app/static/dev/state-gallery.html`(陈列矩阵 + 场景流程 + 网络切换器)。

## 0. 两轴状态模型

### 网络态(后端 probe / net:state 事件,契约 §2.1)

| state | 含义 | 前端 mainState | 主页标题 |
|---|---|---|---|
| `logged_in` | 已认证在线 | `ok` | 问候语。 |
| `not_logged_in` | 服务器可达、未认证 | `out` | 呜,刚才掉线了。 |
| `unreachable` | 认证服务器够不着 | `down` | 现在连不上校园网。 |
| `waiting` | 网络栈未就绪(刚开机/WiFi 在连) | `down`(P0-3 起前端映射层压平 waiting≡unreachable,唯一落点 v-guide) | 现在连不上校园网。 |

### 登录结果(login 信封,契约 §2.3;前端落点 = 2026-09-08 终态收敛后)

完成是全有或全无:彩带只给「真验证通过 + 定时任务在岗」;客观验不了的诚实叫「保存配置」。

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
| `NET_UNREACHABLE` | 够不着服务器 | 提交路径:密码已存 → 保存配置终态(不可达文案),回主页 down + 横幅①;主页重登 → 跳 v-guide |
| `NOT_CONFIGURED` | 没存凭据 | 主页重登 → 跳 v-form(login 语境,P0-4 先给警告块再跳) |
| `INTERNAL` / `BRIDGE_MISSING` | 兜底 | 三提交函数 + quickLogin 就地报原话,不静默 |

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
| v-boot | 仪式检查中(sleep)/ BRIDGE_MISSING(bootWait 等门页已随 P0-3 删,waiting 落点同 unreachable);仪式期间静默任务体检(configured 时并行,只读秒回、2s 超时保护,用户无感) |
| v-form(2026-09-10 P2-1 合一,原 v-ok + v-login 并为一张 DOM) | **一套表单三语境**,由 `formMode(ctx)` 派生头部/按钮/状态行:**firstRun**(首装已连已登:问候标题+tagline+「开启每日自动登录」,密码必填,提交先落触发时间)/ **login**(未登录落地 / 改密 / 验证器结论预填:「登录校园网。」+「立即登录」)/ **save**(v-guide ③ 路径,按钮=「保存配置」,空密码可提交);共用状态:firstRun 学号已识别 / 验证中 busy / 注销告知 / 密码空警告(仅 firstRun)/ 被拒五态(wrong_password / wrong_account / bound / limit_users / throttled)/ 场景4 注销后失败两变体(网先断着 / 已接回);换学号确认框已删(密码迁移静默,验证不过当场自纠);提交走同一条 `submitLadder()`;停留断网 → 直跳 v-guide(表单数据保留);返回键=来路栈(首装期 body.setup 由 CSS 隐藏) |
| v-diag(2026-09-08 新,契约 1.5.0) | 进入即自动开跑(不用点开始) / 跑步中(diag:progress 逐拍上屏,running 脉冲) / 全绿 exit=ok / 凭据败 exit=login / 任务败 exit=task_blocked / 程序败 exit=app_fault(就地说明,无出口按钮) / net_down;页底固定小出口「排查也没解决?说给桂桂听 →」 |
| v-success | 终态三 + 反馈二(共用舞台):彩带(verified && task_ok) / 保存配置(不可达存入 · 锚前 · 降级三文案,bot idle 呼吸不撒彩带) / 拦截页(只留「重建定时任务」,bot sad 思考脸;重建失败变「没建成,再试一次」);反馈收到(工单号在文案行,按钮不带编号) / 没发出去(bot sad;立刻重发=草稿回填 + 完成等待自动补发) |
| v-guide | 不可达落地(琥珀加强状态条:danger+⚠+脉冲;greet 布局 + bot 哭脸) / 重新检测 busy(真调 probe,通了自动分流) / 日常开机落地(可返回,主页 down 态保留) / ③ 保存配置路径(连上后自动登录);事件自动跳:恢复 not_logged_in → v-login,他设备登好 → v-main |
| v-main | 四态:ok(问候语) / out(「再登一次」) / down(「去排查」) / off(总开关关,「我先歇着」);横幅①密码还没验证过(仅保存配置路径,点击直达改密页) / 横幅②任务被拦(点击就地重建,busy;失败变「没建成,再试一次」) / 横幅③再登连败 ≥2(点击进 v-diag;文案拟稿);重登中 busy / 重登成功(就地反馈) / 门没开 stored(lede 如实);再登被拒 → 跳改密页预填警告;「今早没登上」横幅已删(最近结果行已显示) |
| v-log | 正常历史 / 含失败日 / 假期静默日 |
| v-settings | 默认(系统区含「立即体检」→ v-diag) / WiFi 兜底展开;「定时任务被拦」行已删(归主页横幅②) |
| v-feedback | 问题 / 建议 / 校验错误 / 发送中 / pending 行;两终态(复用 v-success 舞台):收到 / 没发出去(草稿回填重发 + 等待自动补发) |

## 2. net:state 事件路由表(2026-09-08 路由统一后:断网只有 v-guide 一个落点)

| 当前视图 | unreachable | logged_in | not_logged_in |
|---|---|---|---|
| v-boot(configured) | 仪式后跳 v-guide(不再落主页 down;返回后主页 down 态保留) | mainState=ok → goDaily | mainState=out → goDaily |
| v-guide | 留在排查页(它正是落点) | 自动回主页 ok | 自动跳 v-form(login) |
| v-main | down 态重渲(「去排查」按钮;主页有自己的四态,不自动跳) | ok 重渲 | out 重渲 |
| v-form(2026-09-10 P2-1 合一) | **直跳 v-guide**(表单数据保留,回来还在;原先只刷状态行,2026-09-08 撤) | 状态行实时刷新 + mainState 记对(返回主页不混搭) | 同左 |
| 其他(v-success / v-diag / 详情) | 跳 v-guide | 记 lastNet,视图不动(返回时如实) | 同左 |

## 3. 用户场景映射(验收链)

| # | 场景 | 路径 | gallery 故事 |
|---|---|---|---|
| 1 | 可达+已登录 | 首装→v-form(firstRun)/ 日常→v-main ok | S1 / S2 |
| 2 | 可达+没登录 | 首装→v-form(login)/ 日常 out | S2 / S3 |
| 3 | 不可达不登录 | →v-guide(挑网→连上→自动跳 v-form login);任何视图停留断网也直跳此页 | S3 / S5 |
| 4 | 可达但登录有问题(阶梯注销后没回滚) | 提交→logging_out→被拒;信封带接回/断着说明;后端节流变体已修 | S4 |
| 5 | 首装测试登录时切网→不可达,还在登录页 | 直跳 v-guide(表单保留);提交路径密码已存 → 保存配置终态 + 主页 down + 横幅① | S5 |
| 6 | 不可达→又可达→密码错 | v-guide 收 not_logged_in 自动跳 v-form(login)→ wrong_password → 改对成功 | S6 |
| 7a | 门没开(06:50 前)提交 | stored/before_open → 保存配置终态(锚前文案);主页重登返 stored 如实 | S7a |
| 7b | 节流 | note「让等 N 秒」;不进密码警告框 | S7b |
| 7c | 定时任务被拦 | 首装:拦截终态页 + 重建放行;日常:启动静默体检 / 轮询 → 主页横幅② 就地重建(设置页被拦行已删) | S7c / S8 |
| 7d | identify 误抓室友学号 | 预填他人号 → 用户直接改号提交(确认框已删,密码迁移静默)→ 或被拒 wrong_account 自纠 | S7d |
| 7e | 总开关关 | 主页 sleep bot「我先歇着」 | S7e |
| 7f | 后端没绑上 | boot 页明说 BRIDGE_MISSING | S7f |
| 8 | 主页再登连败 ≥2(2026-09-08 新) | 计数器失败 +1 成功清零,≥2 → 横幅③(文案拟稿)→ v-diag 五步 → exit 路由(login/task_blocked/ok/app_fault/net_down);排查也没解决 → 反馈兜底 | S9 |
| 9 | 显式体检(2026-09-08 新) | 设置页「立即体检」/ 横幅③ → v-diag 进入即自动开跑;启动静默只跑 probe+taskStatus 两项只读,全量五步只在此页(第 3 步真登有副作用,必须看得见) | S8 / S9 / 画廊 v-diag 卡 |

## 4. 修复记录

| 日期 | commit | 内容 |
|---|---|---|
| 2026-09-07 | 9217f94 | 后端:阶梯节流拒到底补 `_restore_network` + 回归测试 |
| 2026-09-07 | 613b4df | 前端:net:state 六洞(v-login/v-ok 状态行实时、boot 开门按实际态、v-guide logged_in 接住等);mock 补 ladder_fail / ladder_back / beforeopen |
| 2026-09-08 | 4eb6666 | P0:错误路由统一(断网唯一落点 v-guide)+ 终态收敛三态 + 反馈两终态 + 换学号确认框删 + 横幅重做(删「今早没登上」) |
| 2026-09-08 | 0acdc60 | P1:diagnose 验证器(契约 1.4.3→1.5.0,§2.18 + diag:progress 事件)+ v-diag 页 + 两入口(设置页「立即体检」/ 横幅③)+ 登录页结论预填 + 失败计数 |
| 2026-09-08 | (本提交) | P2:矩阵/画廊同步 — mock streak 场景(重登连败)、画廊 v-diag 卡、横幅③ 帧(拟稿待用户过目)、S8 启动静默任务体检 / S9 连败→排查→反馈 两故事 |
| 2026-09-10 | 633435f | P2-1 表单合一:v-ok + v-login 并为 v-form 一套 DOM 三语境(formMode/submitLadder/syncFormStatus 唯一实现);画廊两卡并一卡 17 帧;本表 §1/§2/§3 与 NOT_CONFIGURED 行同步;视觉不变经三语境截图对照验证(基准存 dev/p2-1-before/) |

## 5. 执行约定(新对话零上下文可续)

- 测试基准:仓库根 `python -m pytest guigui/tests -q`(当前 279 全绿);前端语法 `node -e "new Function(提取的 script)"`。
- 契约变更走 `docs/tech/guigui-bridge-api-v1.md` 版本号,前端 mock(`static/dev/mock.js`)与后端(`guigui/app/api.py`)同场景逐字一致。
- 状态画廊:`guigui/app/static/dev/state-gallery.html`(仅 dev,打包排除 `static/dev/`;9 视图 × 全部状态帧 + 十四故事,须 http 打开;2026-09-10 P2-1 后 v-ok/v-login 并为 v-form);新增状态必须同步画廊帧,否则美术看不到。
- 摆拍约定:走产品全局函数/事件入口(quickLogin/openDetail/guiguiEmit 等),let 变量(mainState/loginFailStreak)不可跨窗口直赋。
- 不顺手修:画廊/矩阵之外的风格问题单独开任务,别混提交。
