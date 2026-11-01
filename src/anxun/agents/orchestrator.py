# -*- coding: utf-8 -*-
"""
编排器
======

三个 Agent 之间**只传 JSON 消息**，不共享内存对象。好处很实在：

- 任何一个 Agent 都可以单独拿出来测（拿一份假消息喂进去就行）
- 换成扣子/Coze 时，把消息换成 HTTP 请求体即可，业务代码零改动
- 全过程留 trace，界面上能看见「谁在什么时候做了什么」

调用顺序固定：② 感知 → ③ 研判 → ④ 工单。
中间任何一步没有产出，链路就停在那里并给出原因，不会假装有结果。
"""

from __future__ import annotations

from datetime import datetime

from .perception import PerceptionAgent
from .risk import RiskAgent
from .scenarios import SCENE_KEYS, get_scene
from .workorder import WorkOrderAgent


class Trace:
    """全过程留痕。答辩被问「你这链路怎么跑起来的」，直接翻这个。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, agent: str, action: str, **payload) -> None:
        self.steps.append({
            "seq": len(self.steps) + 1,
            "agent": agent,
            "action": action,
            "payload": payload,
        })


class Orchestrator:
    def __init__(self) -> None:
        self.perception = PerceptionAgent()
        self.risk = RiskAgent()
        self.workorder = WorkOrderAgent()

    def run(self, scene_key: str, now: datetime | None = None) -> dict:
        scene = get_scene(scene_key)
        frames = scene["frames"]
        region = scene["region"]
        trace = Trace()

        # --- ② 视觉感知 ---
        perception = self.perception.run(frames, trace=trace)

        # --- ③ 隐患研判 ---
        affected: dict[str, int] = {}
        for v in perception["violations"]:
            affected[v["equip"]] = affected.get(v["equip"], 0) + 1

        risk = self.risk.run(perception, region, frames[-1].ts, trace=trace)
        for e in risk["events"]:
            e["affected"] = affected.get(e["equip"], 1)
            e["violation_30d"] = region.violation_30d

        # --- ④ 工单闭环 ---
        workorders = self.workorder.run(risk, now=now, trace=trace)

        return {
            "scene": {
                "key": scene["key"],
                "title": scene["title"],
                "camera": scene["camera"],
                "resolution": f"{scene['resolution'][0]}x{scene['resolution'][1]}",
                "region": region.name,
                "region_id": region.region_id,
                "scene_type": region.scene,
                "owner": region.owner,
                "violation_30d": region.violation_30d,
                "frames": len(frames),
                "frame_ts": [f.ts.isoformat(timespec="seconds") for f in frames],
                "subject": scene["subject"],
            },
            "perception": perception,
            "risk": risk,
            "workorders": workorders,
            "trace": trace.steps,
            "summary": self._summary(perception, risk, workorders),
        }

    def run_all(self) -> dict:
        runs = {k: self.run(k) for k in SCENE_KEYS}
        return {
            "mode": "all",
            "scenes": runs,
            "comparison": self._comparison(runs),
        }

    # ---------------- 汇总 ----------------

    @staticmethod
    def _summary(perception: dict, risk: dict, workorders: dict) -> dict:
        events = risk.get("events", [])
        tickets = workorders.get("tickets", [])
        top = max(events, key=lambda e: e["R"]) if events else None
        return {
            "verdicts": perception["counts"]["项数"],
            "violations": len(perception["violations"]),
            "events": len(events),
            "tickets": len(tickets),
            "offline": perception["counts"].get("待复核", 0) + perception["counts"].get("无法判定", 0),
            "top_grade": top["grade"] if top else "无",
            "top_risk": top["R"] if top else 0,
            "headline": (
                f"{top['person']} {top['equip_cn']} · R={top['R']} {top['grade']} · "
                f"{top['due_text']}整改 · 责任人 {top['owner']}"
                if top else "本机位无定论违规，转人工复核队列"
            ),
            "tickets_brief": [
                {"id": t["ticket_id"], "grade": t["grade"], "status": t["status"]}
                for t in tickets
            ],
        }

    @staticmethod
    def _comparison(runs: dict) -> list[dict]:
        """同一违规类型在不同区域的结果对比——PPT 里最该放的那张表。"""
        rows = []
        for key in SCENE_KEYS:
            r = runs[key]
            for e in r["risk"]["events"]:
                rows.append({
                    "scene": key,
                    "region": e["region"],
                    "scene_type": e["scene"],
                    "equip": e["equip"],
                    "equip_cn": e["equip_cn"],
                    "violation_30d": r["scene"]["violation_30d"],
                    "L": e["L"], "S": e["S"], "R": e["R"],
                    "grade": e["grade"],
                    "due": e["due_text"],
                    "ticket": f"TK-{e['event_id'].split('-', 1)[1]}",
                })
        rows.sort(key=lambda x: (x["equip"], -x["R"]))
        return rows
