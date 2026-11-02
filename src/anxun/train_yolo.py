# -*- coding: utf-8 -*-
"""
安巡 Agent · PPE 检测模型训练脚本
================================

三类目标：person / helmet / vest
（goggles 为预留类别，见 `data/ppe.yaml` 注释——无数据、无权重，未启用）

用法
----
# 单卡训练
python train_yolo.py --device 0

# 双卡训练（你的环境）
python train_yolo.py --device 0,1 --batch 32

# 断点续训
python train_yolo.py --resume

# 小显存降级（先用小分辨率跑通再升）
python train_yolo.py --imgsz 480 --batch 16

说明
----
1. 类别顺序必须与 data/ppe.yaml 一致，否则训练出的模型接进规则引擎会错位。
2. 训练结束会自动跑验证集并打印 mAP / 单帧耗时，这两个数要抄进 PPT 第 11 页。
3. 误报率需要单独测：拿一批「不含违规」的负样本图跑推理，统计误报框数。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

HERE = Path(__file__).parent


def parse_device(s: str):
    """'0,1' -> [0, 1]；'cpu' -> 'cpu'"""
    if s.lower() == "cpu":
        return "cpu"
    return [int(x) for x in s.split(",") if x.strip() != ""]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "ppe.yaml"))
    ap.add_argument("--model", default="yolo11s.pt", help="yolo11n / yolo11s / yolo11m")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--device", default="0")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--project", default=str(HERE / "runs"))
    ap.add_argument("--name", default="ppe")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    from ultralytics import YOLO

    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(
            f"数据集配置不存在：{data_path}\n"
            f"请先按 README 准备数据，并写好 ppe.yaml：\n"
            f"  path: ./data/ppe\n  train: images/train\n  val: images/val\n"
            f"  names: {{0: person, 1: helmet, 2: vest, 3: goggles}}"
        )

    device = parse_device(args.device)
    print("=" * 70)
    print(f"模型 {args.model} | 分辨率 {args.imgsz} | batch {args.batch} | 设备 {device}")
    print("=" * 70)

    model = YOLO(args.model)

    model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        workers=args.workers,
        project=args.project,
        name=args.name,
        resume=args.resume,
        # --- 与现场问题一一对应的数据增强（PPT 第 7 页要讲这个）---
        hsv_h=0.015,        # 色相扰动：不同批次工装颜色差异
        hsv_s=0.6,          # 饱和度扰动：车间灯光色温
        hsv_v=0.45,         # 亮度扰动：逆光 / 弱光
        degrees=8.0,        # 小角度旋转：摄像头安装倾斜
        translate=0.12,     # 平移：工人在画面中位置随机
        scale=0.55,         # 尺度缩放：远近不同的监控距离
        fliplr=0.5,         # 水平翻转：左右站位
        mosaic=1.0,         # 马赛克拼接：小目标与多目标场景
        mixup=0.1,
        erasing=0.3,        # 随机擦除：设备遮挡、多人重叠
        # --- 训练策略 ---
        patience=25,        # 25 轮无提升则早停
        save=True,
        plots=True,         # 生成混淆矩阵、PR 曲线，直接进 PPT
        verbose=True,
    )

    # --- 验证并打印可写进 PPT 的指标 ---
    print("\n" + "=" * 70)
    print("验证集指标")
    print("=" * 70)
    metrics = model.val(data=str(data_path), device=device, plots=True)
    box = metrics.box
    print(f"mAP@0.5      : {box.map50:.4f}")
    print(f"mAP@0.5:0.95 : {box.map:.4f}")
    print(f"Precision    : {box.mp:.4f}")
    print(f"Recall       : {box.mr:.4f}")

    # 单帧耗时（用验证集前 20 张测，取平均）
    try:
        from ultralytics import YOLO as _Y
        best = _Y(str(Path(args.project) / args.name / "weights" / "best.pt"))
        import glob
        imgs = glob.glob(str(Path(args.project).parent / "data" / "ppe" / "images" / "val" / "*"))[:20]
        if imgs:
            t = time.perf_counter()
            for p in imgs:
                best.predict(p, verbose=False, device=device[0] if isinstance(device, list) else device)
            ms = (time.perf_counter() - t) / len(imgs) * 1000
            print(f"单帧推理耗时  : {ms:.1f} ms  (batch=1, 含前后处理)")
    except Exception as e:
        print(f"单帧耗时测量跳过：{e}")

    print(f"\n最佳权重：{Path(args.project) / args.name / 'weights' / 'best.pt'}")
    print("下一步：把 best.pt 路径填进 infer_api.py 的 MODEL_PATH，启动推理服务。")


if __name__ == "__main__":
    main()
