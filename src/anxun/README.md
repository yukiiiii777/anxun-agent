# 安巡 Agent · 作品代码

厂区安全巡检多智能体系统的可运行骨架。归属：第二届全国人工智能应用创新大赛 · 通用赛道 · 制造领域 · 本科生组。

> 项目总入口见 [根目录 README](../../README.md)；技术细节见 [`docs/03-技术架构.md`](../../docs/03-技术架构.md)；数据与指标口径见 [`docs/04-数据与模型.md`](../../docs/04-数据与模型.md)。

> ⚠️ **口径警示（2026-11-10）**：本目录是**早期系统线演示骨架**，定级仍是
> `v1.2 / R = L × S / 红橙黄蓝`，只用于演示「四态判定 → 工单」这条链路。
> **对外报数、答辩、PPT、视频、在线研判台一律以
> [`techline-v3.1.0/src/anxun/`](../../techline-v3.1.0/src/anxun/) 与
> [《安巡风险分级标准 v1.4》](../../docs/安巡风险分级标准.md) 为准**
> （A / B / C 按本次确认未佩戴人数分处置时限，不看作业类型与区域历史）。
> 本目录算出的 R 值与颜色等级**已作废，不得引用**。

## 核心设计：判定逻辑与检测模型解耦

```
检测模型（可替换）  ->  规则引擎（确定性）  ->  Agent（编排与对话）
     infer_api.py          rules_engine.py       扣子 / JoyCode
```

这条边界是本作品的技术底座。好处：

1. **模型没训好也能演示**：规则引擎跑模拟框就能出完整结果（`demo.py`）
2. **换模型不影响业务逻辑**：YOLO 换成 RT-DETR 只改 `infer_api.py`
3. **换平台不用重写**：扣子换 JoyCode 只改调用地址
4. **结果可复现**：同一输入永远同一输出，答辩敢让人当场重算

## 目录

| 文件 | 作用 | 依赖 |
|---|---|---|
| `rules_engine.py` | PPE 判定 + 旧版风险矩阵（v1.2，已作废）+ 工单生成 | 纯标准库 |
| `demo.py` | 端到端演示，输出控制台报告 / json / html | 纯标准库 |
| `agents/` | ②③④ 三个 Agent 的本地实现（感知 / 研判 / 工单） | 纯标准库 |
| `run_agents.py` | 多智能体入口：`python run_agents.py --serve` | 纯标准库 |
| `infer_api.py` | 检测模型 HTTP 封装 | fastapi + ultralytics |
| `train_yolo.py` | 模型训练与验证 | ultralytics |
| `data/ppe.yaml` | 数据集配置模板 | — |

## 快速开始（不需要模型，5 分钟）

```bash
python demo.py
```

会生成：
- 控制台完整报告
- `result.json` — 结构化结果，可直接喂给 Agent
- `report.html` — 带画面标注的巡检报告，**可直接截图进 PPT**

## 跑三个 Agent（本地，不依赖扣子）

`demo.py` 是把链路跑给你看，`run_agents.py` 是把链路**拆成三个能对话的 Agent**：

```bash
python run_agents.py            # A/B/C 三场景，终端看完整交接
python run_agents.py --scene B  # 单场景
python run_agents.py --serve    # 本地网页，127.0.0.1:8611
```

细节与设计取舍见 [`agents/README.md`](agents/README.md)。

## 训练模型

### 1. 准备数据

```
data/ppe/
  images/train/  *.jpg
  images/val/    *.jpg
  labels/train/  *.txt   # YOLO 格式，每行: cls cx cy w h（归一化）
  labels/val/    *.txt
```

类别顺序固定为 `person / helmet / vest`（`goggles` 为预留类别，当前无数据、未启用），见 `data/ppe.yaml`。

**划分要点**：同一视频抽出的帧不要跨 train/val，否则验证集指标虚高。按视频划分，不按帧划分。

### 2. 训练

```bash
pip install -r requirements.txt

# 双卡
python train_yolo.py --device 0,1 --batch 32 --model yolo11s.pt

# 小显存先跑通
python train_yolo.py --device 0 --imgsz 480 --batch 16 --model yolo11n.pt
```

训练结束会打印 `mAP@0.5 / mAP@0.5:0.95 / Precision / Recall / 单帧耗时`，这四个数抄进 PPT 第 11 页。

`runs/ppe/` 下的混淆矩阵、PR 曲线图直接可用于 PPT。

## 启动推理服务

```bash
set MODEL_PATH=runs/ppe/weights/best.pt
uvicorn infer_api:app --host 0.0.0.0 --port 8000
```

测试：

```bash
curl -X POST "http://127.0.0.1:8000/detect" -F "file=@test.jpg"
```

返回：

```json
{"width":1920,"height":1080,"infer_ms":31.2,
 "boxes":[{"label":"person","conf":0.94,"x1":300,"y1":300,"x2":540,"y2":920}]}
```

**本地服务要接云端 Agent，需要公网地址**：用内网穿透（cpolar / ngrok）临时映射，或部署到有公网 IP 的服务器。演示前一定先测通，别到录屏当天才发现连不上。

## 接进扣子 / Coze

1. 新建 Bot，粘贴 [`docs/安巡Agent_提示词库.md`](../../docs/安巡Agent_提示词库.md) 中 ② 视觉感知 Agent 的提示词
2. 添加自定义插件，指向 `POST /detect_b64`，入参 `image_base64`
3. 把返回的 `boxes` 塞进提示词上下文，让 Agent 按规则判定
4. 风险矩阵**不要交给模型算**，写成工作流节点或本地 Python 调用

## 关键指标怎么测

### 误报率（比 mAP 更该强调）

准备一批**不含违规**的负样本图（正常戴帽的工人、空场景、设备特写），跑推理：

```
误报率 = 被判为「未佩戴」但实际合规的人数 / 总人数
```

目标是 ≤ 10%。工业场景里误报率高会导致告警被直接关掉，这比漏报更难挽回信任。

### 漏报率

用验证集里的违规样本测：

```
漏报率 = 实际违规但未被判出的人数 / 实际违规人数
```

安全场景漏报后果更严重，应主动在 PPT 里说明这个数。

## 答辩可讲的技术点

| 设计 | 为什么这么做 | 被问到怎么答 |
|---|---|---|
| 置信度三档 | 防止低质量检测直接变成误报 | 0.20 以下丢弃，0.20–0.30 转人工，0.30 以上定论 |
| 时序聚合 | 压制单帧抖动 | 连续 3 帧一致才定论 |
| 小目标拦截 | 远处的模糊目标最容易误判 | 面积 < 8000px² 直接「无法判定」，不输出违规 |
| 计算与语言分离 | 大模型算数不可靠 | 定级走 Python 矩阵，不让模型乘法 |
| 每结论带 reason | 可追溯、可审计 | 屏幕上直接能看到「为什么这么判」 |

## 已知局限（主动写进 PPT 第 16 页）

- 规则依赖人工设定的阈值，不同厂区像素尺度差异大，`MIN_PERSON_AREA` 需按相机标定重设
- 只覆盖正面/侧面视角，完全背影或俯视场景未验证
- 未做跨镜头人员重识别，同一人换镜头会重复计数
- 手部细粒度动作（如手套穿脱）不在当前范围内
