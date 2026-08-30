# 小匠自动动作展示

一个无依赖、自动播放的静态展示页，用于录屏、产品演示或 GitHub Pages。

## 八幕轮播

待命、阅读、生气、提醒、Loading、资料汇入、诊断、睡觉。

开场品牌为「小匠 / XIAOJIANG」，副标题为「NoteAI 文档智能伙伴」。页面不监听鼠标，所有眼神和状态动画都会自行运行。完整播放约 35 秒，然后回到开场继续循环。

## 本地查看

直接打开 `index.html`，或者在本目录启动任意静态服务器。

## 发布到 GitHub Pages

1. 将本目录中的 `index.html`、`xiaojiang-motion.js` 和 `.nojekyll` 放进仓库根目录或 `docs/`。
2. 在 GitHub 仓库的 **Settings → Pages** 中选择对应分支和目录。
3. 页面只使用相对路径，可以部署在仓库子路径下，不需要构建命令。

轮播内容位于 `index.html` 中的 `scenes` 数组，调整顺序、名称或 `duration` 即可修改演示节奏。
