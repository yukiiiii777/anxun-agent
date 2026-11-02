# -*- coding: utf-8 -*-
"""
把三智能体链路固化成**单文件静态页**，挂 GitHub Pages 用。
=========================================================

为什么要静态化
--------------
官方要求「可访问的 Agent 链接」，而本地服务是 127.0.0.1，评委打不开；
内网穿透要账号、断网就废、答辩当天掉线就是灾难。

静态页的取舍：**数据在构建时由真实代码跑出来，页面只负责展示**——
所以它不是截图，页面上的每个数字都能用 `python run_agents.py` 复现。

用法：
    python tools/build_demo_page.py
产出：
    docs/demo/index.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "anxun"))

from agents.orchestrator import Orchestrator  # noqa: E402

SRC = ROOT / "src/anxun/agents/web/index.html"
OUT = ROOT / "docs/demo/index.html"


def main() -> int:
    data = Orchestrator().run_all()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    html = SRC.read_text(encoding="utf-8")

    # 1) 把 fetch 换成内嵌数据
    old_boot = ('async function boot(){\n'
                '  const res = await fetch("/api/run?scene=all");\n'
                '  state.data = await res.json();')
    new_boot = ('const EMBEDDED = ' + payload + ';\n\n'
                'async function boot(){\n'
                '  state.data = EMBEDDED;')
    if old_boot not in html:
        sys.exit("没有找到 boot() 里的 fetch，源页面结构改过了？")
    html = html.replace(old_boot, new_boot)

    # 2) 页脚说明改成静态页口径
    html = html.replace(
        '页面数据来自 <span class="mono">GET /api/run?scene=all</span>，刷新即重算',
        '数据由本地 Agent 预生成，命令 <span class="mono">python run_agents.py</span> 可原样复现'
    )

    # 3) 右上角徽章说明改一下
    html = html.replace(
        '本地离线运行 · 规则引擎确定性输出',
        '静态演示 · 数据由规则引擎预生成'
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    size = OUT.stat().st_size
    print(f"已生成 {OUT.relative_to(ROOT)}  ({size / 1024:.0f} KB)")
    print(f"内嵌场景：{', '.join(data['scenes'])}")
    print(f"对比表行数：{len(data['comparison'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
