# -*- coding: utf-8 -*-
"""
安巡 Agent · 规则引擎
=====================

纯确定性实现：PPE 判定 -> 风险矩阵定级 -> 工单生成

设计原则
--------
1. 不调用任何大模型做判定或计算。同一输入永远同一输出，可复现、可审计。
2. 所有阈值集中在「一、阈值配置」，答辩时可逐条说明依据。
3. 每个结论都带 reason 字段，回答「为什么这么判」。
4. 检测模型只负责产出 Box，不参与任何决策。换模型不影响本文件。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Sequence


# ============================================================
# 一、阈值配置
# ============================================================

# 阈值口径：与实测线（techline-v2.2.0）统一，2026-11-02 由队长确认
# 两套阈值并行的后果是「同一个 0.52 的帽子，演示判待复核、评测判已佩戴」，
# 答辩现场两边一对照就穿帮。这里以「能当场复现的那套」为准。
CONF_FINAL = 0.30          # >= 此值：直接下结论
CONF_REVIEW = 0.20         # [此值, CONF_FINAL)：转人工复核
                           # <  CONF_REVIEW ：丢弃，不输出

HELMET_IOU_MIN = 0.25      # 安全帽框与头部区域的 IoU 阈值
HEAD_REGION_RATIO = 0.30   # 头部区域 = 人员框上部 30%

MIN_PERSON_AREA = 8000.0   # 人员框面积下限（像素^2），小于此值视为过远/过小
MIN_ASPECT = 0.90          # 人员框高宽比下限，小于此值视为半身/蹲姿，无法判定
MAX_EQUIP_RATIO = 3.0      # 装备框面积 / 比对区域面积 的上限，超了多半是关联错框

# 风险矩阵：30 天违规次数 -> 可能性 L
# (次数上限, L 值)，超出最后一档取 4
L_TABLE = ((1, 1), (3, 2), (6, 3))
L_MAX = 4

# 风险矩阵：违规类型 + 场景 -> 后果严重度 S
S_MAP = {
    ("helmet",  "高处"): 4,   # 高处作业未戴安全帽
    ("helmet",  "起重"): 4,   # 起重作业未戴安全帽
    ("helmet",  "动火"): 3,
    ("helmet",  "普通"): 3,
    ("vest",    "车辆"): 3,   # 有车辆通行区域未穿反光背心
    ("vest",    "普通"): 2,
    ("goggles", "飞溅"): 3,
    ("goggles", "普通"): 2,
    ("aisle",   "消防通道"): 3,
}
S_DEFAULT = 2

# 等级判定：(风险值下限, 等级, 处置要求, 整改时限)
GRADE_RULES = (
    (12, "红色", "立即停止作业并整改", timedelta(hours=2)),
    (8,  "橙色", "当日整改",           timedelta(hours=24)),
    (4,  "黄色", "限期整改",           timedelta(days=7)),
    (0,  "蓝色", "加强关注",           timedelta(days=30)),
)

# 违规类型 -> 中文名 + 整改动作模板
VIOLATION_INFO = {
    "helmet":  ("未佩戴安全帽",
                "补发安全帽 {n} 顶至 {region}，登记发放签收记录，次日复查佩戴率"),
    "vest":    ("未穿戴反光背心",
                "补发反光背心 {n} 件至 {region}，登记领用记录，次日复查穿戴率"),
    "goggles": ("未佩戴防护眼镜",
                "配发防护眼镜 {n} 副至 {region}，登记领用记录，次日复查佩戴率"),
    "aisle":   ("消防通道占用",
                "清空 {region} 消防通道堆物，恢复通行宽度并拍照留存，24 小时内复查"),
}


# ============================================================
# 二、基础数据结构
# ============================================================

@dataclass
class Box:
    """一个检测框。这是检测模型与本引擎之间唯一的接口。"""
    label: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    def top_region(self, ratio: float = HEAD_REGION_RATIO) -> "Box":
        """返回框的顶部区域（默认上部 30%），用于圈定头部范围。"""
        return Box(self.label, self.conf, self.x1, self.y1,
                   self.x2, self.y1 + self.h * ratio)


def iou(a: Box, b: Box) -> float:
    """交并比。"""
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


# ============================================================
# 三、PPE 判定
# ============================================================

@dataclass
class Verdict:
    """单人单类装备的判定结果。"""
    person_idx: int
    equip: str              # helmet / vest / goggles
    status: str             # 已佩戴 / 未佩戴 / 无法判定 / 待复核 / 丢弃
    conf: float
    reason: str
    is_violation: bool = False


def judge_equipment(person: Box, idx: int, boxes: Sequence[Box],
                    equip: str) -> Verdict:
    """
    判定单人某项装备的佩戴状态。

    判定链：
      1. 尺度/姿态可用性检查 -> 不合格直接「无法判定」
      2. 取头部（或上身）区域，与同类装备框求最大 IoU
      3. 达阈值 -> 已佩戴；未达 -> 未佩戴
      4. 按置信度分档：定论 / 待复核 / 丢弃
    """
    # --- 1. 可用性检查 ---
    if person.area < MIN_PERSON_AREA:
        return Verdict(idx, equip, "无法判定", person.conf,
                       f"人员框面积 {person.area:.0f}px² 小于下限 {MIN_PERSON_AREA:.0f}px²，目标过小")
    if person.h / max(person.w, 1e-6) < MIN_ASPECT:
        return Verdict(idx, equip, "无法判定", person.conf,
                       f"高宽比 {person.h / max(person.w, 1e-6):.2f} 小于 {MIN_ASPECT}，疑似半身或非站姿")

    # --- 2. 圈定比对区域 ---
    if equip == "helmet":
        region = person.top_region(HEAD_REGION_RATIO)
        region_name = "头部区域"
    elif equip == "goggles":
        region = person.top_region(0.45)
        region_name = "面部区域"
    else:  # vest
        region = Box("torso", person.conf, person.x1,
                     person.y1 + person.h * 0.20,
                     person.x2, person.y1 + person.h * 0.70)
        region_name = "上身区域"

    # --- 3. 找最佳匹配框 ---
    candidates = [b for b in boxes if b.label == equip]
    best, best_iou = None, 0.0
    for b in candidates:
        v = iou(region, b)
        if v > best_iou:
            best, best_iou = b, v

    # 装备框比比对区域大出数倍，基本是「把远处的帽子关联到近处的人」这类错配
    if best is not None and region.area > 0 and best.area > region.area * MAX_EQUIP_RATIO:
        best, best_iou = None, 0.0

    # --- 4. 结论 ---
    if best is not None and best_iou >= HELMET_IOU_MIN:
        conf = best.conf
        if conf < CONF_REVIEW:
            return Verdict(idx, equip, "丢弃", conf,
                           f"装备框置信度 {conf:.2f} 低于 {CONF_REVIEW}，不可用")
        if conf < CONF_FINAL:
            return Verdict(idx, equip, "待复核", conf,
                           f"装备框与{region_name} IoU={best_iou:.2f} 成立，但置信度 {conf:.2f} 落在复核区间")
        return Verdict(idx, equip, "已佩戴", conf,
                       f"装备框与{region_name} IoU={best_iou:.2f}，置信度 {conf:.2f}")

    # 未匹配到装备框 -> 未佩戴。此时可信度取决于「人」判定得多确定
    conf = person.conf
    if conf < CONF_REVIEW:
        return Verdict(idx, equip, "丢弃", conf,
                       f"人员框置信度 {conf:.2f} 过低，不作为依据")
    if conf < CONF_FINAL:
        return Verdict(idx, equip, "待复核", conf,
                       f"{region_name}内未检出装备框，但人员框置信度 {conf:.2f} 落在复核区间")
    return Verdict(idx, equip, "未佩戴", conf,
                   f"{region_name}内未检出装备框（最高 IoU={best_iou:.2f} < {HELMET_IOU_MIN}），判定为未佩戴",
                   is_violation=True)


def judge_frame(boxes: Sequence[Box],
                equips: Sequence[str] = ("helmet", "vest")) -> list[Verdict]:
    """对一帧内的所有人做指定装备的判定。"""
    persons = [b for b in boxes if b.label == "person"]
    out: list[Verdict] = []
    for i, p in enumerate(persons):
        for e in equips:
            out.append(judge_equipment(p, i, boxes, e))
    return out


def aggregate_temporal(frames: Sequence[Sequence[Verdict]],
                       need: int = 3) -> list[Verdict]:
    """
    时序聚合：同一人员连续 need 帧结论一致才定论。
    不足 need 帧的标为「待复核」。用于压制单帧抖动。
    """
    if len(frames) < need:
        res = []
        for v in frames[-1]:
            if v.status in ("已佩戴", "未佩戴"):
                res.append(Verdict(v.person_idx, v.equip, "待复核", v.conf,
                                   f"仅 {len(frames)} 帧，不足 {need} 帧时序确认"))
            else:
                res.append(v)
        return res

    window = frames[-need:]
    final: list[Verdict] = []
    for k, last in enumerate(window[-1]):
        seq = [w[k].status for w in window if k < len(w)]
        if len(seq) == need and len(set(seq)) == 1:
            st = seq[0]
            if st in ("已佩戴", "未佩戴"):
                final.append(Verdict(last.person_idx, last.equip, st, last.conf,
                                     f"连续 {need} 帧一致：" + last.reason,
                                     is_violation=(st == "未佩戴")))
            else:
                # 无法判定 / 丢弃 属于失效状态，不得被改写为待复核
                final.append(Verdict(last.person_idx, last.equip, st, last.conf,
                                     last.reason))
        else:
            final.append(Verdict(last.person_idx, last.equip, "待复核", last.conf,
                                 f"连续 {need} 帧结论不一致：{seq}"))
    return final


# ============================================================
# 四、风险矩阵
# ============================================================

def likelihood(violation_count_30d: int) -> int:
    """可能性 L：由该区域近 30 天违规次数决定。"""
    for cap, val in L_TABLE:
        if violation_count_30d <= cap:
            return val
    return L_MAX


def severity(equip: str, scene: str) -> int:
    """后果严重度 S：由违规类型 + 作业场景决定。"""
    return S_MAP.get((equip, scene), S_DEFAULT)


def grade_of(risk: int) -> tuple[str, str, timedelta]:
    """风险值 -> (等级, 处置要求, 整改时限)。"""
    for low, name, action, due in GRADE_RULES:
        if risk >= low:
            return name, action, due
    return "蓝色", "加强关注", timedelta(days=30)


# ============================================================
# 五、事件与工单
# ============================================================

@dataclass
class Region:
    region_id: str
    name: str
    scene: str                 # 高处 / 起重 / 动火 / 车辆 / 普通 / 消防通道
    owner: str                 # 责任班组长
    violation_30d: int = 0


@dataclass
class Event:
    event_id: str
    region: Region
    equip: str
    ts: datetime
    conf: float
    evidence: str
    L: int = 0
    S: int = 0
    R: int = 0
    grade: str = ""
    action: str = ""
    due_at: datetime | None = None


def build_event(region: Region, equip: str, ts: datetime,
                conf: float, evidence: str, event_id: str = "") -> Event:
    """把一条违规判定转成带定级的事件。"""
    L = likelihood(region.violation_30d)
    S = severity(equip, region.scene)
    R = L * S
    g, act, due_delta = grade_of(R)
    return Event(
        event_id=event_id or f"EV-{ts:%Y%m%d%H%M%S}-{region.region_id}",
        region=region, equip=equip, ts=ts, conf=conf, evidence=evidence,
        L=L, S=S, R=R, grade=g, action=act, due_at=ts + due_delta,
    )


def make_ticket(ev: Event, affected: int = 1) -> dict:
    """生成可执行、可追踪的整改工单。"""
    cn, tpl = VIOLATION_INFO.get(ev.equip, ("未知违规", "整改{region}"))
    requirement = tpl.format(n=affected, region=ev.region.name)
    escalate_1 = ev.ts + (ev.due_at - ev.ts) * 0.5
    return {
        "ticket_id": f"TK-{ev.event_id.split('-', 1)[1]}",
        "event_id": ev.event_id,
        "violation": cn,
        "region": ev.region.name,
        "grade": ev.grade,
        "risk": ev.R,
        "requirement": requirement,
        "assignee": ev.region.owner,
        "cc": "部门安全负责人" if ev.grade == "红色" else "",
        "created_at": ev.ts.isoformat(timespec="minutes"),
        "due_at": ev.due_at.isoformat(timespec="minutes"),
        "review_at": (ev.due_at + timedelta(days=1)).isoformat(timespec="minutes"),
        "escalate_at_50pct": escalate_1.isoformat(timespec="minutes"),
        "status": "派单",
    }


def to_json(obj) -> str:
    import json
    def conv(o):
        if isinstance(o, datetime):
            return o.isoformat(timespec="minutes")
        if hasattr(o, "__dataclass_fields__"):
            d = asdict(o)
            return d
        raise TypeError(str(type(o)))
    return json.dumps(obj, ensure_ascii=False, indent=2, default=conv)
