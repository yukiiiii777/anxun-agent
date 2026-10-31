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
    for b in r.boxes:
        x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
        boxes.append({
            "label": names[int(b.cls)],
            "conf": round(float(b.conf), 4),
            "x1": round(x1, 1), "y1": round(y1, 1),
            "x2": round(x2, 1), "y2": round(y2, 1),
        })

    h, w = r.orig_shape
    return {"width": int(w), "height": int(h), "infer_ms": round(ms, 1), "boxes": boxes}


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
