# -*- coding: utf-8 -*-
"""
安巡 Agent · 本地多智能体入口
=============================

在 `src/anxun` 目录下运行：

    python run_agents.py                    # A/B/C 三个场景全跑
    python run_agents.py --scene B          # 只看高处作业场景
    python run_agents.py --json out.json    # 顺带落结构化结果
    python run_agents.py --serve            # 起本地网页（默认 8611 端口）

纯标准库，不装任何依赖。规则引擎与演示报告仍由 `rules_engine.py` / `demo.py` 提供，
本文件只是把它们编排成三个可对话的 Agent。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
