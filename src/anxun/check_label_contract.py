# -*- coding: utf-8 -*-
"""校验 infer_api 的标签契约层：语法 + 映射表 + 归一函数。"""
import ast
from pathlib import Path

SRC = Path("infer_api.py")
tree = ast.parse(SRC.read_text(encoding="utf-8"))

label_map = None
fn_src = None
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "LABEL_MAP":
        label_map = ast.literal_eval(node.value)
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LABEL_MAP":
        label_map = ast.literal_eval(node.value)
    if isinstance(node, ast.FunctionDef) and node.name == "normalize_label":
        fn_src = ast.get_source_segment(SRC.read_text(encoding="utf-8"), node)

assert label_map, "没找到 LABEL_MAP"
assert fn_src, "没找到 normalize_label"

ns: dict = {"LABEL_MAP": label_map}
exec(fn_src, ns)
normalize = ns["normalize_label"]

print(f"LABEL_MAP 共 {len(label_map)} 条")
print(f"{'模型输出':<14}{'规则引擎':<10}")
for raw in ["person", "Hardhat", "NOHardhat", "hardhat", "no_hardhat",
            "vest", "no_vest", "Vest", "goggles", "boots", "no_gloves", "unknown"]:
    print(f"  {raw:<12}-> {normalize(raw)}")

# 断言关键行为
assert normalize("person") == "person"
assert normalize("Hardhat") == "helmet"
assert normalize("hardhat") == "helmet"
assert normalize("NOHardhat") is None, "负类必须丢弃"
assert normalize("no_vest") is None, "负类必须丢弃"
assert normalize("vest") == "vest"
assert normalize("boots") is None, "未映射类别必须丢弃"
print("\n关键断言全部通过")
