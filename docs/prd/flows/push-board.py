#!/usr/bin/env python3
"""白板推送配方(文档,不自动执行)。

本文件只记录经过实锤的推送流程;安全扫描器禁止在本仓库用 subprocess 封装
CLI 调用,故不内嵌自动化。要推白板时,在 docs/prd/flows/ 下按下面三步手动执行。

推送三步(2026-09-10 定稿,两次实测通过):
  1. 生成 payload(绝不用板上导出的 raw 回推):
     npx -y @larksuite/whiteboard-cli -i guigui-user-flow.dsl.json -t openapi -F json -o p.json
  2. 四层显式 z(用 python 一行式或临时脚本改 p.json,按 area 分层):
     泳道/根框(area>100000) z=0..   连线 z=100..   节点框 z=200..   文字 z=300..
  3. 推送并复核:
     lark-cli whiteboard +update --whiteboard-token <TOKEN> --input_format raw --source @p.json --overwrite
     lark-cli whiteboard +export  --whiteboard-token <TOKEN> --output-type raw --output back.json --overwrite
     复核 back.json:层序 框<线<节点<文字 严格成立,且无文字 z 低于其所在节点框。

为什么必须显式 z(事故链):
  覆写(overwrite)时服务器的自动铸层只在干净板首推时正确;同板二次覆写后
  文字会沉到形状底下(框在字没),若把连线全垫底又会被泳道填充框盖住(线被盖)。
  服务器完全认账 payload 里的显式 z_index——四层分配是唯一稳定解。

当前板 token 见 lark-cli 记忆条目;恢复点 = guigui-user-flow.board-raw.json
(即带四层 z 的最新 payload,可整文件直接作为 --source 重推)。
"""

if __name__ == "__main__":
    print(__doc__)
