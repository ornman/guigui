# 桂桂 v2 前端保真审计记录(F5)

> 2026-08-31,前端工作流产出。目的:证明「应用前端 = PRD 原型 100% 还原」并登记全部有意差异。
> 基准:`docs/prd/guigui-prd-v2.html`(冻结)。被审:`guigui/app/static/`。

## 一、证据链

| 层 | 方法 | 结论 |
|---|---|---|
| CSS | 与原型逐字节 diff(F1 时脚本断言) | 主 `<style>` 块零改动;唯一增量 = `#app-overrides`(字体 @font-face + 应用模式透明背景) |
| DOM(逐视图) | 双页同状态 innerHTML 比对,归一化后 diff | **内容级全部一致**;v-success 归一化后完全相等 |
| 视觉 | 双页同视口截图 + WebView2 实窗视检 | 元素/字体/配色/布局一致;透明圆角无边框在 WebView2 下成立 |
| 交互 | 逐项驱动 | 时间跳格/越界校验/药丸联动/下拉互斥+持久化/开关同步/bot 情绪/彩带采样(440 粒子)/来路栈回退 全过 |
| 哨兵子集 | grep(design-taste §9.G/§6/§4.5/§9.A) | em-dash 仅存在于注释;#000/#fff 全部来自原型基准 CSS(舞台底/mask 技术);无新增动画 |

## 二、比对时归一化的项(非差异)

- bot 注入的 SVG 几何(活体动画逐帧不同,容器/尺寸/状态机一致)。
- `value` 属性(JS 设值不回写属性)与内联 style 序列化空格(`display:none` vs `display: none;`,计算态相同)。
- 动态渲染挂点:`id`(ok-status / login-status / guide-server / guide-cur / main-last / main-log-entries / log-days / f-sid-login)。

## 三、有意差异清单(全部可追溯到需求)

| # | 差异 | 依据 |
|---|---|---|
| 1 | 删除演示道具:`.demo` 按钮、假任务栏、`#pill` 胶囊、`backdrop-win11` 假壁纸 | 原型舞台道具,非产品 |
| 2 | 删除预填占位学号/密码 | 原型头注安全要求(P0);契约 §0 凭据纪律 |
| 3 | 设置控件挂 `data-cfg`/`toggleCfg`/`data-v`,选择即存 | 契约 2.7 saveConfig |
| 4 | v-log 外层 `#log-days` 容器 div(无样式) | 动态填充需要 |
| 5 | v-guide「重新检测」onclick `reProbe()`(原型为演示用 `bootWait()`) | 真实重探测语义 |
| 6 | WiFi 兜底列表按需渲染(原型硬编码 3 行) | 契约 2.4 scanWifi |
| 7 | 「昨晚」行/主页网行按数据渲染,新增 fail/silent/none 文案 | 契约 2.10;原型只示范了 ok 态 |
| 8 | titlebar 加 `pywebview-drag-region` 类 | 无边框拖拽(pywebview 6 约定) |

## 四、遗留产品问题(已登记,不阻塞)

- v-guide 候选列表是否应过滤非校园网(热点):契约 scanWifi 返回全部,前端全渲染;是否过滤属后端/产品决策。已记入契约「集成待办」。
- minimize 真行为未实测(CUA 坐标限制);与 close 同走 `GG.win`→`winMinimize()`,链路一致,风险低。
