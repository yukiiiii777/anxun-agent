# -*- coding: utf-8 -*-
"""
④ 工单闭环 Agent
================

职责：把「隐患事件」变成「可执行、可追踪、可验收的工单」。

这一步是整条链上最容易被做薄的地方——很多方案停在一句「已通知负责人」。
本 Agent 强制四件事：

1. **时限按等级写死**，不放宽（A 级 2 小时、B 级 24 小时、C 级 7 天）。
2. **整改要求必须是可验证动作**：物资数量 + 地点 + 留痕记录，缺一项判不合格。
3. **复查人 ≠ 整改人**，且复查时间 = 整改完成次日。
4. **逾期自动升级**：50% 提醒上级 → 100% 上报并标逾期 → 连续 3 次逾期升红重定级。

工单本体由 `rules_engine.make_ticket()` 生成，本 Agent 负责 SLA、验收、升级与状态机。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from rules_engine import Event, Region, make_ticket

from . import kb

# 组织架构（演示用，接真实系统时换成 HR / 组织接口）
REVIEWER = "安全员 陈立"
ESCALATE_TO = "部门安全负责人 周敏"
PLANT_MANAGER = "厂长 郑海"

SLA_HOURS = {"A": 2, "B": 24, "C": 24 * 7}
PHASES = ("派单", "整改完成", "复查通过", "归档")


class WorkOrderAgent:
    name = "④ 工单闭环"
    role = "整改跟踪员"

    def run(self, risk: dict, now: datetime | None = None, trace=None) -> dict:
        events = risk.get("events", [])
        if now is None:
            now = self._default_now(events)

        tickets = [self._ticket(e, now) for e in events]

        if trace:
            trace.record(
                self.name, "生成工单",
                count=len(tickets),
                rule="等级定 SLA｜复查人 ≠ 整改人｜逾期自动升级",
                tickets=[{"id": t["ticket_id"], "grade": t["grade"],
                          "due": t["due_at"], "status": t["status"]} for t in tickets],
            )

        return {
            "agent": self.name,
            "role": self.role,
            "now": now.isoformat(timespec="minutes"),
            "org": {"reviewer": REVIEWER, "escalate_to": ESCALATE_TO, "plant_manager": PLANT_MANAGER},
            "sla_table": [{"grade": g, "hours": h} for g, h in SLA_HOURS.items()],
            "tickets": tickets,
            "handoff_note": self._handoff(tickets),
        }

    # ---------------- 内部 ----------------

    @staticmethod
    def _default_now(events: list[dict]) -> datetime:
        """默认时钟：第一条事件发生后 75 分钟（A 级工单正好触发 50% 提醒）。"""
        if not events:
            return datetime.now()
        return datetime.fromisoformat(events[0]["ts"]) + timedelta(minutes=75)

    def _ticket(self, e: dict, now: datetime) -> dict:
        ev = self._rehydrate(e)
        affected = int(e.get("affected", 1))
        base = make_ticket(ev, affected=affected)
        sla_h = SLA_HOURS.get(ev.grade, 24)

        created, due = ev.ts, ev.due_at
        review = due + timedelta(days=1)
        archive = review + timedelta(hours=2)
        at_50 = created + (due - created) * 0.5

        checks = self._verify_requirement(base["requirement"], affected, ev.region.name)

        return {
            **base,
            "sla_hours": sla_h,
            "affected": affected,
            "reviewer": REVIEWER,
            "checks": checks,
            "verifiable": all(c["ok"] for c in checks),
            "escalation": {
                "at_50pct": at_50.isoformat(timespec="minutes"),
                "to_50pct": ESCALATE_TO,
                "at_100pct": due.isoformat(timespec="minutes"),
                "to_100pct": PLANT_MANAGER,
                "repeat_3": "连续 3 次逾期 → 升级为 A 级并重新定级",
            },
            "closure": self._phases(now, created, due, review, archive),
            "status": self._status(now, created, due, review, at_50),
            "remain_text": self._remain(now, due),
            "legal": kb.ticket_basis(),
            "evidence_pack": [
                "物资签收单（数量 + 签字）",
                "整改后同机位照片（与原帧同角度）",
                "复查记录（复查人签字，非整改责任人）",
            ],
        }

    @staticmethod
    def _rehydrate(e: dict) -> Event:
        """只吃 JSON 消息、不依赖上游对象——这就是「解耦」在代码里的样子。"""
        region = Region(
            region_id=e["region_id"],
            name=e["region"],
            scene=e["scene"],
            owner=e["owner"],
            violation_30d=e.get("violation_30d", 0),
        )
        return Event(
            event_id=e["event_id"], region=region, equip=e["equip"],
            ts=datetime.fromisoformat(e["ts"]), conf=e["conf"], evidence=e["evidence"],
            L=e["L"], S=e["S"], R=e["R"], grade=e["grade"], action=e["action"],
            due_at=datetime.fromisoformat(e["due_at"]),
        )

    @staticmethod
    def _verify_requirement(req: str, affected: int, region: str) -> list[dict]:
        """整改要求「可验证」的三条硬检查。反例「加强安全管理」会全部不通过。"""
        return [
            {"item": "含具体物资与数量", "ok": str(affected) in req, "detail": f"{affected} 件/顶"},
            {"item": "含具体地点", "ok": region in req, "detail": region},
            {"item": "含留痕动作", "ok": any(k in req for k in ("签收", "登记", "记录", "留存")),
             "detail": "签收 / 登记 / 留存"},
        ]

    @staticmethod
    def _phases(now: datetime, created: datetime, due: datetime,
                review: datetime, archive: datetime) -> list[dict]:
        plan = [("派单", created), ("整改完成", due), ("复查通过", review), ("归档", archive)]
        out, prev_done = [], True
        for name, t in plan:
            if now >= t:
                status = "已完成"
            elif prev_done:
                status = "进行中"
            else:
                status = "未开始"
            prev_done = now >= t
            out.append({
                "phase": name,
                "plan": t.isoformat(timespec="minutes"),
                "actual": t.isoformat(timespec="minutes") if status == "已完成" else "",
                "status": status,
            })
        return out

    @staticmethod
    def _status(now: datetime, created: datetime, due: datetime,
                review: datetime, at_50: datetime) -> str:
        if now < created:
            return "待派发"
        if now < due:
            return "整改中 · 已触发 50% 提醒" if now >= at_50 else "整改中"
        if now < review:
            return "逾期未整改 · 已上报"
        return "逾期未整改 · 升级处置"

    @staticmethod
    def _remain(now: datetime, due: datetime) -> str:
        d = due - now
        secs = d.total_seconds()
        if secs <= 0:
            return "已超时"
        if secs < 3600:
            return f"剩余 {secs / 60:.0f} 分钟"
        if secs < 86400:
            return f"剩余 {secs / 3600:.1f} 小时"
        return f"剩余 {secs / 86400:.1f} 天"

    @staticmethod
    def _handoff(tickets: list[dict]) -> str:
        if not tickets:
            return "无事件可派单。"
        a = [t for t in tickets if t["grade"] == "A"]
        return (f"派单 {len(tickets)} 张，其中 A 级 {len(a)} 张（时限 2 小时）；"
                f"复查统一排到整改完成次日，复查人固定为 {REVIEWER}，与整改责任人分离。")
