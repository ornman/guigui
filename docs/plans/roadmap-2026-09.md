# Roadmap 2026-09(下一阶段规划)

> 状态:生效(常青,完成即收口)。前一阶段:ui-interaction-rework v2 已闭环(2026-09-11,F-② 21/21 + F-②a 18/18 + F-④ AC 2/2);杀软整改批 ADR-0001~0004 已落地(322 测)。本表只管**接下来**。
>
> **执行约定**(零上下文适用):测试基准 = 仓库根 `.venv-guigui` pytest,**322 只增不减**;契约变更必须 bump + 登记(docs/tech/guigui-bridge-api-v1.md);不顺手修;拍板项呈报不代拍;每单元 git commit(中文,说清做了什么为什么);subagent 接力用 `docs/gov/prompt-templates.md` T3 模板。

## P0 · 拍板解锁(用户动作,agent 不得代拍)

| 事项 | 入口 | 状态 |
|---|---|---|
| 签名预算/路径(Trusted Signing / OV 证书 / 开源免费档) | docs/adr/0005-code-signing-strategy.md | 事实表已列,待用户拍 |
| 停试阈值 + Wake 降级文案 | docs/adr/0006-scheduling-surface-and-backoff.md | 拍后即纯执行 |
| 契约 1.6.0 余项(库链/程序链/通知矩阵/冷却/深链等缺口) | docs/tech/guigui-bridge-api-v1.md §5 变更记录 | 2026-09-11 前已呈报,仍待裁决 |
| H 表(横幅)拟稿 + P1-11 及衍生拍板项 | ui-interaction-rework 计划文档收尾段 | 同上,已呈报待过目 |

P0 任一项拍板后:配套实施即为纯执行项,按 ADR/计划文档自动接力。

## P1 · 验收欠账(agent 可执行,按序)

1. **安装器重出** ✅ 已重出(2026-09-12):ISCC 实为 per-user 安装(`%LocalAppData%\Programs\Inno Setup 6\ISCC.exe`,6.7.3;09-11 ADR-0004 批「本机无 ISCC」系漏检 per-user 路径),PyInstaller + ISCC 重跑,产物 `guigui/Output/guigui-setup-2.0.0.exe`(2026-09-12 01:39,含 ADR-0004 卸载补删四任务);**待用户实机验收**:装→开→卸,四任务全删。
2. **真机三件**(需在校环境,计划见 SPEC §7):锚点窗口期实测(06:50 前后)、bind 解绑补测(测试账号)、返校日实跑(boot 拍豁免链)。
3. **审计附录 A 小瑕疵批** ✅ 完成(2026-09-12,commit 6b9bd5d/c8631f0/4255f50):wifictl SSID XML 转义(+2 测)、临时文件自有前缀 + 入口 sweep 陈旧残留(+2 测)、vault 持久化常量注释澄清;附录 A-4(凭据在岗自检)仍挂 R7 待文案过目,不在本批。

## P2 · 工程化(agent 可执行)

1. **门禁自动化**(2026-09-10 已确认缺口):pre-commit 钩子跑快速档 pytest(全量 48min 太重,选集合或 -k 冒烟)+ commit 信息规范检查;方案先落 docs/plans/ 再动手。
2. **文档存量对账** ✅ 完成(2026-09-12,commit 972eed4):四份已闭环(qa-fix-plan-2026-09-07 / ui-routing-rework-2026-09-08 / ui-flow-rework-2026-09-08 / ui-interaction-rework-2026-09-09);**存疑 1 份**:guigui-package-fix-plan-2026-08-31 的 Task 7 实机 6 项人工清单在审计文档中标注「待人工验证」且从未回填,无旁证,未标已闭环,待用户裁决(该清单针对 08-31 版安装器,当前安装器已重出,验收可并入 P1-1 装机验收一并做)。
3. **1.6.0 文档收口核对**:契约 §5 所列余项与 P0 拍板结果对齐后,统一收口一次(版本/变更记录/矩阵同步)。

## 明确不做(防跑偏)

- 不做托盘/常驻、不做通用化跨校、不做 AI 写作类功能(SPEC §4 决策基线);
- 不动 legacy-v1/;不在无拍板情况下实施 ADR-0005/0006;
- 调度机制不换(审计 §5 论证),新想法先过 ADR。
