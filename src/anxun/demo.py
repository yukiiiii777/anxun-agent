# -*- coding: utf-8 -*-
"""
安巡 Agent · 端到端演示
=======================

不依赖任何模型，用模拟检测框跑完整链路：
    检测框 -> PPE 判定 -> 时序聚合 -> 风险矩阵定级 -> 工单生成 -> 报告

运行：
    python demo.py

产出：
    控制台报告 + result.json + report.html（可直接截图进 PPT）
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from rules_engine import (
    Box, Region, judge_frame, aggregate_temporal,
    build_event, make_ticket, likelihood, severity, grade_of,
    CONF_FINAL, CONF_REVIEW,
)

HERE = Path(__file__).parent
T0 = datetime(2026, 11, 3, 9, 20, 0)

W, H = 1920, 1080   # 模拟图像分辨率


# ============================================================
# 一、构造检测结果
# ============================================================

def make_boxes() -> list[Box]:
    """
    四个人员 + 部分装备框。

    人1：戴帽且高置信度       -> 已佩戴
    人2：有帽但置信度中等     -> 待复核（演示复核通道）
    人3：无帽                 -> 未佩戴（本演示的违规主体）
    人4：目标过小（远处）     -> 无法判定（演示失效保护）
    """
    return [
        # --- 人员 ---
        Box("person", 0.94, 300, 300, 540, 920),      # 人1
        Box("person", 0.88, 700, 320, 940, 940),      # 人2
        Box("person", 0.91, 1100, 310, 1340, 930),    # 人3（违规主体）
        Box("person", 0.71, 1650, 700, 1710, 800),    # 人4（远处小目标）

        # --- 安全帽 ---
        Box("helmet", 0.93, 320, 290, 520, 410),      # 人1 的帽
        Box("helmet", 0.52, 720, 310, 920, 430),      # 人2 的帽（低置信）

        # --- 反光背心 ---
        Box("vest", 0.89, 310, 470, 530, 760),        # 人1 背心
        Box("vest", 0.87, 710, 490, 930, 780),        # 人2 背心
        Box("vest", 0.86, 1110, 480, 1330, 770),      # 人3 背心
    ]


# ============================================================
# 二、场景定义
# ============================================================

REGIONS = {
    "A": Region("A-03", "3 号车间东侧通道", "普通", "李建国", violation_30d=4),
    "B": Region("B-01", "2 号车间高处作业平台", "高处", "王志强", violation_30d=7),
    "C": Region("C-07", "原料库装卸区", "车辆", "赵明", violation_30d=1),
}


# ============================================================
# 三、报告渲染
# ============================================================

STATUS_COLOR = {
    "已佩戴": ("#3B6D11", "#EAF3DE"),
    "未佩戴": ("#A32D2D", "#FCEBEB"),
    "待复核": ("#854F0B", "#FAEEDA"),
    "无法判定": ("#5F5E5A", "#F1EFE8"),
    "丢弃": ("#7A7A7A", "#F1EFE8"),
}


def scene_svg(boxes: list[Box], verdicts, title: str) -> str:
    """把检测框画成示意图，作为报告里的「画面」。"""
    sx, sy = 640 / W, 360 / H
    viol_person = {v.person_idx for v in verdicts if v.equip == "helmet" and v.is_violation}

    persons = [b for b in boxes if b.label == "person"]
    parts = [
        f'<rect x="0" y="0" width="640" height="360" fill="#1F2421"/>',
        f'<rect x="0" y="300" width="640" height="60" fill="#2A302B"/>',
        f'<text x="12" y="20" fill="#9FBFA8" font-size="11" font-family="monospace">{title}</text>',
    ]

    for i, p in enumerate(persons):
        x1, y1 = p.x1 * sx, p.y1 * sy
        w, h = p.w * sx, p.h * sy
        bad = i in viol_person
        color = "#E24B4A" if bad else "#97C459"
        parts.append(
            f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="1.6"/>'
        )
        label = f"P{i + 1} {p.conf:.2f}"
        parts.append(
            f'<rect x="{x1:.1f}" y="{y1 - 15:.1f}" width="{len(label) * 6.4 + 8:.1f}" '
            f'height="14" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{x1 + 4:.1f}" y="{y1 - 4:.1f}" fill="#fff" font-size="10" '
            f'font-family="monospace">{label}</text>'
        )
        if bad:
            parts.append(
                f'<text x="{x1 + w / 2:.1f}" y="{y1 + h / 2:.1f}" text-anchor="middle" '
                f'fill="#E24B4A" font-size="12" font-family="monospace">NO HELMET</text>'
            )

    for b in boxes:
        if b.label == "person":
            continue
        x1, y1 = b.x1 * sx, b.y1 * sy
        w, h = b.w * sx, b.h * sy
        parts.append(
            f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="none" stroke="#85B7EB" stroke-width="1" stroke-dasharray="3 2"/>'
        )

    return ('<svg viewBox="0 0 640 360" width="100%" xmlns="http://www.w3.org/2000/svg" '
            'style="border-radius:8px;display:block">' + "".join(parts) + "</svg>")


def verdict_rows(verdicts) -> str:
    rows = []
    for v in verdicts:
        fg, bg = STATUS_COLOR.get(v.status, ("#4A4A4A", "#F1EFE8"))
        equip = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜"}.get(v.equip, v.equip)
        rows.append(
            f"<tr><td>P{v.person_idx + 1}</td><td>{equip}</td>"
            f'<td><span style="background:{bg};color:{fg};padding:1px 7px;'
            f'border-radius:3px;font-size:12px">{v.status}</span></td>'
            f"<td>{v.conf:.2f}</td>"
            f'<td style="color:#7A7A7A;font-size:12px">{v.reason}</td></tr>'
        )
    return "".join(rows)


# ============================================================
# 四、主流程
# ============================================================

def main() -> None:
    boxes = make_boxes()
    line = "=" * 74

    print(line)
    print("安巡 Agent · 端到端演示")
    print(f"时间：{T0:%Y-%m-%d %H:%M}    图像：{W}x{H}    检测框：{len(boxes)} 个")
    print(line)

    # --- 1. 单帧判定 ---
    frame = judge_frame(boxes, equips=("helmet", "vest"))
    print("\n[1] 单帧 PPE 判定")
    print("-" * 74)
    print(f"{'人员':<6}{'装备':<10}{'结论':<8}{'置信':<7}依据")
    for v in frame:
        equip = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜"}[v.equip]
        print(f"P{v.person_idx + 1:<5}{equip:<10}{v.status:<8}{v.conf:<7.2f}{v.reason}")

    # --- 2. 时序聚合（模拟 4 帧一致）---
    frames = [frame, frame, frame, frame]
    final = aggregate_temporal(frames, need=3)
    print("\n[2] 时序聚合（连续 3 帧一致才定论）")
    print("-" * 74)
    n_final = sum(1 for v in final if v.status in ("已佩戴", "未佩戴"))
    n_review = sum(1 for v in final if v.status == "待复核")
    n_na = sum(1 for v in final if v.status == "无法判定")
    print(f"定论 {n_final} 项 | 待复核 {n_review} 项 | 无法判定 {n_na} 项")

    # --- 3. 提取违规 ---
    violations = [v for v in final if v.is_violation]
    print("\n[3] 违规清单")
    print("-" * 74)
    if not violations:
        print("无违规")
        return
    for v in violations:
        print(f"P{v.person_idx + 1} · {v.equip} · 置信度 {v.conf:.2f} · {v.reason}")

    # --- 4. 同一违规，不同场景定级 ---
    print("\n[4] 风险矩阵定级（同一违规，不同场景结果不同）")
    print("-" * 74)
    print(f"{'区域':<22}{'场景':<8}{'30天违规':<10}{'L':<4}{'S':<4}{'R':<5}{'等级':<6}时限")
    events = []
    for key in ("A", "B", "C"):
        r = REGIONS[key]
        equip = "helmet" if key != "C" else "vest"
        ev = build_event(r, equip, T0, violations[0].conf, "frame_0003.jpg")
        events.append(ev)
        d = ev.due_at - ev.ts
        due_txt = f"{d.total_seconds() / 3600:.0f} 小时内" if d.days == 0 else f"{d.days} 天内"
        print(f"{r.name:<22}{r.scene:<8}{r.violation_30d:<10}{ev.L:<4}{ev.S:<4}"
              f"{ev.R:<5}{ev.grade:<6}{due_txt}")

    # --- 5. 工单 ---
    print("\n[5] 整改工单（以风险最高的一条为例）")
    print("-" * 74)
    top = max(events, key=lambda e: e.R)
    ticket = make_ticket(top, affected=1)
    for k, v in ticket.items():
        if v:
            print(f"  {k:<18}{v}")

    # --- 6. 落盘 ---
    result = {
        "meta": {"time": T0.isoformat(), "image": f"{W}x{H}", "boxes": len(boxes)},
        "verdicts": [v.__dict__ for v in final],
        "events": [{
            "event_id": e.event_id, "region": e.region.name, "scene": e.region.scene,
            "equip": e.equip, "L": e.L, "S": e.S, "R": e.R, "grade": e.grade,
            "action": e.action,
            "due_at": e.due_at.isoformat(timespec="minutes"),
        } for e in events],
        "tickets": [make_ticket(e, 1) for e in events],
    }
    (HERE / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>安巡 Agent · 巡检报告</title>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
margin:0;padding:32px;background:#FBFAF7;color:#1A1A1A;line-height:1.7}}
.w{{max-width:920px;margin:0 auto}}
h1{{font-size:22px;font-weight:600;margin:0 0 6px}}
.m{{color:#7A7A7A;font-size:13px;margin-bottom:24px}}
.g{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}
.c{{background:#fff;border:1px solid #E6E4DD;border-radius:8px;padding:14px 16px}}
.c .k{{font-size:12px;color:#7A7A7A}}
.c .v{{font-size:22px;font-weight:500;margin-top:2px}}
h2{{font-size:15px;font-weight:600;margin:28px 0 10px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff}}
th{{text-align:left;background:#F4F2EC;padding:9px 11px;font-weight:600;border-bottom:1px solid #E6E4DD}}
td{{padding:9px 11px;border-bottom:1px solid #E6E4DD;color:#4A4A4A}}
</style></head><body><div class="w">
<h1>安巡 Agent · 巡检报告</h1>
<div class="m">{T0:%Y-%m-%d %H:%M} · 3 号车间东侧通道 · 设备 ANX-CAM-03</div>

{scene_svg(boxes, final, "CAM-03 / 2026-11-03 09:20:00")}

<div class="g">
<div class="c"><div class="k">识别人员</div><div class="v">{sum(1 for b in boxes if b.label == 'person')}</div></div>
<div class="c"><div class="k">定论判定</div><div class="v">{n_final}</div></div>
<div class="c"><div class="k">违规项</div><div class="v" style="color:#A32D2D">{len(violations)}</div></div>
<div class="c"><div class="k">待复核</div><div class="v" style="color:#854F0B">{n_review}</div></div>
</div>

<h2>判定明细</h2>
<table><tr><th>人员</th><th>装备</th><th>结论</th><th>置信度</th><th>判定依据</th></tr>
{verdict_rows(final)}
</table>

<h2>风险定级</h2>
<table><tr><th>区域</th><th>场景</th><th>L</th><th>S</th><th>R</th><th>等级</th><th>整改时限</th></tr>
{''.join(f'<tr><td>{e.region.name}</td><td>{e.region.scene}</td><td>{e.L}</td><td>{e.S}</td>'
         f'<td><b>{e.R}</b></td><td>{e.grade}</td><td>{e.due_at:%m-%d %H:%M}</td></tr>' for e in events)}
</table>

<h2>整改工单</h2>
<table><tr><th>工单号</th><th>违规</th><th>整改要求</th><th>责任人</th><th>时限</th></tr>
<tr><td>{ticket['ticket_id']}</td><td>{ticket['violation']}</td>
<td>{ticket['requirement']}</td><td>{ticket['assignee']}</td><td>{ticket['due_at']}</td></tr>
</table>
</div></body></html>"""
    (HERE / "report.html").write_text(html, encoding="utf-8")

    print("\n" + line)
    print("已生成：result.json、report.html")
    print(line)


if __name__ == "__main__":
    main()
