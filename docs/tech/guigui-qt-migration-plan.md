# 桂桂 PySide6(Qt)迁移计划

> 2026-09-06 立项。动机:WebView2 壳的三类固有税——内存基线 100MB+、
> 无边框窗口靠 SetWindowRgn 胶水层(黑角/白角/拖动卡顿三次踩坑的根源)、
> PyInstaller+Python 冷启动慢。PySide6 是唯一保留 Python 业务层的原生路线。

## 0. 原则(全阶段有效)

1. **`guigui/core/` 一行不改,193 测持续全绿。** 迁移只动"壳 + UI 层"。
2. **契约 v1.2.0 语义原样保留**:方法名、信封 `{ok,data}/{ok,code,message,reason}`、
   事件名(net:state / log:appended / schedule:changed)、拒绝三态 reason。
   变的只是传输层:js_api 桥 + evaluate_js → QObject 直接调用 + Qt Signal。
3. **视觉逐像素复刻**:8 视图以现版 `app/static/index.html` 为唯一基准
   (它是 PRD 原型的逐字节实现)。OKLCH 色彩、9px 圆角配方、自绘下拉、
   bot 眯眯眼、按钮三级分层,全部照抄语义,不趁机"改良设计"。
4. **web 壳迁移期共存,验收后冻结**:`gui.py` 与新 Qt 壳并存开发,
   M5 验收通过后 web 壳归档(不删历史),`static/` 冻结只读。
5. 线上在岗的 v1(dist)与官网分发链全程不动,直到新包替换。

## 1. 技术选型(定死,不再摇摆)

| 决策 | 选择 | 理由 |
|---|---|---|
| UI 技术 | **Qt Quick(QML)**,不用 Widgets | 渐变/发光/圆角/时间线动画是 QML 一等公民;Widgets 的 QSS 表现力不够复刻现版视觉 |
| 绑定 | **PySide6 ≥ 6.7**(LGPL) | 官方 Python 绑定;6.7 起可变字体轴稳定支持(思源宋体 VF 依赖) |
| 无边框圆角 | `FramelessWindowHint` + `WA_TranslucentBackground` + QML 根节点 `radius` | Qt 的透明窗口是一等公民(真 alpha 通道),**rgn 胶水全家(keeper/trackers/SetWindowRgn)整体删除**——本次迁移最大红利 |
| 阴影 | QML `MultiEffect`(Qt 6.5+) | QML 无 box-shadow,MultiEffect 是官方替代 |
| bot 动效 | QML `Shape`(几何)+ `SpringAnimation`(物理)重写 | 现 `xiaojiang-motion.js` 629 行 = SVG 绘制 + 弹簧物理 + 10 状态机;弹簧 QML 原生免费 |
| 彩带 | `QtQuick.Particles` | 替代 vendor 的 confetti.browser.min.js |
| 字体 | `fonts/` 目录平移(NotoSerifSC-VF + Inter 三字重) | QFontDatabase 加载,零转换 |

## 2. 阶段与里程碑

### M0 · Spike 三关(2 天,止损点)

新目录 `guigui/qtapp/`,只做一页主窗口空壳,过三关:

1. **圆角关**:560×640 无边框透明窗 + radius 8,四角无黑/白/紫角;
   150% DPI 复查;MultiEffect 阴影观感与现版等价。
2. **字体关**:思源宋体 VF 三档字重(细/常规/粗)渲染正确,
   截图与 WebView2 现版并排对照;Inter 同测。
3. **动画关**:bot 眯眯眼 + 一次状态切换(sleep→happy)弹簧动效 60fps;
   Particles 500 粒子彩带不掉帧。

附基线测量:冷启动秒数、常驻内存(目标 <80MB,对比现版 WebView2 ~100MB+)。

**任一关不过 → 停,写结论归档,沉没成本 2 天。** 这是"大胆"的保险丝。

### M1 · 壳(1-2 天)

- `qtapp/main.py`:QApplication + 无边框窗口 + 标题行拖拽(mousePressEvent,
  只认标题行,对应现在的 `pywebview-drag-region` 纪律)。
