# -*- coding: utf-8 -*-
"""命令行入口：把三个 Agent 跑一遍，终端里直接看完整链路。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .orchestrator import Orchestrator
from .scenarios import SCENE_KEYS

LINE = "=" * 78
DASH = "-" * 78
EQUIP_CN = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜"}
GRADE_MARK = {"红色": "🔴", "橙色": "🟠", "黄色": "🟡", "蓝色": "🔵"}


def _w(s: str) -> int:
    """显示宽度：中文按 2 列算。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in str(s))


def _pad(s, width: int) -> str:
    s = str(s)
    return s + " " * max(0, width - _w(s))


def _hr(title: str = "") -> None:
    if title:
        print(f"\n{title}")
        print(DASH)
    else:
        print(DASH)


def _table(headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
    print("".join(_pad(h, wd) for h, wd in zip(headers, widths)))
    print("".join("-" * wd for wd in widths))
    for r in rows:
        print("".join(_pad(c, wd) for c, wd in zip(r, widths)))


def print_run(run: dict) -> None:
    sc = run["scene"]
    p, rk, wo = run["perception"], run["risk"], run["workorders"]

    print(LINE)
    print(f"安巡 Agent · {sc['title']}")
    print(f"机位 {sc['camera']}  {sc['resolution']}  {sc['frames']} 帧  "
          f"{sc['frame_ts'][0]} → {sc['frame_ts'][-1][11:]}")
    print(f"区域 {sc['region']}（{sc['region_id']}） · 场景 {sc['scene_type']} · "
          f"负责人 {sc['owner']} · 近 30 天违规 {sc['violation_30d']} 次")
    print(LINE)

    # ---------- ② ----------
    _hr("[② 视觉感知] 单帧判定 → 时序聚合 → 四态输出")
    rows = []
    for v in p["verdicts"]:
        rows.append([
            v["person"], v["equip_cn"], v["status"], f"{v['conf']:.2f}",
            ("⚠ " if v["is_violation"] else "") + v["reason"],
        ])
    _table(["人员", "装备", "结论", "置信", "判定依据"], rows, [6, 10, 10, 6, 40])

    c = p["counts"]
    print(f"\n汇总：定论 {c['定论']} 项（其中违规 {len(p['violations'])}） | "
          f"待复核 {c['待复核']} | 无法判定 {c['无法判定']} | 共 {c['项数']} 项")
    print(f"交接 → {p['handoff_note']}")

    # ---------- ③ ----------
    _hr("[③ 隐患研判] R = L × S，同一违规换场景换等级")
    if not rk["events"]:
        print("无定论违规，链路在此终止（不向工单环节派发）。")
        return

    rows = []
    for e in rk["events"]:
        rows.append([
            e["person"] + " " + e["equip_cn"], e["scene"],
            str(e["L"]), str(e["S"]), str(e["R"]),
            GRADE_MARK.get(e["grade"], "") + e["grade"], e["due_text"],
        ])
    _table(["违规", "场景", "L", "S", "R", "等级", "时限"], rows, [16, 8, 4, 4, 4, 8, 10])

    for e in rk["events"]:
        print(f"\n  {e['event_id']}")
        print(f"    {e['explain']['L']}")
        print(f"    {e['explain']['S']}")
        print(f"    {e['explain']['R']} → {e['grade']}（{e['action']}）")
        legal = e["legal"]
        if legal["found"]:
            for cl in legal["clauses"][:2]:
                print(f"    依据 {cl['citation']} · {cl['title']}")
                print(f"         「{cl['quote'][:40]}…」")
        else:
            print(f"    依据 {legal['missing']}")
    print(f"\n交接 → {rk['handoff_note']}")

    # ---------- ④ ----------
    _hr("[④ 工单闭环] 派单 → 整改 → 复查 → 归档")
    for t in wo["tickets"]:
        print(f"\n  工单 {t['ticket_id']}   {GRADE_MARK.get(t['grade'], '')}{t['grade']}"
              f"（R={t['risk']}）   {t['status']}")
        print(f"    整改要求  {t['requirement']}")
        print(f"    责任人    {t['assignee']}" + (f"    抄送 {t['cc']}" if t["cc"] else ""))
        print(f"    时限      {t['created_at']} → {t['due_at']}（{t['sla_hours']} 小时）"
              f"   {t['remain_text']}")
        print(f"    复查      {t['review_at']}  复查人 {t['reviewer']}（≠ 整改人）")
        print(f"    升级      50% {t['escalation']['at_50pct']} → {t['escalation']['to_50pct']}；"
              f"100% {t['escalation']['at_100pct']} → {t['escalation']['to_100pct']}")
        print(f"    验收      " + " | ".join(
            f"{c['item']} {'✓' if c['ok'] else '✗'}" for c in t["checks"]))
        print(f"    闭环      " + " → ".join(
            f"{c['phase']}({c['status']})" for c in t["closure"]))
    print(f"\n交接 → {wo['handoff_note']}")

    # ---------- summary ----------
    s = run["summary"]
    _hr("[链路留痕]")
    for st in run["trace"]:
        print(f"  {st['seq']:>2}. {st['agent']} · {st['action']}")
    print(f"\n结论：{s['headline']}")


def print_comparison(cmp: list[dict]) -> None:
    _hr("[横向对比] 同一条违规，不同场景不是同一个责任")
    rows = []
    for c in cmp:
        rows.append([
            c["scene"], c["region"], c["scene_type"], c["equip_cn"],
            str(c["violation_30d"]), str(c["L"]), str(c["S"]), str(c["R"]),
            GRADE_MARK.get(c["grade"], "") + c["grade"], c["due"],
        ])
    _table(["场景", "区域", "作业", "违规", "30天", "L", "S", "R", "等级", "时限"],
           rows, [6, 22, 8, 10, 6, 4, 4, 4, 8, 10])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安巡 Agent · 本地三智能体链路")
    parser.add_argument("--scene", default="all", help="A / B / C / all（默认 all）")
    parser.add_argument("--json", metavar="PATH", help="把结构化结果写到文件")
    parser.add_argument("--now", help="模拟当前时间，如 2026-11-03T10:35")
    parser.add_argument("--serve", action="store_true", help="启动本地网页")
    parser.add_argument("--port", type=int, default=8611, help="网页端口，默认 8611")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.serve:
        from .server import serve
        serve(port=args.port)
        return 0

    orch = Orchestrator()
    now = datetime.fromisoformat(args.now) if args.now else None

    if args.scene.lower() == "all":
        result = orch.run_all()
        for key in SCENE_KEYS:
            print_run(result["scenes"][key])
            print()
        print_comparison(result["comparison"])
    else:
        result = orch.run(args.scene, now=now)
        print_run(result)

    if args.json:
        path = Path(args.json)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写出 {path}")

    print("\n" + LINE)
    return 0
