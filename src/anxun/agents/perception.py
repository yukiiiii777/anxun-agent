# -*- coding: utf-8 -*-
"""
② 视觉感知 Agent
================

职责：把「检测框」变成「四态判定」。

    输入：连续帧的检测框（person / helmet / vest / goggles）+ 帧元信息
    输出：每人每类装备的四态结论 + 违规清单

四态是硬约束（提示词库「常见翻车点」第 1 条）：已佩戴 / 未佩戴 / 待复核 / 无法判定。
任何模糊表述都不允许出现在输出里。

判定本身不在这里发明——`judge_frame()` 与 `aggregate_temporal()` 来自
`rules_engine.py`，本 Agent 只负责三件事：

1. 遮挡保护（提示词规则 6）：可见面积不足 40% 的人直接判「无法判定」，不许出违规。
2. 逐帧记录，让「为什么是待复核」在界面上可解释。
3. 把结果整理成下一位 Agent 能直接吃的结构化消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from rules_engine import (
    Box,
    Verdict,
    aggregate_temporal,
    judge_frame,
    CONF_FINAL,
    CONF_REVIEW,
)

STATUS_ORDER = ("已佩戴", "未佩戴", "待复核", "无法判定")
EQUIP_CN = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜"}


@dataclass
class Frame:
    """一帧检测结果。检测模型与本 Agent 之间唯一的接口。"""
    index: int
    ts: datetime
    boxes: list[Box]
    occluded: tuple[int, ...] = ()      # 可见面积 < 40% 的人员序号

    @property
    def persons(self) -> list[Box]:
        return [b for b in self.boxes if b.label == "person"]


class PerceptionAgent:
    name = "② 视觉感知"
    role = "视觉合规判定员"

    def run(self, frames: list[Frame], equips: tuple[str, ...] = ("helmet", "vest"),
            trace=None) -> dict:
        if not frames:
            raise ValueError("至少需要一帧检测结果")

        per_frame = []
        judged_frames: list[list[Verdict]] = []

        for f in frames:
            verdicts = judge_frame(f.boxes, equips=equips)
            verdicts = self._apply_occlusion(verdicts, f.occluded)
            judged_frames.append(verdicts)
            per_frame.append({
                "frame": f.index,
                "ts": f.ts.isoformat(timespec="seconds"),
                "persons": len(f.persons),
                "occluded": list(f.occluded),
                "statuses": [v.status for v in verdicts],
            })
            if trace:
                trace.record(self.name, "单帧判定", frame=f.index,
                             persons=len(f.persons),
                             summary=self._counts(verdicts))

        final = aggregate_temporal(judged_frames, need=3)
        violations = [v for v in final if v.is_violation]
        counts = self._counts(final)

        if trace:
            trace.record(self.name, "时序聚合", frames=len(frames),
                         rule="连续 3 帧一致才定论",
                         summary=counts,
                         violations=len(violations))

        return {
            "agent": self.name,
            "role": self.role,
            "frames": len(frames),
            "equips": list(equips),
            "counts": counts,
            "per_frame": per_frame,
            "verdicts": [self._verdict_dict(v) for v in final],
            "violations": [self._verdict_dict(v) for v in violations],
            "handoff_note": self._handoff_note(final, violations, counts),
        }

    # ---------------- 内部 ----------------

    @staticmethod
    def _apply_occlusion(verdicts: list[Verdict], occluded: tuple[int, ...]) -> list[Verdict]:
        """提示词规则 6：遮挡严重时不得输出违规，只能「无法判定」。"""
        if not occluded:
            return verdicts
        out = []
        for v in verdicts:
            if v.person_idx in occluded and v.status in ("已佩戴", "未佩戴"):
                out.append(Verdict(
                    v.person_idx, v.equip, "无法判定", v.conf,
                    f"人员可见面积低于 40%（遮挡），按遮挡规则不参与判定",
                ))
            else:
                out.append(v)
        return out

    @staticmethod
    def _counts(verdicts: list[Verdict]) -> dict:
        c = {k: 0 for k in STATUS_ORDER}
        for v in verdicts:
            c[v.status] = c.get(v.status, 0) + 1
        c["定论"] = c["已佩戴"] + c["未佩戴"]
        c["项数"] = len(verdicts)
        return c

    @staticmethod
    def _verdict_dict(v: Verdict) -> dict:
        return {
            "person": f"P{v.person_idx + 1}",
            "person_idx": v.person_idx,
            "equip": v.equip,
            "equip_cn": EQUIP_CN.get(v.equip, v.equip),
            "status": v.status,
            "conf": round(v.conf, 3),
            "reason": v.reason,
            "is_violation": v.is_violation,
        }

    @staticmethod
    def _handoff_note(final, violations, counts) -> str:
        pending = counts.get("待复核", 0) + counts.get("无法判定", 0)
        if not violations:
            return (f"本批次无定论违规（待复核/无法判定 {pending} 项），"
                    f"不向下游派发事件，转人工复核队列。")
        return (f"确认违规 {len(violations)} 项，另有 {pending} 项未定论已拦在"
                f"本 Agent 内、不进入定级环节。违规清单移交 ③ 隐患研判。")
