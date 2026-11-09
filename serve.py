# -*- coding: utf-8 -*-
"""
安巡 Agent · 研判台本地服务
===========================

一个进程把三件事做完，评委面前不用开三个窗口：

    GET  /                    研判台（chat/index.html）
    GET  /demo/               多智能体链路静态页
    GET  /api/health          服务 / 模型 / 对话后端状态
    GET  /api/scenes          真实样例（带 A/B/C 场景映射）
    POST /api/inspect         {scene_id}                    真模型跑一个样例场景
    POST /api/inspect         {image_base64, region_id}     真模型跑任意上传图片
    POST /api/chat            对话（转发 DeepSeek；需 DEEPSEEK_API_KEY）

为什么要有它：
    `chat/index.html` 原来只有两种状态——预置回答，或浏览器直连 DeepSeek。
    两种情况都没有跑过我们自己训的 best.pt：右侧四态判定和工单都是手写数据。
    这个服务把 techline 的模型链路接进来，页面右侧改成「best.pt 实测」。

启动：
    python serve.py                 # 默认 http://127.0.0.1:8611
    python serve.py --port 8620 --open

依赖：
    走 torch/ultralytics（本机已有）或 onnxruntime。装不上就只服务静态页，
    /api/health 会如实报 model.ready=false，页面自动退回演示数据——
    评委电脑没环境时不会白屏。
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

# 两个仓库的目录结构不一样：
#   主仓        <root>/techline-v3.1.0/{src,models,datasets}
#   技术线仓     <root>/{src,models,datasets}       ← 根目录就是技术线
# 写死 techline-v3.1.0 的话，技术线仓 clone 下来 `python serve.py` 直接 ImportError。
TL = ROOT / "techline-v3.1.0"
if not (TL / "src" / "anxun").is_dir():
    TL = ROOT
sys.path.insert(0, str(TL / "src"))

MAX_BODY = 16 * 1024 * 1024          # 单请求上限，防超大 base64 吃光内存

# 页面里的 A/B/C 与现场素材一一对应：
#   A 3 号车间东侧通道（全员合规）  -> R-02
#   B 2 号车间高处作业平台（未戴帽）-> R-01
#   C 原料库装卸区（多人）          -> R-03
CHAT_SCENE = {"A": "R-02", "B": "R-01", "C": "R-03"}

STATE = {
    "detector": None,
    "ready": False,
    "error": "",
    "note": "",
    "backend": "",
    "selfcheck": None,
    "boot_at": datetime.now(),
}

# ultralytics / CUDA 不是线程安全的：两个请求同时进来会串框。
_LOCK = threading.Lock()


# ============================================================
# 一、模型
# ============================================================

def load_model(prefer: str = "auto", imgsz: int = 640, conf: float = 0.25,
               device: str = "") -> None:
    """加载检测模型。失败不抛——静态页和演示数据仍然要能用。"""
    try:
        from anxun import backend as backend_mod

        det, note, name = backend_mod.build(
            prefer=prefer, imgsz=imgsz, conf=conf, device=device,
            model=str(TL / "models" / "best.pt"),
            person_model=str(TL / "models" / "yolov8n.pt"),
        )
        sc = backend_mod.selfcheck(det)
        STATE.update({"detector": det, "ready": True, "note": note,
                      "backend": name, "selfcheck": sc})
        print(f"[模型] {name} · {note}")
        print(f"[自检] {sc['device']} 实测 {sc['mean_ms']} ms/帧  "
              f"GPU{'已启用' if sc['gpu_active'] else '未启用'}")
    except Exception as e:                        # noqa: BLE001
        STATE["error"] = str(e)
        print(f"[模型] 未加载：{e}")
        print("[模型] 只提供静态页与演示数据；/api/health 会报 model.ready=false")


def _can_equips() -> list[str] | None:
    if not STATE["ready"]:
        return None
    from anxun.detectors import available_equips
    return available_equips(STATE["detector"])


def _inspect(scene: dict, region) -> dict:
    from anxun.pipeline import inspect

    wanted = list(scene.get("equips", ["helmet", "vest"]))
    can = _can_equips()
    kept = [e for e in wanted if e in can] if can is not None else wanted
    with _LOCK:
        out = inspect(scene, region, STATE["detector"], equips=kept)
    return out


# ============================================================
# 二、业务
# ============================================================

def run_scene(scene_id: str) -> dict:
    from anxun.catalog import REGION_MAP, SCENES, SCENE_MAP

    scene = SCENE_MAP.get(scene_id)
    if not scene:
        raise ValueError(f"未知场景 {scene_id}，可用：{[s['scene_id'] for s in SCENES]}")
    if not STATE["ready"]:
        raise RuntimeError("模型未加载：" + (STATE["error"] or "未知原因"))
    region = REGION_MAP[scene["region_id"]]
    out = _inspect(scene, region)
    out["source"] = f"scene:{scene_id}"
    return out


def _looks_like_image(raw: bytes) -> bool:
    """按文件头判断是不是真图片。

    不校验的话，一段随便什么字节会一路走到 cv2.imdecode → None →
    `list index out of range` 的 500，前端只能看到一串英文异常。
    """
    head = raw[:16]
    if head.startswith(b"\xff\xd8\xff"):            # jpeg
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):      # png
        return True
    if head.startswith(b"GIF8"):                   # gif
        return True
    if head.startswith(b"BM"):                     # bmp
        return True
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return True
    return False


def _scene_check(out: dict) -> dict:
    """给上传图加一条「这像不像作业面」的提示。

    模型对着一张光脚草地图也会检出一个 0.41 的 person 框，
    然后一本正经地开「未佩戴安全帽」的工单。这里不改判定结果，
    只把可疑信号显式标出来，让页面能提示「该图疑似非作业全景」。
    """
    persons = out.get("persons") or []
    frame = (out.get("frames") or [{}])[-1]
    fw, fh = frame.get("frame_w") or 0, frame.get("frame_h") or 0
    if not persons or not fw or not fh:
        out["scene_check"] = {"ok": not persons, "reason": "" if persons else "未检出人员框"}
        return out

    area = fw * fh
    boxes = [p["box"] for p in persons]
    avg_ratio = sum((b["x2"] - b["x1"]) * (b["y2"] - b["y1"]) for b in boxes) / len(boxes) / area
    avg_aspect = sum((b["x2"] - b["x1"]) / max(1e-6, b["y2"] - b["y1"]) for b in boxes) / len(boxes)

    # 站姿的人框细长（宽/高≈0.3–0.5）；整片草地/地面被当成"人"时框接近方形，
    # 而且一张图就占掉半屏。两个条件同时成立才提示，避免误伤近距离特写。
    suspect = avg_ratio > 0.40 and avg_aspect > 0.62
    out["scene_check"] = {
        "ok": not suspect,
        "reason": "人员框占画面 {:.0%}、宽高比 {:.2f}，疑似非作业全景".format(avg_ratio, avg_aspect) if suspect else "",
        "avg_person_area_ratio": round(avg_ratio, 4),
        "avg_person_aspect": round(avg_aspect, 3),
    }
    return out


def run_upload(image_b64: str, region_id: str = "A-03") -> dict:
    from anxun.catalog import REGION_MAP, REGIONS

    if not STATE["ready"]:
        raise RuntimeError("模型未加载：" + (STATE["error"] or "未知原因"))
    if "," in image_b64[:100]:                       # 兼容 data URI
        image_b64 = image_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_b64, validate=False)
    except Exception:                                # noqa: BLE001
        raise ValueError("image_base64 不是合法 base64") from None
    if not raw:
        raise ValueError("image_base64 解码后为空")
    if not _looks_like_image(raw):
        raise ValueError("不是有效图片：只支持 jpg / png / webp / bmp")

    region = REGION_MAP.get(region_id) or REGIONS[0]
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tmp.write(raw)
        tmp.close()
        scene = {
            "scene_id": "UPLOAD",
            "region_id": region.region_id,
            "images": [tmp.name],
            "frames": 1,
            "equips": ["helmet", "vest"],
            "title": "上传图片",
            "camera": "UPLOAD",
        }
        out = _inspect(scene, region)
        out["source"] = "upload"
        return _scene_check(out)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def health() -> dict:
    llm = bool(os.environ.get("DEEPSEEK_API_KEY"))
    return {
        "ok": True,
        # mock=true 表示对话仍是前端预置/直连；模型能力单独由 model.ready 报，
        # 两者互不牵连——没显卡的电脑也要能打开页面。
        "mock": not llm,
        "service": "anxun-desk",
        "model": "deepseek-chat" if llm else "anxun-demo",
        "llm_ready": llm,
        "inspect_ready": STATE["ready"],
        "model_info": {
            "ready": STATE["ready"],
            "name": "best.pt",
            "backend": STATE["backend"],
            "note": STATE["note"],
            "selfcheck": STATE["selfcheck"],
            "error": STATE["error"],
        },
        "chat_scene_map": CHAT_SCENE,
        "uptime_s": int((datetime.now() - STATE["boot_at"]).total_seconds()),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AnxunDesk/1.0"

    # ---------------- 路由 ----------------

    def do_GET(self):                                      # noqa: N802
        p = urlparse(self.path).path
        if p in ("/", "/chat", "/chat/", "/index.html"):
            return self._file(ROOT / "chat" / "index.html")
        if p in ("/demo", "/demo/"):
            return self._file(ROOT / "demo" / "index.html")
        if p == "/api/health":
            return self._json(health())
        if p == "/api/scenes":
            return self._json(self._scenes())
        if p.startswith("/assets/"):
            return self._static(p)
        return self._json({"error": "not found", "path": p}, 404)

    def do_POST(self):                                     # noqa: N802
        p = urlparse(self.path).path
        body = self._body()
        if body is None:                                   # 已回 413
            return
        try:
            if p == "/api/inspect":
                if body.get("image_base64"):
                    return self._json(run_upload(
                        body["image_base64"], str(body.get("region_id") or "A-03")))
                return self._json(run_scene(str(body.get("scene_id") or "R-01")))
            if p == "/api/chat":
                return self._proxy_chat(body)
            return self._json({"error": "not found", "path": p}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except RuntimeError as e:
            return self._json({"error": str(e), "hint": "先装 torch 或 onnxruntime，或用 --backend onnx"}, 503)
        except Exception as e:                             # noqa: BLE001
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def do_HEAD(self):                                     # noqa: N802
        """探活/代理预热会用 HEAD。原来没实现，直接 501，看着像服务坏了。"""
        p = urlparse(self.path).path
        target = None
        if p in ("/", "/chat", "/chat/", "/index.html"):
            target = ROOT / "chat" / "index.html"
        elif p in ("/demo", "/demo/"):
            target = ROOT / "demo" / "index.html"
        if target and target.is_file():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            return
        code = 200 if p == "/api/health" else 404
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):                                  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    # ---------------- 实现 ----------------

    @staticmethod
    def _scenes() -> dict:
        try:
            from anxun.catalog import SCENES, public_scene
            items = [public_scene(s) for s in SCENES]
        except Exception:                                  # noqa: BLE001
            items = []
        for s in items:
            s["chat_key"] = next((k for k, v in CHAT_SCENE.items()
                                  if v == s["scene_id"]), "")
        return {"scenes": items, "chat_scene_map": CHAT_SCENE,
                "model_ready": STATE["ready"]}

    def _proxy_chat(self, body: dict) -> None:
        """把对话请求转给 DeepSeek，SSE 原样透传。

        前端 `streamLive()` 走的就是这条路。没有 key 时明确回 503，
        不假装成功——页面看到非 2xx 会自己回落到演示模式。
        """
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            return self._json({
                "error": "未配置 DEEPSEEK_API_KEY",
                "hint": "想在这个服务里跑真实对话：set DEEPSEEK_API_KEY=sk-... 后重启；"
                        "或在页面右上角菜单里直连（key 只存本机浏览器）",
            }, 503)

        payload = {
            "model": body.get("model") or "deepseek-chat",
            "messages": body.get("messages") or [],
            "temperature": body.get("temperature", 0.3),
            "stream": True,
        }
        if body.get("tools"):
            payload["tools"] = body["tools"]
            payload["tool_choice"] = body.get("tool_choice", "auto")

        req = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            upstream = urlopen(req, timeout=120)
        except Exception as e:                             # noqa: BLE001
            return self._json({"error": f"上游连接失败：{e}"}, 502)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in iter(lambda: upstream.read(1024), b""):
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            upstream.close()

    # ---------------- 输出 ----------------

    def _body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json({"error": f"请求体过大（{length} > {MAX_BODY}）"}, 413)
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            # 原来静默返回 {}，于是非法 JSON 会被当成「跑默认场景 R-01」，
            # 看起来像请求成功。改成明确 400。
            self._json({"error": "请求体不是合法 JSON"}, 400)
            return None

    def _static(self, path: str) -> None:
        # 只允许读 assets/ 目录内的文件。原来只判 is_relative_to(ROOT)，
        # 一个 /assets/../serve.py 就能把源码和 42 MB 的 onnx 读走。
        assets = (ROOT / "assets").resolve()
        target = (ROOT / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(assets) or not target.is_file():
            return self._json({"error": "forbidden"}, 403)
        self._file(target)

    def _file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            return self._json({"error": "not found", "path": path.name}, 404)
        raw = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self._send(200, raw, ctype)

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if os.environ.get("ANXUN_VERBOSE"):
            super().log_message(fmt, *args)


def main() -> int:
    # 托管平台（Sites / 容器）只给一个 PORT 环境变量，且要求绑 0.0.0.0。
    # 本机双击启动时没有 PORT，就老实绑回 127.0.0.1——别把服务暴露到局域网。
    deployed = bool(os.environ.get("PORT"))
    ap = argparse.ArgumentParser(description="安巡 Agent 研判台（页面 + 真模型）")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PORT") or 8611))
    ap.add_argument("--host",
                    default=os.environ.get("HOST") or ("0.0.0.0" if deployed else "127.0.0.1"))
    ap.add_argument("--backend", default="auto", choices=("auto", "torch", "onnx"))
    ap.add_argument("--device", default="", help="cpu 强制 CPU；留空自动")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--no-model", action="store_true", help="只服务页面，不加载模型")
    ap.add_argument("--open", action="store_true", help="启动后自动开浏览器")
    args = ap.parse_args()

    if args.open and deployed:
        args.open = False          # 服务器上没有浏览器可开

    if not args.no_model:
        load_model(prefer=args.backend, imgsz=args.imgsz,
                   conf=args.conf, device=args.device)

    httpd = None
    port = args.port
    for p in range(args.port, args.port + 10):
        try:
            httpd = ThreadingHTTPServer((args.host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"{args.port}–{args.port + 9} 端口都被占用，换一个：--port 8620")
        return 2

    url = f"http://{args.host}:{port}"
    print(f"安巡 Agent 研判台  ->  {url}")
    print(f"  模型：{'已加载 ' + STATE['backend'] if STATE['ready'] else '未加载（演示数据）'}")
    print(f"  对话：{'已配置 key，可代理' if os.environ.get('DEEPSEEK_API_KEY') else '演示模式（页面可直连）'}")
    print("  Ctrl+C 退出")
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
