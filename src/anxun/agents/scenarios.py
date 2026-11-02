# -*- coding: utf-8 -*-
"""
演示场景数据
============

三个机位、三套判定、三个等级。数据全部写死，不随机——答辩现场重跑结果必须一致。

刻意设计的五个点：

| 人员 | 设计 | 想证明什么 |
|---|---|---|
| P1 | 帽 0.93、背心 0.89 | 正常放行，不制造噪音 |
| P2 | 帽置信度 0.35 / 0.25 / 0.32 / 0.28 抖动 | 时序聚合：单帧会误判，连续帧才定论 |
| P3 | 无安全帽 | 违规主体，进定级 |
| P4 | 面积 6000px² / 遮挡 | 两道失效保护：小目标、遮挡，都不许报违规 |
| P5 | 有帽、无背心 | 第二个违规类型，验证 S 值随类型变化 |

同一批人换到三个区域，等级从 2 分到 16 分——这就是「同样一条告警，
不是同一个责任」的实证。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from rules_engine import Box, Region

from .perception import Frame

T0 = datetime(2026, 11, 3, 9, 20, 0)
FRAME_GAP = timedelta(seconds=2)

REGIONS: dict[str, Region] = {
    "A": Region("A-03", "3 号车间东侧通道", "普通", "李建国", violation_30d=4),
    "B": Region("B-01", "2 号车间高处作业平台", "高处", "王志强", violation_30d=7),
    "C": Region("C-07", "原料库装卸区", "车辆", "赵明", violation_30d=1),
}

# P2 安全帽置信度逐帧抖动：0.35 定论 → 0.25 灰区 → 0.32 → 0.28 灰区
P2_HELMET = (0.35, 0.25, 0.32, 0.28)


def _persons(kind: str) -> list[Box]:
    p4 = (1650, 700, 1710, 800) if kind != "B" else (1560, 300, 1660, 900)
    return [
        Box("person", 0.94, 300, 300, 540, 920),      # P1 正常
        Box("person", 0.88, 700, 320, 940, 940),      # P2 帽子置信度抖动
        Box("person", 0.91, 1100, 310, 1340, 930),    # P3 违规主体
        Box("person", 0.71, *p4),                     # P4 远处小目标 / 遮挡
        Box("person", 0.89, 1500, 300, 1700, 900),    # P5 缺背心
    ]


def _equips(kind: str, i: int) -> list[Box]:
    boxes = [
        Box("helmet", 0.93, 320, 290, 520, 410),          # P1 帽
        Box("helmet", P2_HELMET[i], 720, 310, 920, 430),  # P2 帽（抖动）
        Box("vest", 0.89, 310, 470, 530, 760),            # P1 背心
        Box("vest", 0.87, 710, 490, 930, 780),            # P2 背心
    ]
    if kind == "C":
        # 车辆区：P3 戴帽没穿背心，P5 穿背心没戴帽
        boxes += [
            Box("helmet", 0.90, 1120, 300, 1320, 420),    # P3 帽
            Box("vest", 0.84, 1510, 480, 1690, 770),      # P5 背心
        ]
    else:
        boxes += [
            Box("helmet", 0.80, 1520, 290, 1690, 410),    # P5 帽
            Box("vest", 0.86, 1110, 480, 1330, 770),      # P3 背心
        ]
    return boxes


def frames_for(kind: str) -> list[Frame]:
    occluded = (3,) if kind == "B" else ()
    out = []
    for i in range(4):
        out.append(Frame(
            index=i + 1,
            ts=T0 + FRAME_GAP * i,
            boxes=_persons(kind) + _equips(kind, i),
            occluded=occluded,
        ))
    return out


SCENES: dict[str, dict] = {
    "A": {
        "key": "A",
        "title": "3 号车间东侧通道 · 普通作业",
        "camera": "ANX-CAM-03",
        "resolution": (1920, 1080),
        "subject": "安全帽未佩戴 + 反光背心未穿戴",
    },
    "B": {
        "key": "B",
        "title": "2 号车间高处作业平台 · 高处作业",
        "camera": "ANX-CAM-07",
        "resolution": (1920, 1080),
        "subject": "同一违规换到高处作业场景",
    },
    "C": {
        "key": "C",
        "title": "原料库装卸区 · 车辆通行",
        "camera": "ANX-CAM-11",
        "resolution": (1920, 1080),
        "subject": "反光背心未穿戴为主，等级拉开差距",
    },
}

SCENE_KEYS = ("A", "B", "C")


def get_scene(key: str) -> dict:
    k = key.upper()
    if k not in SCENES:
        raise KeyError(f"未知场景 {key}，可选：{', '.join(SCENE_KEYS)}")
    meta = dict(SCENES[k])
    meta["region"] = REGIONS[k]
    meta["frames"] = frames_for(k)
    return meta
