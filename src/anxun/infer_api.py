# -*- coding: utf-8 -*-
"""
安巡 Agent · 视觉检测推理服务
=============================

把 PPE 检测模型封装成独立 HTTP API。
这是整个架构里最关键的一个解耦点：
  - Agent 平台（扣子 / JoyCode）只负责编排和对话
  - 视觉能力独立部署，换平台不用重写模型

启动
----
    set MODEL_PATH=runs/ppe/weights/best.pt
    uvicorn infer_api:app --host 0.0.0.0 --port 8000

接口
----
POST /detect        表单上传图片文件，返回检测框
POST /detect_b64    JSON 传入 base64 图片（扣子插件更方便）
GET  /health        健康检查

返回格式与 rules_engine.Box 严格对齐，可直接喂给规则引擎：
    {"width":1920,"height":1080,
     "boxes":[{"label":"person","conf":0.94,"x1":300,"y1":300,"x2":540,"y2":920}, ...]}

标签契约（重要）
----------------
模型和数据集的类别名不统一：数据集是 9 类 `person / hardhat / no_hardhat / vest /
no_vest / boots / no_boots / gloves / no_gloves`，而规则引擎只认
`person / helmet / vest / goggles`（见 `rules_engine.Box`）。

**不做映射，接上真模型后所有人都会被判成「未佩戴」**——因为 `helmet` 永远对不上。
所以这里有一层 `LABEL_MAP`：

- 正类（hardhat/helmet → helmet，vest → vest）直接归一
- 负类（no_hardhat / no_vest）**丢弃**：规则引擎的判据是「头部区域里有没有装备框」，
  没有就是违规，负类框塞进去反而会被当成「有装备」
- 映射不上的类别丢弃，并在返回里记 `dropped_labels`，方便上线时一眼看出契约没对齐
"""

from __future__ import annotations

import base64
import io
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

MODEL_PATH = os.getenv("MODEL_PATH", "runs/ppe/weights/best.pt")
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.25"))

# 模型类别 -> 规则引擎类别。None = 该类别不产生装备框（负类）
LABEL_MAP: dict[str, str | None] = {
    "person": "person",
    "hardhat": "helmet",
    "helmet": "helmet",
    "safety_helmet": "helmet",
    "no_hardhat": None,
    "nohardhat": None,
    "no-helmet": None,
    "vest": "vest",
    "safety_vest": "vest",
    "no_vest": None,
    "novest": None,
    "goggles": "goggles",
    "glasses": "goggles",
}


def normalize_label(raw: str) -> str | None:
    """把模型类别名归一成规则引擎认的三种。未知类别返回 None（丢弃）。"""
    return LABEL_MAP.get(raw.strip().lower())


state: dict = {"model": None, "loaded_at": None, "error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from ultralytics import YOLO
        state["model"] = YOLO(MODEL_PATH)
        state["loaded_at"] = time.time()
        print(f"[anxun] 模型已加载：{MODEL_PATH}")
    except Exception as e:
        state["error"] = str(e)
        print(f"[anxun] 模型加载失败：{e}（/health 会返回 degraded）")
    yield
    state.clear()


app = FastAPI(title="安巡 Agent 视觉服务", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _infer(image) -> dict:
    model = state["model"]
    if model is None:
        raise HTTPException(503, f"模型未加载：{state['error']}")
    t0 = time.perf_counter()
    r = model.predict(image, conf=CONF_THRESHOLD, verbose=False)[0]
    ms = (time.perf_counter() - t0) * 1000

    names = r.names
    boxes = []
    dropped: dict[str, int] = {}
    for b in r.boxes:
        raw_label = str(names[int(b.cls)])
        label = normalize_label(raw_label)
        if label is None:                 # 负类或未知类别：不进设备框
            dropped[raw_label] = dropped.get(raw_label, 0) + 1
            continue
        x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
        boxes.append({
            "label": label,
            "conf": round(float(b.conf), 4),
            "x1": round(x1, 1), "y1": round(y1, 1),
            "x2": round(x2, 1), "y2": round(y2, 1),
        })

    h, w = r.orig_shape
    out = {"width": int(w), "height": int(h), "infer_ms": round(ms, 1), "boxes": boxes}
    if dropped:
        out["dropped_labels"] = dropped   # 出现即说明标签契约没对齐，上线时先看这里
    return out


def _to_image(raw: bytes):
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"图片解析失败：{e}")
    return img


@app.get("/health")
def health():
    return {
        "status": "ok" if state["model"] is not None else "degraded",
        "model": MODEL_PATH,
        "error": state["error"],
        "uptime_s": round(time.time() - state["loaded_at"], 1) if state["loaded_at"] else 0,
    }


@app.post("/detect")
async def detect(file: UploadFile = File(...)):
    """表单上传。适合自建前端、Postman 调试。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    return _infer(_to_image(raw))


class B64Request(BaseModel):
    image_base64: str


@app.post("/detect_b64")
def detect_b64(req: B64Request):
    """base64 传入。扣子的「自定义插件」走这条路最省事。"""
    s = req.image_base64
    if "," in s:                      # 兼容 data:image/jpeg;base64,xxx
        s = s.split(",", 1)[1]
    try:
        raw = base64.b64decode(s)
    except Exception as e:
        raise HTTPException(400, f"base64 解码失败：{e}")
    return _infer(_to_image(raw))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
