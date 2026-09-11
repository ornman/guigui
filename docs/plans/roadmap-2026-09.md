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

1. **安装器重出**:本机装 ISCC(或换机)跑构建链,把 ADR-0004 补删打进安装包;验收 = 装→开→卸,四任务全删。
2. **真机三件**(需在校环境,计划见 SPEC §7):锚点窗口期实测(06:50 前后)、bind 解绑补测(测试账号)、返校日实跑(boot 拍豁免链)。
3. **审计附录 A 小瑕疵批**(docs/tech/guigui-backend-audit-2026-09-11.md 附录):wifictl SSID XML 转义、临时文件崩溃残留、vault 持久化注释澄清——小批纯执行,一并 commit。

## P2 · 工程化(agent 可执行)

1. **门禁自动化**(2026-09-10 已确认缺口):pre-commit 钩子跑快速档 pytest(全量 48min 太重,选集合或 -k 冒烟)+ commit 信息规范检查;方案先落 docs/plans/ 再动手。
2. **文档存量对账**:按 document-management.md §6 逐条标「已闭环」,存疑呈报。
3. **1.6.0 文档收口核对**:契约 §5 所列余项与 P0 拍板结果对齐后,统一收口一次(版本/变更记录/矩阵同步)。

## 明确不做(防跑偏)

- 不做托盘/常驻、不做通用化跨校、不做 AI 写作类功能(SPEC §4 决策基线);
- 不动 legacy-v1/;不在无拍板情况下实施 ADR-0005/0006;
- 调度机制不换(审计 §5 论证),新想法先过 ADR。
