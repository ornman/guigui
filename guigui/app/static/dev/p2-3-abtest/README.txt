P2-3 store 收口 · 零回归证据(2026-09-10)

- p2-3-before/:改动前基线(daily/out/down 三场景,700x800,共享 user-data-dir)。
- p2-3-after/:改动后同视口同缓存三帧。
  daily 0.012%(bot 动画帧)/ down 0.000% / out 4.547% —
  ⚠️ out 的差异带(129-415 行,表单文本行)系 before 批次采集混杂:
  该帧是本 profile 首次以 login 表单渲染,字体子集未缓存,文本以兜底字体
  渲染(与 P2-2 的 daily-main.png 冷字体 9.6% 同因),不构成重构差异证据。
- p2-3-abtest/:决定性 A/B — git HEAD 旧 index.html 与工作区新 index.html
  同缓存连拍 out(最复杂的表单页):旧vs新 0.000%(逐像素一致),
  同码连拍噪声底 0.449%,视觉零变化成立。
- 行为验证(HEADLESS dump-dom):daily→v-main / out→v-form / down→v-guide /
  waiting→v-main(P0-3 等网自动恢复回日常)/ unverified→v-main+横幅① 1 条、
  waiting/daily 横幅 0 条(P0-5 精确条件)。
- 画廊 58 帧 CDP 真跑(强制懒加载+逐帧切换+摆拍错误收集):
  55 帧直接过;横幅③帧为异步链(quickLogin×2+backFrom,~5s)采样时机
  抖动,延时 9s 复检通过(v-main+横幅③在场);v-feedback 终态两帧落
  v-success 系固有设计(showFeedbackEnd 复用成功页舞台),HEAD 旧版基线
  复跑同 58 帧 FAIL 集一致 — 两版行为等价,零回归。
- 验收 grep:顶格 let 归零,仅剩 const S + 常量(VIEW_MS/MAIN_LOG_KEEP/
  DIAG_KEYS/NET_TXT/ROUTE 等)+ 函数 + bots/origin 容器;画廊白名单
  16 函数全部在位。
