P2-2 路由数据化 · 视觉零变化证据(2026-09-10)

- p2-2-before/:改动前基线(daily/out/down + down 恢复落点)。
  ⚠ daily-main.png 是本标签页首拍,冷缓存下 @font-face 字体未就绪,
  全页文本以兜底字体渲染 — 与 p2-2-after/daily-main.png 对照出 9.6% 差异,
  系采集混杂因素,不构成重构差异证据(见 p2-2-abtest/)。
- p2-2-after/:改动后同视口同会话四帧。out/down/recover 差异 0.086~0.345%,
  均在动画噪声底内。
- p2-2-abtest/:决定性 A/B — git HEAD 旧 index.html 与工作区新 index.html
  在同标签页同缓存下各拍 daily:旧vs新 0.137% < 同码连拍噪声底 0.359%
  (差异全部集中在 bot 动画帧),视觉零变化成立。
