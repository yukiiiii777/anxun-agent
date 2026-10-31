#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub Git Data API 把本地仓库同步到远程。

为什么需要这个脚本
------------------
本机网络环境无法直连 github.com:443（git push 不通），但 api.github.com 可访问。
所以用 REST API 直接写 blob / tree / commit，效果等同于 git push。

行为
----
- 把 .git 索引里的**全部文件**上传为一个新 commit，追加到远程分支头部
- 幂等：可以反复运行，每次都会把本地内容镜像上去
- 不依赖第三方库，只用标准库

用法
----
    python tools/push_via_api.py                 # 从 git remote 自动解析 owner/repo
    python tools/push_via_api.py --branch dev    # 指定分支
    python tools/push_via_api.py --proxy http://127.0.0.1:51094

前置条件
--------
- 已安装并登录 GitHub CLI（`gh auth login`），脚本用 `gh auth token` 取凭证
- 远程仓库已存在（可用 `gh repo create` 创建）

注意
----
本脚本创建的 commit 作者是 token 对应的账号，与本机 git config 无关。
如果只是本地开发用 git，远程同步用本脚本，两边内容一致但 commit 历史独立。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_ROOT = "https://api.github.com"


# ---------------------------------------------------------------- 基础设施
def run(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd).decode("utf-8").strip()


def repo_root() -> str:
    return run(["git", "rev-parse", "--show-toplevel"])


def parse_remote(root: str) -> tuple[str, str]:
    """从 origin 的 URL 解析 owner/repo。"""
    url = run(["git", "remote", "get-url", "origin"], cwd=root)
    m = re.search(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"无法从远程地址解析 owner/repo：{url}")
    return m.group(1), m.group(2)


def make_caller(token: str, proxy: str | None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    opener = urllib.request.build_opener(*handlers)

    def call(method: str, url: str, data: dict | None = None, retries: int = 3):
        body = json.dumps(data).encode("utf-8") if data is not None else None
        last = ""
        for _ in range(retries):
            try:
                req = urllib.request.Request(url, data=body, method=method)
                req.add_header("Authorization", f"Bearer {token}")
                req.add_header("Accept", "application/vnd.github+json")
                req.add_header("X-GitHub-Api-Version", "2022-11-28")
                if body is not None:
                    req.add_header("Content-Type", "application/json")
                with opener.open(req, timeout=120) as r:
                    return json.loads(r.read().decode("utf-8") or "{}")
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:400]
                if e.code in (200, 201):
                    return {}
                last = f"HTTP {e.code}: {detail}"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
        raise RuntimeError(f"{method} {url} 失败 -> {last}")

    return call


# ---------------------------------------------------------------- 文件读取
def staged_files(root: str) -> dict[str, bytes]:
    """读取 .git 索引中的文件内容（换行已按 .gitattributes 规范化）。"""
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    paths = [p for p in out.decode("utf-8").split("\0") if p]
    files: dict[str, bytes] = {}
    for p in paths:
        try:
            files[p] = subprocess.check_output(
                ["git", "cat-file", "-p", f":{p}"], cwd=root
            )
        except subprocess.CalledProcessError:
            with open(os.path.join(root, p), "rb") as f:
                files[p] = f.read()
    return files


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="用 GitHub Git Data API 同步本地仓库")
    ap.add_argument("--branch", default="main", help="目标分支（默认 main）")
    ap.add_argument("--message", default=None, help="commit message（默认取本地最新 commit）")
    ap.add_argument("--proxy", default=os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"),
                    help="HTTP 代理，默认读 https_proxy 环境变量")
    args = ap.parse_args()

    if not shutil.which("gh"):
        sys.exit("需要 GitHub CLI：https://cli.github.com/")
    token = run(["gh", "auth", "token"])

    root = repo_root()
    owner, repo = parse_remote(root)
    api = f"{API_ROOT}/repos/{owner}/{repo}"
    call = make_caller(token, args.proxy)

    message = args.message
    if not message:
        try:
            message = run(["git", "log", "-1", "--pretty=%B"], cwd=root)
        except subprocess.CalledProcessError:
            message = "chore: 同步仓库"

    files = staged_files(root)
    if not files:
        sys.exit("本地索引为空，先 git add")
    print(f"仓库   {owner}/{repo}   分支 {args.branch}")
    print(f"文件   {len(files)} 个   代理 {args.proxy or '（未使用）'}\n")

    # 1) 取远程当前头部；空仓库则先建一个种子 commit
    base_commit = base_tree = None
    try:
        ref = call("GET", f"{api}/git/ref/heads/{args.branch}")
        base_commit = ref["object"]["sha"]
        base_tree = call("GET", f"{api}/git/commits/{base_commit}")["tree"]["sha"]
        print(f"基于远程头部 {base_commit[:7]} 追加\n")
    except RuntimeError:
        seed_path = "README.md" if "README.md" in files else next(iter(files))
        print(f"远程仓库为空，先用 {seed_path} 建立初始 commit…")
        res = call("PUT", f"{api}/contents/{seed_path}", {
            "message": "chore: 初始化仓库",
            "content": base64.b64encode(files[seed_path]).decode("ascii"),
            "branch": args.branch,
        })
        base_commit = res["commit"]["sha"]
        base_tree = res["commit"]["tree"]["sha"]
        print(f"  初始 commit {base_commit[:7]}\n")

    # 2) 上传 blob
    def upload(item):
        path, raw = item
        sha = call("POST", f"{api}/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64",
        })["sha"]
        return path, sha, len(raw)

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (path, sha, size) in enumerate(pool.map(upload, files.items()), 1):
            results.append((path, sha))
            print(f"  [{i:>2}/{len(files)}] {size:>8,} B  {path}")

    # 3) 建 tree
    tree = call("POST", f"{api}/git/trees", {
        "base_tree": base_tree,
        "tree": [
            {"path": p, "mode": "100644", "type": "blob", "sha": s}
            for p, s in results
        ],
    })

    # 4) 建 commit
    commit = call("POST", f"{api}/git/commits", {
        "message": message,
        "tree": tree["sha"],
        "parents": [base_commit],
    })

    # 5) 移动分支
    call("PATCH", f"{api}/git/refs/heads/{args.branch}", {
        "sha": commit["sha"], "force": True,
    })

    print(f"\n完成  https://github.com/{owner}/{repo}/tree/{args.branch}")
    print(f"      commit {commit['sha'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
