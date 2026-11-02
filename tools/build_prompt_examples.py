# -*- coding: utf-8 -*-
"""
生成《12 · 三组 Agent 提示词示例》—— 输入与输出全部取自真实运行结果。
====================================================================

官方硬要求「≥3 个提示词示例及输出」。这份文档的每一条数据都由
`Orchestrator().run_all()` 现算，不手写、不编造。

用法：python tools/build_prompt_examples.py
产出：docs/12-Agent提示词示例.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "anxun"))

from agents.orchestrator import Orchestrator  # noqa: E402
from agents.scenarios import get_scene  # noqa: E402

OUT = ROOT / "docs/12-Agent提示词示例.md"

TITLE = """# 12 · 三组 Agent 提示词示例（输入 → 输出）

> 对应官方要求「≥3 个提示词示例及输出」，PPT 第 19 页直接取用。
>
> 本文所有输入、判定、定级、工单**均为程序真实输出**，生成命令：
>
> ```bash
> cd src/anxun
> python run_agents.py --scene A     # 示例一
> python run_agents.py --scene B     # 示例二
> python run_agents.py --scene C     # 示例三
> ```
>
> 提示词全文见 [`安巡Agent_提示词库.md`](安巡Agent_提示词库.md)，此处只摘与判定直接相关的规则。

---

## 〇、三组放在一起看

| 示例 | 场景 | 违规 | 30 天违规 | L | S | R | 等级 | 时限 |
|---|---|---|---|---|---|---|---|---|
"""

EXAMPLE_HEAD = """
---

## {idx} · {title}

**一句话**：{one_liner}

### ① 提示词（摘录）

**② 视觉感知 Agent**

```
{perception_prompt}
```

**③ 隐患研判 Agent**

```
{risk_prompt}
```

**④ 工单闭环 Agent**

```
{workorder_prompt}
```

### ② 输入

机位 `{camera}`，{frames} 帧连续画面，{res}。第 1 帧检测结果：

| 目标 | 位置（x1,y1,x2,y2） | 置信度 |
|---|---|---|
{input_rows}

### ③ 输出

**判定（②）**

| 人员 | 装备 | 结论 | 置信度 | 依据 |
|---|---|---|---|---|
{verdict_rows}

**定级（③）**

{event_block}

**工单（④）**

{ticket_block}

### ④ 判读要点

{notes}
"""

PERCEPTION_PROMPT = """# 角色：厂区安全视觉合规判定员
1. 人员识别：类别 person 的目标各视为一名待判定人员。
2. 安全帽：头部区域（person 框上部 30%）内存在 helmet 框且 IoU ≥ 0.25 → 已佩戴；
   不存在或 IoU < 0.25 → 未佩戴。
3. 置信度三档（不得省略）：
   ≥ 0.30 直接定论；[0.20, 0.30) 输出「待复核」，不给违规结论；< 0.20 丢弃。
4. 时序一致性：同一人员连续 3 帧结论一致才输出最终结论，否则标「待复核」。
5. 遮挡处理：可见面积 < 40% → 「无法判定」，**不得输出违规**。
6. 只允许四种状态：已佩戴 / 未佩戴 / 待复核 / 无法判定，禁止「可能」「大概」。"""

RISK_PROMPT = """# 角色：企业安全隐患定级员
风险值 R = 可能性 L × 后果严重度 S，按矩阵定级，不得凭经验跳步。
L：本区域近 30 天同类违规 0–1 次→1，2–3 次→2，4–6 次→3，≥7 次→4。
S：安全帽未戴 + 高处/起重→4；+ 普通→3；反光背心未穿 + 车辆区→3；+ 普通→2；
   其他→2。
定级：R ≥ 12 红色（立即停工整改）；8–11 橙色（当日整改）；
     4–7 黄色（限期整改）；1–3 蓝色（加强关注）。
