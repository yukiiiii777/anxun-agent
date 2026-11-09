# -*- coding: utf-8 -*-
"""
③ 隐患研判 Agent
================

职责：把「违规」变成「带等级、带时限、带法规依据的隐患事件」。

关键设计：**定级永远不交给大模型做乘法。**

v1.4 起等级不再走 R = L × S 矩阵，改成按「本次全场合计确认未佩戴人数」分档
（≥3 人 A / 1–2 人 B / 仅待复核 C），与 `rules_engine.urgency_of()` 同一套口径。
本 Agent 只负责：

1. 把人数 → 等级 → 处置时限写成可读的句子（答辩现场被追问「为什么是 A」时的答案）。
2. 挂上法规依据；查不到就明说查不到，不补。
3. 人数按**全场合计**，不按单类装备拆开——否则同一场景会出现安全帽 B、背心 A。
"""

from __future__ import annotations

from datetime import datetime

from rules_engine import Event, Region, build_event

from . import kb

EQUIP_CN = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜", "aisle": "消防通道"}

GRADE_NAME = {"A": "立即处置", "B": "当日处置", "C": "限期核实"}


class RiskAgent:
    name = "③ 隐患研判"
    role = "安全隐患定级员"

    def run(self, perception: dict, region: Region, ts: datetime, trace=None) -> dict:
        violations = perception.get("violations", [])
        events: list[dict] = []
        # v1.4：人数取本次全部确认未佩戴，两张单共用同一个等级
        confirmed_total = len(violations)

        for v in violations:
            ev = build_event(region, v["equip"], ts, v["conf"], self._evidence(v),
                             event_id=self._event_id(region, ts, v["equip"], v.get("person", "")),
                             scale=1, confirmed_total=confirmed_total)
            events.append(self._event_dict(ev, v))

        if trace:
            trace.record(
                self.name, "处置等级定级",
                rule="按本次全场合计确认未佩戴人数分档：≥3 人 A（2 小时内）｜"
                     "1–2 人 B（24 小时内）｜仅待复核 C（7 天内）；不看作业类型与区域历史",
                events=[{"event": e["event_id"], "grade": e["grade"],
                         "confirmed": e["confirmed_total"]} for e in events],
            )

        return {
            "agent": self.name,
            "role": self.role,
            "region": {
                "region_id": region.region_id,
                "name": region.name,
                "scene": region.scene,
                "owner": region.owner,
                "violation_30d": region.violation_30d,
            },
            "events": events,
            "grading_basis": kb.grading_basis(),
            "handoff_note": self._handoff(events),
        }

    # ---------------- 内部 ----------------

    @staticmethod
    def _event_id(region: Region, ts: datetime, equip: str, person: str = "") -> str:
        """事件号带装备代码 + 人员号。

        只带装备代码时，同一帧同一区域的两个人都没戴安全帽会算出同一个
        event_id，工单号（由 event_id 派生）也跟着撞——演示页上会出现两张
        编号相同的工单，一眼就是假的。
        """
        code = {"helmet": "H", "vest": "V", "goggles": "G", "aisle": "A"}.get(
            equip, equip[:1].upper())
        tail = f"-{person}" if person else ""
        return f"EV-{ts:%Y%m%d%H%M%S}-{region.region_id}-{code}{tail}"

    @staticmethod
    def _evidence(v: dict) -> str:
        return f"{v['person']} · {v['equip_cn']} · 置信度 {v['conf']:.2f}"

    def _event_dict(self, ev: Event, v: dict) -> dict:
        legal = kb.lookup(ev.equip, ev.region.scene)
        n = ev.confirmed_total or ev.scale
        grade_name = GRADE_NAME.get(ev.grade, ev.grade)

        due_hours = (ev.due_at - ev.ts).total_seconds() / 3600
        return {
            "event_id": ev.event_id,
            "region": ev.region.name,
            "region_id": ev.region.region_id,
            "scene": ev.region.scene,
            "owner": ev.region.owner,
            "equip": ev.equip,
            "equip_cn": EQUIP_CN.get(ev.equip, ev.equip),
            "person": v["person"],
            "conf": round(ev.conf, 3),
            "evidence": ev.evidence,
            "ts": ev.ts.isoformat(timespec="minutes"),
            # v1.4：L/S/R 不再参与定级，字段位保留给旧调用方，恒为 0
            "L": 0,
            "S": 0,
            "R": 0,
            "scale": ev.scale,                 # 本类装备确认人数
            "confirmed_total": n,              # 全场合计确认人数（定级依据）
            "grade": ev.grade,
            "grade_name": grade_name,
            "band": f"{ev.grade} · {grade_name}",
            "action": ev.action,
            "due_at": ev.due_at.isoformat(timespec="minutes"),
            "due_text": self._due_text(due_hours),
            "explain": {
                "people": f"本次全场合计确认未佩戴 {n} 人 → {ev.grade} 级（{grade_name}）",
                "grade": f"按处置时限分档：{n} 人 → {ev.grade} 级，{self._due_text(due_hours)}整改 → {ev.action}",
                "note": "等级不看作业类型，也不看区域历史违规次数",
            },
            "legal": legal,
        }

    @staticmethod
    def _due_text(hours: float) -> str:
        if hours < 1:
            return f"{hours * 60:.0f} 分钟内"
        if hours < 24:
            return f"{hours:.0f} 小时内"
        return f"{hours / 24:.0f} 天内"

    @staticmethod
    def _handoff(events: list[dict]) -> str:
        if not events:
            return "无定论违规，本环节不产生隐患事件，流程终止于人工复核。"
        rank = {"A": 3, "B": 2, "C": 1}
        top = max(events, key=lambda e: rank.get(e["grade"], 0))
        return (f"定级 {len(events)} 条，最高 {top['grade']} 级（全场合计 {top['confirmed_total']} 人，"
                f"{top['equip_cn']}·{top['scene']}），移交 ④ 工单闭环。")
