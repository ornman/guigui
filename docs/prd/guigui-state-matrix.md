# 桂桂 UI 状态矩阵(2026-09-07 全边界盘点)

> 起因:用户盘点「前端业务逻辑和 UI 态一堆洞」,列出日常/首装 × 网络七场景。
> 本文档是**状态总账**:全部状态、每个视图的态、事件路由表、七场景映射、修复记录。
> 活的形式见 `guigui/app/static/dev/state-gallery.html`(陈列矩阵 + 场景流程 + 网络切换器)。

## 0. 两轴状态模型

### 网络态(后端 probe / net:state 事件,契约 §2.1)

| state | 含义 | 前端 mainState | 主页标题 |
|---|---|---|---|
| `logged_in` | 已认证在线 | `ok` | 问候语。 |
| `not_logged_in` | 服务器可达、未认证 | `out` | 呜,刚才掉线了。 |
| `unreachable` | 认证服务器够不着 | `down` | 现在连不上校园网。 |
| `waiting` | 网络栈未就绪(刚开机/WiFi 在连) | (bootWait 等门,不进主页) | — |

### 登录结果(login 信封,契约 §2.3)

| result / code | 语义 | 前端落点 |
|---|---|---|
| `success` + verified | 真验证通过 | 庆祝页(彩带) |
| `success` + verified + task_ok=false | 登上了但定时任务被拦 | 庆祝页变体(重建入口) |
| `already` | 已在线(线上是本人) | 庆祝页(无彩带,「明早会真验证」当 verified=false) |
| `stored` / reason=before_open | 06:50 前被拒,不判密码错,存未验证 | 庆祝页变体;主页重登也返此(2026-09-07 前端补如实文案) |
| `AUTH_REJECTED` reason=`wrong_password` | 密码不对,不存 | 错误行直显 |
| `AUTH_REJECTED` reason=`wrong_account` | 学号/运营商选错 | 错误行直显(identify 误抓室友学号的自纠出口) |
| `AUTH_REJECTED` reason=`bound` | 密码对但绑定被拦 | 错误行,「自助服务平台」六字内联可点 |
| `AUTH_REJECTED` reason=`limit_users` | 学号在别的设备在线 | 错误行(不冤枉密码) |
| `AUTH_REJECTED` reason=`throttled` | 节流,≠密码错,不存 | 中性 note「让等 N 秒再试」;阶梯路径带恢复后缀 |
| `AUTH_REJECTED` reason=`before_open` | 已存凭据路径的锚前被拒 | 「明早自动验证」 |
| `NET_UNREACHABLE` | 够不着服务器 | 首装/改密提交路径:**密码已存(未验证)**→ v-guide;主页重登 → v-guide |
| `NOT_CONFIGURED` | 没存凭据 | 主页重登 → 跳 v-login |
| `INTERNAL` / `BRIDGE_MISSING` | 兜底 | 2026-09-07 前补:三提交函数 + quickLogin 就地报原话,不再静默 |

### 验证阶梯(提交密码时线上已有人)

`logged_in` + 提交密码 → `logging_out` 事件(线上他人学号打码注明)→ 注销 → 等翻转 → 真登一次:

- 真登成功 → 存 verified ✓
- 真登被拒 → **旧凭据尽力把网接回**,信封带「已用旧密码把网接回来了,改对再点一次」/「网先断着,输对马上通」
- 真登被节流 → 2026-09-07 前补:同样尽力接回(原先直接 return,用户网断着+密码没存+被节流三重伤害,commit 9217f94)
- 注销无配置/未翻转 → 降级存入 already verified=false
- 中途不可达 → 尽力接回 + 存未验证 + NET_UNREACHABLE「密码先存着,明早首试见真章」

## 1. 视图 × 状态总表