- 最小化/关闭按钮、窗口居中(注意 v1 踩过的窗口公式问题,用 Qt 自己的居中)。
- 单实例锁、`guigui://` 深链、FileWatcher、通知:纯 Python 模块**平移复用**。
- 删除等价物:rgn 全家、region keeper、Resize/LocationChanged 钩子。

### M2 · 视图迁移(核心三视图 3-5 天;全 8 视图 + 组件库 1-2 周)

迁移顺序(由简到繁、先主干后枝叶):

1. `v-boot` 开机仪式(最简,验证视图切换机制)
2. `v-main` 日常页(核心:口吻行/三行服务条/总开关/日志钉底)
3. `v-settings` 设置页(控件最密:开关/自绘下拉/时间药丸/连体输入组)
4. `v-ok` / `v-login` 表单两页(输入验证/密码眼睛/运营商别名层)
5. `v-guide` / `v-success` / `v-log`(引导/庆祝+彩带/历史日志)

组件库(QML 组件,对齐现 CSS 类):三级按钮(.btn/.link/.tbtn)、自绘下拉
(菜单同宽对齐、六项全显)、开关 .sw、时间药丸、bot(Shape+Spring 重写)、
自制滚动条。视图切换 = StackLayout + 过渡(对应现在 .v 的 leaving/on)。

### M3 · 桥接层(1-2 天)

- `api.py` 方法体不动;新增 `qtapp/bridge.py`:QObject 暴露方法(QML 直调)
  + Signal 推事件(替代 `guiguiEmit`)。
- **mock/dev 工作流重建**:devshell 退役;`GG_SCENE=bind python -m guigui.qtapp`
  场景注入,mock.js 的 9 场景表(ok/out/down/waiting/daily/rejected/bind/other/
  unverified)移植为 Python dict → bridge 层拦截。契约"两边逐字一致"的校验
  从 JS mock 移到 pytest(直接断言 api.py 返回)。
- 契约文档更新:传输层章节改 Qt,语义不变,版本 1.3.0。

### M4 · 打包(1-2 天)

- PyInstaller spec 重写:排除未用 Qt 模块(sql/network 之外按需裁),
  预估体积 24MB → 50-60MB(实测为准)。
- Inno Setup 微调(产物路径、卸载项);免管理员安装策略不变。
- **杀软观察:PySide6 exe 的特征与 PyInstaller+webview 不同,火绒重新过一遍**;
  toast 指引兜底保留。

### M5 · 验收与切换(1 天)

- 193 测全绿 + 新增桥层 pytest(事件推送/场景注入)。
- 8 视图逐屏截图对照现版(像素采样,复用视觉量化方法)。
- 启动/内存/安装包体积三数字记入文档。
- 通过 → web 壳归档、入口切 Qt、发版;不通过 → 列差距回炉。

## 3. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 可变字体轴在 PySide6 表现不符 | 中 | spike 第二关前置;不过则换思源宋体静态三字重文件 |
| QML 阴影/发光观感与 CSS box-shadow 有差 | 中 | MultiEffect 参数对照调;最坏自绘 pre-render 阴影图 |
| bot 动效重写出细微走样(最大单项工作) | 中 | 眨眼+两状态先过关;以现版录屏为对照基准 |
| 打包体积涨幅超预期 / 杀软新特征 | 中 | M4 实测;裁剪清单兜底 |
| dev 工作流变慢(QML 无 mock 同构) | 低 | M3 场景注入补齐;qmllint 进常规自检 |
| Qt 透明窗口在个别显卡驱动的合成怪癖 | 低 | spike + M1 各机型抽查;最坏退 QSS 圆角(不透明底色方案) |

## 4. 明确不做

- core/ 业务逻辑重构(登录阶梯/调度/凭据/自愈全不动)
- 契约语义变更、视图结构重排、文案改动
- 跨平台(Linux/macOS)、托盘常驻(GUI 低频定位不变)
- v1 与官网分发链的任何变动
