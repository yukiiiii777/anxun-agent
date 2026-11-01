# -*- coding: utf-8 -*-
"""
本地网页服务
============

纯标准库 http.server，不装 FastAPI / Flask。两个接口：

    GET  /api/scenes          场景列表
    GET  /api/run?scene=A     跑一个场景（all = 三个都跑）
    POST /api/run {"scene":"B"}

页面在 `web/index.html`，打开 127.0.0.1:8611 就能演示整条链路。
这个页面就是为了截进 PPT 第 10–13 页设计的：一屏能看到 ②→③→④ 的交接。
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .orchestrator import Orchestrator
from .scenarios import SCENE_KEYS, SCENES

WEB_DIR = Path(__file__).resolve().parent / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "AnxunAgent/1.0"

    # ---------------- 路由 ----------------

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            self._file(WEB_DIR / "index.html")
        elif path == "/api/scenes":
            self._json(self._scenes())
        elif path == "/api/run":
            scene = self._query_scene(query)
            self._json(self._run(scene))
        elif path == "/api/health":
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path, _, _ = self.path.partition("?")
        if path != "/api/run":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}
        self._json(self._run(str(body.get("scene", "A"))))

    # ---------------- 业务 ----------------

    @staticmethod
    def _scenes() -> dict:
        return {
            "scenes": [
                {
                    "key": k,
                    "title": SCENES[k]["title"],
                    "camera": SCENES[k]["camera"],
                    "subject": SCENES[k]["subject"],
                }
                for k in SCENE_KEYS
            ]
        }

    @staticmethod
    def _run(scene: str) -> dict:
        orch = Orchestrator()
        if scene.lower() == "all":
            return orch.run_all()
        return {"mode": "one", "run": orch.run(scene, now=None)}

    @staticmethod
    def _query_scene(query: str) -> str:
        for part in query.split("&"):
            k, _, v = part.partition("=")
            if k == "scene" and v:
                return v
        return "A"

    # ---------------- 输出 ----------------

    def _file(self, path: Path) -> None:
        if not path.exists():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, path.read_bytes(), "text/html; charset=utf-8")

    def _json(self, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return  # 安静点，别把终端刷满


def serve(port: int = 8611, open_browser: bool = True) -> None:
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"{port}–{port + 9} 端口都被占用，换个端口：--port 8620")

    url = f"http://127.0.0.1:{port}"
    print(f"安巡 Agent 本地演示：{url}")
    print("  GET  /api/scenes        场景列表")
    print("  GET  /api/run?scene=A   跑一个场景（all = 全跑）")
    print("  Ctrl+C 退出")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
