# fonts/ — 内嵌字体(保真用)

目的:PRD 设计基准(`docs/prd/guigui-prd-v2.html`)的字体栈在分发机器上不存在时,
由 `index.html` 的 `#app-overrides` @font-face 内嵌加载,保证任何机器渲染一致。

| 文件 | 族名 | 用途 | 来源 | 许可 |
|---|---|---|---|---|
| `NotoSerifSC-VF.ttf` | "Source Han Serif SC" / "Noto Serif SC"(双别名,同一文件) | 正文衬线(思源宋体,可变字重 100–900) | google/fonts Noto Serif SC VF | OFL-1.1 |
| `Inter-Regular.ttf` | Inter | UI 元件 400 | rsms/inter v4 静态实例 | OFL-1.1 |
| `Inter-Medium.ttf` | Inter | UI 元件 500(药丸/下拉) | 同上 | OFL-1.1 |
| `Inter-SemiBold.ttf` | Inter | UI 元件 600(标签/标题栏) | 同上 | OFL-1.1 |
| `Inter-Bold.ttf` | Inter | `<b>` 加粗 700 | 同上 | OFL-1.1 |

- 完整许可文本见 `OFL-1.1.txt`(Noto 与 Inter 均适用);分发安装包时须随附本目录或许可文本。
- 中文 UI 元件字形走系统 sans 兜底(`"PingFang SC",sans-serif` → Windows 上为雅黑),
  与设计基准在本机的实际渲染路径一致,不额外打包。
- 体积说明:NotoSerifSC-VF 约 24MB,是安装包体积的主要构成;如后续需瘦身,
  可换子集化静态字重(需覆盖日志/设置的动态中文,谨慎),由前端工作流统一决策。
