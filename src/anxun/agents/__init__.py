# -*- coding: utf-8 -*-
"""安巡 Agent · 本地多智能体实现（② 感知 → ③ 研判 → ④ 工单）。

模块边界：

    perception.py   ② 视觉感知 Agent   —— 四态判定 + 遮挡保护 + 时序聚合
    risk.py         ③ 隐患研判 Agent   —— R=L×S 定级 + 法规依据
    workorder.py    ④ 工单闭环 Agent   —— SLA + 验收 + 逾期升级
    orchestrator.py 编排与留痕
    scenarios.py    演示数据（写死，不随机）
    kb.py           法规知识库（只收核对过的条文）
    cli.py          命令行入口
    server.py       本地网页入口

运行：在 `src/anxun` 目录下

    python run_agents.py                 # 跑 A/B/C 三个场景
    python run_agents.py --scene B       # 只跑高处作业场景
    python run_agents.py --json out.json # 同时落一份结构化结果
    python run_agents.py --serve         # 起本地网页，浏览器里看整条链路
"""

__version__ = "1.0.0"
__all__ = ["perception", "risk", "workorder", "orchestrator", "scenarios", "kb"]