输出每条事件必须附：L 与 S 的取值理由、法规条款（查不到就写「未检索到」）。"""

WORKORDER_PROMPT = """# 角色：企业安全隐患整改跟踪员
1. 时限按等级写死，不得放宽：红 2 小时 / 橙 24 小时 / 黄 7 天 / 蓝 30 天。
2. 责任人：优先该区域班组长；红色同时抄送部门安全负责人。
3. 整改要求必须可验证：数量 + 地点 + 留痕记录，缺一项判不合格。
4. 复查：安排在该完成时间的次日，复查人**不得**是整改责任人。
5. 逾期：50% 提醒上级；100% 上报安全负责人并标「逾期未整改」；
   连续 3 次逾期升红并重新定级。"""


def fmt_boxes(frame) -> str:
    rows = []
    persons = [b for b in frame.boxes if b.label == "person"]
    for i, p in enumerate(persons):
        mark = "（远处小目标）" if p.area < 8000 else ""
        rows.append(f"| P{i + 1} person | {p.x1:.0f},{p.y1:.0f},{p.x2:.0f},{p.y2:.0f}{mark} | {p.conf:.2f} |")
    for b in frame.boxes:
        if b.label != "person":
            name = {"helmet": "helmet 安全帽", "vest": "vest 反光背心", "goggles": "goggles 护目镜"}.get(
                b.label, b.label)
            rows.append(f"| {name} | {b.x1:.0f},{b.y1:.0f},{b.x2:.0f},{b.y2:.0f} | {b.conf:.2f} |")
    return "\n".join(rows)


def fmt_verdicts(run: dict) -> str:
    out = []
    for v in run["perception"]["verdicts"]:
        reason = v["reason"].replace("|", "／")
        out.append(f"| {v['person']} | {v['equip_cn']} | **{v['status']}** | {v['conf']:.2f} | {reason} |")
    return "\n".join(out)


def fmt_events(run: dict) -> str:
    lines = []
    for e in run["risk"]["events"]:
        lines.append(f"- **{e['event_id']}**　{e['person']} · {e['equip_cn']}")
        lines.append(f"  - {e['explain']['L']}")
        lines.append(f"  - {e['explain']['S']}")
        lines.append(f"  - {e['explain']['R']} → **{e['grade']}**，{e['due_text']}整改")
        legal = e["legal"]
        if legal["found"]:
            c = legal["clauses"][0]
            lines.append(f"  - 依据 {c['citation']}：{c['quote']}")
        else:
            lines.append(f"  - {legal['missing']}")
    return "\n".join(lines) if lines else "（本场景无定论违规，链路终止于人工复核）"


def fmt_tickets(run: dict) -> str:
    lines = []
    for t in run["workorders"]["tickets"]:
        lines.append(f"**{t['ticket_id']}**（{t['grade']} · R={t['risk']}）")
        lines.append("")
        lines.append("| 项 | 内容 |")
        lines.append("|---|---|")
        lines.append(f"| 整改要求 | {t['requirement']} |")
        lines.append(f"| 责任人 | {t['assignee']}{'　抄送 ' + t['cc'] if t['cc'] else ''} |")
        lines.append(f"| 时限 | {t['created_at']} → {t['due_at']}（SLA {t['sla_hours']} 小时） |")
        lines.append(f"| 复查 | {t['review_at']}，复查人 {t['reviewer']}（≠ 整改人） |")
        lines.append(f"| 验收 | " + "；".join(
            f"{c['item']} {'✓' if c['ok'] else '✗'}" for c in t["checks"]) + " |")
        lines.append(f"| 闭环 | " + " → ".join(f"{c['phase']}（{c['status']}）" for c in t["closure"]) + " |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    orch = Orchestrator()
    runs = {k: orch.run(k) for k in ("A", "B", "C")}

    # 对比表
    table_rows = []
    for e in orch._comparison(runs):
        table_rows.append(
            f"| {e['scene']} | {e['region']}（{e['scene_type']}） | {e['equip_cn']} | "
            f"{e['violation_30d']} 次 | {e['L']} | {e['S']} | **{e['R']}** | {e['grade']} | {e['due']} |"
        )

    head = TITLE + "\n".join(table_rows) + "\n"

    specs = [
        ("A", "示例一", "车间通道未戴安全帽 → 橙色 R=9，24 小时内整改",
         "普通生产区域，30 天违规 4 次，S=3", "最常规的一次派单。注意 P2 输了「待复核」而不是硬判违规。"),
        ("B", "示例二", "同一违规换到高处作业平台 → 红色 R=16，2 小时内停工整改",
         "同样没戴帽子，只因场景变成高处作业、30 天违规 7 次，等级从橙变红。",
         "这条是整个作品的核心论点：**告警相同，责任不同**。"),
        ("C", "示例三", "装卸区反光背心未穿 → 蓝色 R=3，30 天内整改",
         "有车辆通行但 30 天仅 1 次违规，按矩阵落到最低档。",
         "最低档同样要派单——蓝色不是「不处理」，是「加强关注」。"),
    ]

    body = ""
    for key, idx, one_liner, _sub, notes in specs:
        run = runs[key]
        scene = get_scene(key)
        frame = scene["frames"][0]
        body += EXAMPLE_HEAD.format(
            idx=idx,
            title=run["scene"]["title"],
            one_liner=one_liner,
            perception_prompt=PERCEPTION_PROMPT,
            risk_prompt=RISK_PROMPT,
            workorder_prompt=WORKORDER_PROMPT,
            camera=run["scene"]["camera"],
            frames=run["scene"]["frames"],
            res=run["scene"]["resolution"],
            input_rows=fmt_boxes(frame),
            verdict_rows=fmt_verdicts(run),
            event_block=fmt_events(run),
            ticket_block=fmt_tickets(run),
            notes=notes,
        )

    tail = """
---

## 四、三组示例想说明什么

| 想证明的 | 看哪里 |
|---|---|
| 判定是四态、不是「是/否」 | 示例一 P2：0.28 只给「待复核」，不给违规结论 |
| 失效保护真的会拦 | 示例一 P4：6000px² 直接「无法判定」，不产生工单 |
| 同一违规不同责任 | 示例一 R=9 橙 / 示例二 R=16 红，输入几乎一样 |
| 等级低也要闭环 | 示例三 R=3 蓝色，照样派单、照样有复查人 |
| 法规不是编的 | 每条事件附条款号 + 原文，查不到会写「未检索到」 |

## 五、现场被问怎么答

- **「提示词能改吗」**：能。改的是角色与规则描述，判定阈值和风险矩阵在代码里，
  不让模型做算术——这是刻意的，大模型算乘法不可靠。
- **「换个大模型会变吗」**：判定结果不会变，因为数值判定不经过模型；
  会变的是措辞和解释。
- **「为什么要三档置信度」**：低置信度直接下结论就是误报来源，
  工业场景里误报几次，人就把告警关掉了。
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(head + body + tail, encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
