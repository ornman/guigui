# 桂桂官网(产品落地页)

桂桂 / GuiGui 的对外产品官网。单 HTML,双主题(Win11 / 桂航宇宙),顶导一键切换。

## 怎么打开

直接双击 `index.html` 即可,不需要任何构建步骤、服务器、依赖。

## 文件结构

```
docs\prd\guigui-site\
├─ index.html              # 单页双主题,内联 <style> + 内联 <script>
├─ vendor\
│   └─ xiaojiang-motion.js # 桂桂吉祥物组件(MIT,来自 bumbum55/noteai-bot)
├─ assets\
│   ├─ logo.svg            # 桂林航天工业学院校徽(单色蓝 #04459b)
│   └─ screenshots\        # 产品截图
└─ README.md
```

## 主题切换

- 顶导右侧有 `Win11 ⇄ 桂航宇宙` 切换按钮
- 主题选择存在浏览器 `localStorage` 的 `guigui-site-theme` 键
- 刷新页面会保留上次的选择

## 校徽来源

`assets\logo.svg` 拷贝自 `E:\桌面\桂林航天工业学院.svg`(桂林航天工业学院官方校徽,单色蓝 `#04459b`,扁平矢量)。

校徽元素:外圆环 + 校名环绕 + 内圆环 + 五角星 + 火箭 + 卫星轨道 + 经纬网格。

## 上线到正式服务器时需要替换的占位

- 顶导 / Hero / 页脚所有 `href="#"` → 真实 URL
- `meta og:title` / `og:description` / `og:image` → 真实截图
- README 顶部地址信息 → 桂航最新地址(从学校官网核对)

## 接 GitHub Pages

把整个 `guigui-site\` 目录扔进 `gh-pages` 分支即可。无需配置。

## 接 Vercel

`index.html` 同名,无需配置。