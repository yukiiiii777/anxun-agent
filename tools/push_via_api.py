#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub Git Data API 把本地仓库同步到远程。

为什么需要这个脚本
------------------
本机网络环境无法直连 github.com:443（git push 不通），但 api.github.com 可访问。
所以用 REST API 直接写 blob / tree / commit，效果等同于 git push。

行为
----
- **增量**：比对本地索引 blob sha 与远程 tree，只上传有差异的文件，
  其余靠 base_tree 继承（仓库含 43MB best.onnx / 21MB best.pt，
  全量重传会被 GitHub Blobs API 以 422 拒绝）
- 幂等：可以反复运行，无差异时直接跳过
- 不删除远程独有文件，避免覆盖队友的东西
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
def index_blobs(root: str) -> dict[str, str]:
    """返回 {path: blob_sha}，直接读 .git 索引，不把大权重读进内存。"""
    out = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=root)
    blobs: dict[str, str] = {}
    for rec in out.decode("utf-8").split("\0"):
        if not rec.strip():
            continue
        meta, path = rec.split("\t", 1)
        blobs[path] = meta.split()[1]
    return blobs


def read_blob(root: str, path: str) -> bytes:
    """读索引里的文件内容（换行已按 .gitattributes 规范化）。"""
    try:
        return subprocess.check_output(["git", "cat-file", "-p", f":{path}"], cwd=root)
    except subprocess.CalledProcessError:
        with open(os.path.join(root, path), "rb") as f:
            return f.read()


def remote_blobs(call, api: str, tree_sha: str) -> dict[str, str]:
    """远程 tree 里已有的 {path: blob_sha}。"""
    tree = call("GET", f"{api}/git/trees/{tree_sha}?recursive=1")
    return {t["path"]: t["sha"] for t in tree["tree"] if t["type"] == "blob"}


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

    local = index_blobs(root)
    if not local:
        sys.exit("本地索引为空，先 git add")
    print(f"仓库   {owner}/{repo}   分支 {args.branch}")
    print(f"索引   {len(local)} 个文件   代理 {args.proxy or '（未使用）'}\n")

    # 1) 取远程当前头部；空仓库则先建一个种子 commit
    base_commit = base_tree = None
    try:
        ref = call("GET", f"{api}/git/ref/heads/{args.branch}")
        base_commit = ref["object"]["sha"]
        base_tree = call("GET", f"{api}/git/commits/{base_commit}")["tree"]["sha"]
        print(f"基于远程头部 {base_commit[:7]} 追加\n")
    except RuntimeError:
        seed_path = "README.md" if "README.md" in local else next(iter(local))
        print(f"远程仓库为空，先用 {seed_path} 建立初始 commit…")
        res = call("PUT", f"{api}/contents/{seed_path}", {
            "message": "chore: 初始化仓库",
            "content": base64.b64encode(read_blob(root, seed_path)).decode("ascii"),
            "branch": args.branch,
        })
        base_commit = res["commit"]["sha"]
        base_tree = res["commit"]["tree"]["sha"]
        print(f"  初始 commit {base_commit[:7]}\n")

    # 2) 只上传与远程 blob sha 不同的文件。
    #    GitHub Blobs API 对超大 content 返回 422（仓库里的 43MB best.onnx
    #    就过不去），全量重传既慢又必然失败；其余文件靠 base_tree 继承。
    remote = remote_blobs(call, api, base_tree)
    changed = [p for p, sha in local.items() if remote.get(p) != sha]
    print(f"远程   {len(remote)} 个文件   差异 {len(changed)} 个")
    if not changed:
        print("远程已与本地索引一致，无需推送。")
        return 0

    MAX_API_BLOB = 20 * 1024 * 1024
    too_big = []
    for p in changed:
        try:
            if os.path.getsize(os.path.join(root, p.replace("/", os.sep))) > MAX_API_BLOB:
                too_big.append(p)
        except OSError:
            pass
    if too_big:
        sys.exit("以下改动文件超过 Blobs API 单次上限，需走别的通道：\n  "
                 + "\n  ".join(too_big))

    def upload(path: str):
        raw = read_blob(root, path)
        sha = call("POST", f"{api}/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64",
        })["sha"]
        return path, sha, len(raw)

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (path, sha, size) in enumerate(pool.map(upload, changed), 1):
            results.append((path, sha))
            print(f"  [{i:>2}/{len(changed)}] {size:>8,} B  {path}")

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
