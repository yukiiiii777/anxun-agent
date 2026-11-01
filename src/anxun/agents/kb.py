# -*- coding: utf-8 -*-
"""
安巡 Agent · 法规知识库（小型、可审计）
======================================

设计约束（抄自 `docs/安巡Agent_提示词库.md` 全局约定第 2 条）：

1. 只收录**逐字核对过**的条文，`quote` 字段是原文，不是概述。
2. 没有把握的条目宁可不收。检索不到就返回 `found=False`，让上层明确回答
   「未检索到直接对应条款」，绝不编造条款号。
3. 标准类文件只登记标准号、名称与适用范围，**不伪造条文原文**；
   `quote=None` 时页面会显示「条文未入库，仅登记标准号」。

文本核对来源：全国人大《中华人民共和国安全生产法》（2021 年第三次修正），
经浙江省应急管理厅公开发布页逐条比对。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_URL = "https://yjt.zj.gov.cn/art/2024/11/6/art_1229892438_2564469.html"
SOURCE_LABEL = "《中华人民共和国安全生产法》（2021 年第三次修正）"


# ============================================================
# 一、条文
# ============================================================

@dataclass(frozen=True)
class Clause:
    key: str
    law: str
    article: str
    title: str
    quote: str
    scope: tuple[str, ...]          # 适用的装备类型；空元组 = 通用
    meaning: str                    # 人话解读，明确标注为「解读」

    @property
    def citation(self) -> str:
        return f"{self.law} {self.article}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "law": self.law,
            "article": self.article,
            "title": self.title,
            "quote": self.quote,
            "citation": self.citation,
            "meaning": self.meaning,
            "source": SOURCE_URL,
            "source_label": SOURCE_LABEL,
        }


LAW = "《中华人民共和国安全生产法》"

CLAUSES: tuple[Clause, ...] = (
    Clause(
        key="saf-45",
        law=LAW,
        article="第四十五条",
        title="劳动防护用品的提供与监督佩戴",
        quote=("生产经营单位必须为从业人员提供符合国家标准或者行业标准的"
               "劳动防护用品，并监督、教育从业人员按照使用规则佩戴、使用。"),
        scope=("helmet", "vest", "goggles"),
        meaning=("「监督」二字是这条的关键：用人单位不只是把帽子发下去就完事，"
                 "还要管有没有戴。本系统的巡检与工单，落点正是这条的"
                 "「监督」义务。"),
    ),
    Clause(
        key="saf-57",
        law=LAW,
        article="第五十七条",
        title="从业人员正确佩戴使用劳动防护用品",
        quote=("从业人员在作业过程中，应当严格落实岗位安全责任，遵守本单位"
               "的安全生产规章制度和操作规程，服从管理，正确佩戴和使用劳动"
               "防护用品。"),
        scope=("helmet", "vest", "goggles"),
        meaning=("这一条对应「人」的责任。工单派给班组长时，整改动作里必须包含"
                 "对当事人的告知与教育，而不是只补发物资。"),
    ),
    Clause(
        key="saf-41",
        law=LAW,
        article="第四十一条",
        title="安全风险分级管控与隐患排查治理",
        quote=("生产经营单位应当建立安全风险分级管控制度，按照安全风险分级"
               "采取相应的管控措施。\n"
               "生产经营单位应当建立健全并落实生产安全事故隐患排查治理制度，"
               "采取技术、管理措施，及时发现并消除事故隐患。事故隐患排查治理"
               "情况应当如实记录，并通过职工大会或者职工代表大会、信息公示栏"
               "等方式向从业人员通报。其中，重大事故隐患排查治理情况应当及时"
               "向负有安全生产监督管理职责的部门和职工大会或者职工代表大会"
               "报告。"),
        scope=(),
        meaning=("「分级」是定级的法律出处：同一条违规在不同风险场景下，"
                 "管控措施本该不同。本系统的 R=L×S 五色分级即落在这条上。"),
    ),
    Clause(
        key="saf-46",
        law=LAW,
        article="第四十六条",
        title="安全生产管理人员的经常性检查与记录",
        quote=("生产经营单位的安全生产管理人员应当根据本单位的生产经营"
               "特点，对安全生产状况进行经常性检查；对检查中发现的安全问题，"
               "应当立即处理；不能处理的，应当及时报告本单位有关负责人，"
               "有关负责人应当及时处理。检查及处理情况应当如实记录在案。"),
        scope=(),
        meaning=("「检查及处理情况应当如实记录在案」是工单必须留痕、必须可"
                 "追溯的直接依据，也是验收环节要求照片/签收记录的原因。"),
    ),
    Clause(
        key="saf-99-5",
        law=LAW,
        article="第九十九条第（五）项",
        title="未提供合规劳动防护用品的罚则",
        quote=("生产经营单位有下列行为之一的，责令限期改正，处五万元以下的"
               "罚款；……情节严重的，责令停产停业整顿；构成犯罪的，依照刑法"
               "有关规定追究刑事责任：……（五）未为从业人员提供符合国家标准"
               "或者行业标准的劳动防护用品的；"),
        scope=("helmet", "vest", "goggles"),
        meaning=("这是「不整改会怎样」的答案。答辩被问「你这系统有什么约束力」"
                 "时，指向这一条比讲技术更有说服力。"),
    ),
)

# ============================================================
# 二、标准（只登记，不伪造条文）
# ============================================================

@dataclass(frozen=True)
class Standard:
    code: str
    name: str
    scope: tuple[str, ...]
    note: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "citation": f"{self.code}《{self.name}》",
            "note": self.note,
            "quote": None,
        }


STANDARDS: tuple[Standard, ...] = (
    Standard(
        code="GB 2811-2019",
        name="头部防护 安全帽",
        scope=("helmet",),
        note="安全帽产品标准。本系统只引用标准号与适用范围，条文原文未入库。",
    ),
    Standard(
        code="GB 39800.1-2020",
        name="个体防护装备配备规范 第1部分：总则",
        scope=("helmet", "vest", "goggles"),
        note="配备与判废的通用要求。条文原文未入库，仅作标准号引用。",
    ),
)

EQUIP_CN = {"helmet": "安全帽", "vest": "反光背心", "goggles": "防护眼镜", "aisle": "消防通道"}


# ============================================================
# 三、检索
# ============================================================

def lookup(equip: str, scene: str = "") -> dict:
    """
    按装备类型检索条文。

    返回结构：
        {"found": bool, "clauses": [...], "standards": [...], "missing": str|None}

    found=False 时上层必须原样回答「未在知识库中检索到直接对应条款」，
    不得自行补一条。
    """
    known = {e for c in CLAUSES for e in c.scope}
    matched = [c for c in CLAUSES if not c.scope or equip in c.scope]
    stds = [s for s in STANDARDS if equip in s.scope]

    if equip not in known:
        return {
            "found": False,
            "equip": equip,
            "equip_cn": EQUIP_CN.get(equip, equip),
            "scene": scene,
            "clauses": [],
            "standards": [],
            "missing": f"知识库未收录「{EQUIP_CN.get(equip, equip)}」相关条款，未检索到直接对应条款",
        }

    return {
        "found": True,
        "equip": equip,
        "equip_cn": EQUIP_CN.get(equip, equip),
        "scene": scene,
        "clauses": [c.to_dict() for c in matched],
        "standards": [s.to_dict() for s in stds],
        "missing": None,
    }


def ticket_basis() -> list[dict]:
    """工单必须留痕的依据，挂在每张工单上。"""
    return [c.to_dict() for c in CLAUSES if c.key == "saf-46"]


def grading_basis() -> dict:
    """定级方法的法律出处。"""
    for c in CLAUSES:
        if c.key == "saf-41":
            return c.to_dict()
    return {}
