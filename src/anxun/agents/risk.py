# -*- coding: utf-8 -*-
"""
③ 隐患研判 Agent
================

职责：把「违规」变成「带等级、带时限、带法规依据的隐患事件」。

关键设计：**定级永远不交给大模型做乘法。**
R = L × S 全部走 `rules_engine.build_event()`，本 Agent 只负责：

1. 把 L / S 的取值理由写成可读的句子（答辩现场被追问「为什么是 16」时的答案）。
2. 挂上法规依据；查不到就明说查不到，不补。
3. 同一违规在不同场景下必须算出不同等级——这是整个作品最想被看见的一点。
"""

from __future__ import annotations

from datetime import datetime

from rules_engine import Event, Region, build_event

from . import kb

EQUIP_CN = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜", "aisle": "消防通道"}

BANDS = (
    (12, "红色", "重大风险"),
    (8, "橙色", "较大风险"),
    (4, "黄色", "一般风险"),
    (0, "蓝色", "低风险"),
)


class RiskAgent:
    name = "③ 隐患研判"
    role = "安全隐患定级员"

    def run(self, perception: dict, region: Region, ts: datetime, trace=None) -> dict:
        violations = perception.get("violations", [])
        events: list[dict] = []

        for v in violations:
            ev = build_event(region, v["equip"], ts, v["conf"], self._evidence(v),
                             event_id=self._event_id(region, ts, v["equip"]))
            events.append(self._event_dict(ev, v))

        if trace:
            trace.record(
                self.name, "风险矩阵定级",
                rule="R = L（30 天违规频次）× S（违规类型 × 作业场景）",
                events=[{"event": e["event_id"], "R": e["R"], "grade": e["grade"]} for e in events],
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
    def _event_id(region: Region, ts: datetime, equip: str) -> str:
        """事件号带上装备代码，避免同一帧同一区域多条违规撞号。"""
        code = {"helmet": "H", "vest": "V", "goggles": "G", "aisle": "A"}.get(
            equip, equip[:1].upper())
        return f"EV-{ts:%Y%m%d%H%M%S}-{region.region_id}-{code}"

    @staticmethod
    def _evidence(v: dict) -> str:
        return f"{v['person']} · {v['equip_cn']} · 置信度 {v['conf']:.2f}"

    def _event_dict(self, ev: Event, v: dict) -> dict:
        band = next((b for low, b, _ in BANDS if ev.R >= low), "蓝色")
        band_name = next((n for low, b, n in BANDS if ev.R >= low), "低风险")
        legal = kb.lookup(ev.equip, ev.region.scene)

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
            "L": ev.L,
            "S": ev.S,
            "R": ev.R,
            "grade": ev.grade,
            "band": f"{band} · {band_name}",
            "action": ev.action,
            "due_at": ev.due_at.isoformat(timespec="minutes"),
            "due_text": self._due_text(due_hours),
            "explain": {
                "L": f"该区域近 30 天同类违规 {ev.region.violation_30d} 次 → L={ev.L}",
                "S": f"{EQUIP_CN.get(ev.equip, ev.equip)} × {ev.region.scene}作业场景 → S={ev.S}",
                "R": f"R = L({ev.L}) × S({ev.S}) = {ev.R}",
                "grade": f"R={ev.R} 落在「{band}」区间（{band_name}）→ {ev.action}",
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
        top = max(events, key=lambda e: e["R"])
        return (f"定级 {len(events)} 条，最高 {top['grade']}（R={top['R']}，{top['equip_cn']}·"
                f"{top['scene']}），移交 ④ 工单闭环。")
