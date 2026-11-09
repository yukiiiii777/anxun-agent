# -*- coding: utf-8 -*-
"""
把仓库裁成可发布的瘦身包（线上演示用）
=====================================

线上只要「页面 + ONNX 权重 + 判定代码」三样，不需要训练集、torch 权重、
评测账本。整个仓库 120 MB 直接上传又慢又容易超时，这里只挑必须的文件：

    serve.py
    chat/  demo/
    techline-v3.1.0/src/           判定代码
    techline-v3.1.0/config/        thresholds.json（判定阈值的唯一来源）
    techline-v3.1.0/models/onnx/   best.onnx + yolov8n.onnx
    techline-v3.1.0/datasets/scenes/  4 张现场照片 + scenes.json

产出约 56 MB，比整仓小一半多。

用法：
    python tools/make_deploy.py                 # 生成到仓库旁边的 _deploy/
    python tools/make_deploy.py --out D:/x      # 指定输出目录

发布（需要 WorkBuddy 的发布能力）：
    directory = <out 目录>, language = python
    installCmd = pip install -r requirements.txt
    startCmd   = python serve.py --backend onnx
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TL = "techline-v3.1.0"

REQUIREMENTS = """\
# 线上演示版：只跑 ONNX-CPU，不装 torch（省 2 GB 镜像）
# 判定链路与本地一致，差别只有速度：GPU 15 ms/帧 → CPU 30~40 ms/帧
onnxruntime
numpy
opencv-python-headless
"""


def copytree(src: Path, dst: Path, pattern: str = "*") -> None:
    if not src.exists():
        raise SystemExit(f"缺文件：{src}")
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.rglob(pattern):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成线上演示用的瘦身包")
    ap.add_argument("--out", default=str(ROOT.parent / "_deploy"))
    ap.add_argument("--clean", action="store_true", help="先删掉输出目录")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    if out == ROOT or ROOT.is_relative_to(out):
        raise SystemExit("输出目录不能是仓库本身或它的上级")
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "serve.py", out / "serve.py")
    for page in ("chat", "demo"):
        copytree(ROOT / page, out / page, "*.html")

    tl = ROOT / TL
    copytree(tl / "src", out / TL / "src", "*.py")
    copytree(tl / "config", out / TL / "config", "*.json")
    copytree(tl / "models" / "onnx", out / TL / "models" / "onnx", "*")
    copytree(tl / "datasets" / "scenes", out / TL / "datasets" / "scenes", "*")
    if (tl / "models" / "config.json").exists():
        shutil.copy2(tl / "models" / "config.json", out / TL / "models" / "config.json")

    for pyc in out.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)

    (out / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")

    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    n = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"已生成 {out}")
    print(f"  {n} 个文件，{total / 1048576:.1f} MB")
    print("  下一步：python serve.py --backend onnx   先本机自检，再发布")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