| 视图 | 状态 |
|---|---|
| v-boot | 仪式检查中(sleep)/ 等门 bootWait(waiting)/ BRIDGE_MISSING |
| v-ok | 已连已登 / 学号已识别 / 验证中 busy / 注销告知 / 密码空警告 / 被拒 wrong_password / 被拒 bound / 节流 / **停留时断网(状态行 danger)** |
| v-login | 未登录落地 / 被拒五态(wrong_password / wrong_account / bound / limit_users / throttled)/ 验证中(注明他人学号)/ **场景4 注销后失败(网先断着)** / 场景4b 已接回来 / 换学号确认框 / **停留时断网** |
| v-success | 真验证成功 / already 未验证 / before_open 存好 / task 被拦 / 重建失败 |
| v-guide | 不可达 + wifi 列表 / (事件自动跳:恢复→v-login,他设备登好→v-main) |
| v-main | ok / master off / out 掉线 / down 不可达 / 双横幅 / 今早失败单横幅 / 重登中 busy / 重登成功 / 重登被拒 / **门没开 stored** |
| v-log | 正常历史 / 含失败日 / 假期静默日 |
| v-settings | 默认 / 任务被拦行 / WiFi 兜底展开 |
| v-feedback | 问题 / 建议 / 校验错误 / 发送中 / 已收到 / 断网入队 / pending 行 |

## 2. net:state 事件路由表(2026-09-07 修后,之前 v-login/v-ok 无人接)

| 当前视图 | logged_in | not_logged_in | unreachable |
|---|---|---|---|
| v-boot(configured) | mainState=ok → goDaily | mainState=out → goDaily(**原先不问 e.state 预写 ok,假绿已修**) | mainState=down → goDaily |
| v-guide | mainState=ok → goDaily(**原先无人接,已修**) | mainState=out → 跳 v-login | mainState=down(**记对状态,返回主页不装绿**) |
| v-main | ok 重渲 | out 重渲 | down 重渲 |
| v-login | 状态行刷新(已连通) | 状态行刷新 | **状态行 danger 连不上(场景 5 核心,已修)** |
| v-ok | 同上 | 同上 | 同上 |
| 其他(v-success 等) | 记 lastNet,视图不动(返回时如实) | | |

## 3. 用户七场景映射(验收链)

| # | 场景 | 路径 | gallery 故事 |
|---|---|---|---|
| 1 | 可达+已登录 | 首装→v-ok / 日常→v-main ok | S1 / S2 |
| 2 | 可达+没登录 | 首装→v-login / 日常 out | S2 / S3 |
| 3 | 不可达不登录 | →v-guide(挑网→连上→自动跳 v-login) | S3 |
| 4 | 可达但登录有问题(阶梯注销后没回滚) | 提交→logging_out→被拒;信封带接回/断着说明;后端节流变体已修 | S4 |
| 5 | 首装测试登录时切网→不可达,还在登录页 | 状态行实时变 danger(已修);提交→密码已存→主页 down+横幅(已修) | S5 |
| 6 | 不可达→又可达→密码错 | v-guide 收 not_logged_in 自动跳 v-login→wrong_password→改对成功 | S6 |
| 7a | 门没开(06:50 前)提交 | stored/before_open,成功页如实;主页重登返 stored(前端已补如实文案) | S7 |
| 7b | 节流 | note「让等 N 秒」;不进密码警告框 | S7 |
| 7c | 定时任务被拦 | 成功页 blocked + 重建;设置页被拦行 | S7 |
| 7d | identify 误抓室友学号 | 预填他人号→用户改号→确认框(密码迁移)→或被拒 wrong_account 自纠 | S7 |
| 7e | 总开关关 | 主页 sleep bot「我先歇着」 | S7 |
| 7f | 后端没绑上 | boot 页明说 BRIDGE_MISSING | S7 |

## 4. 修复记录(2026-09-07)

| commit | 内容 |
|---|---|
| 9217f94 | 后端:阶梯节流拒到底补 `_restore_network` + 回归测试(268 测) |
| 613b4df | 前端:net:state 六洞(v-login/v-ok 状态行实时、boot 开门按实际态、v-guide logged_in 接住、enableDaily 断网 configured/mainState 归位、quickLogin stored 如实+成功归位、三提交函数 INTERNAL 兜底);mock 补 ladder_fail / ladder_back / beforeopen |

## 5. 执行约定(新对话零上下文可续)

- 测试基准:仓库根 `python -m pytest guigui/tests -q`(当前 268 全绿);前端语法 `node -e "new Function(提取的 script)"`。
- 契约变更走 `docs/tech/guigui-bridge-api-v1.md` 版本号,前端 mock(`static/dev/mock.js`)与后端(`guigui/app/api.py`)同场景逐字一致。
- 状态画廊:`guigui/app/static/dev/state-gallery.html`(仅 dev,打包排除 `static/dev/`);新增状态必须同步画廊帧,否则美术看不到。
- 不顺手修:画廊/矩阵之外的风格问题单独开任务,别混提交。
