# -*- coding: utf-8 -*-
"""按 21 页新版 PPT + 简明正式版讲解稿，生成带硬字幕的参赛视频。

与旧 `build_video.py`（20 页）完全隔离：
- 页面图：deliver/slides_v21/p01.png … p21.png（由 演示文稿1.pptx 逐页导出）
- 旁白：deliver/视频讲解稿_21页_简明版.md 的 21 段正文（解析得到，不另维护副本）
- 工作区：deliver/.video_work/v21/（避免复用旧版 v01…v20.wav 与句边界缓存）
- 输出：deliver/制造-上海中侨职业技术大学-张璟瑜-安巡Agent_21页版.{mp4,srt}

字幕复用 make_subtitles 的 edge-tts SentenceBoundary 逐句对齐 + ASS 烧录逻辑，
仅在运行时把该模块的路径常量改指向 v21 工作区，不修改旧模块本身。
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_subtitles as ms  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliver"
SLIDES = OUT / "slides_v21"
WORK = OUT / ".video_work" / "v21"
SCRIPT_MD = OUT / "视频讲解稿_21页_简明版.md"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VOICE = "zh-CN-YunxiNeural"
RATE = "+12%"
GAP = 0.32          # 每页讲完后的停顿（秒）
N_PAGES = 21
MAX_TOTAL = 358.0   # 官方上限 6 分钟，留 2 秒缓冲

BASE = "制造-上海中侨职业技术大学-张璟瑜-安巡Agent_21页版"
MP4 = OUT / f"{BASE}.mp4"
SRT = OUT / f"{BASE}.srt"
TIMELINE = OUT / "视频时间轴_21页.md"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_narration() -> list[str]:
    """从讲解稿 markdown 抽取 21 段正文，保证单一数据源。"""
    md = SCRIPT_MD.read_text(encoding="utf-8")
    body = md.split("## 逐页旁白", 1)[1].split("## 术语白话对照", 1)[0]
    parts = re.split(r"^### P(\d{2})[^\n]*$", body, flags=re.M)
    pages: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        text = " ".join(parts[i + 1].split())
        if text:
            pages[int(parts[i])] = text
    missing = [i for i in range(1, N_PAGES + 1) if i not in pages]
    if missing:
        raise RuntimeError(f"讲解稿缺页：{missing}")
    arr = [pages[i] for i in range(1, N_PAGES + 1)]
    log(f"  解析讲解稿：{len(arr)} 段，共 {sum(len(x) for x in arr)} 字")
    return arr


def _proxy() -> str | None:
    return os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or None


# edge-tts 的边界抓取在 make_subtitles 内部直接实例化 Communicate（不传 proxy）。
# 这里做一次全局包装，保证音频与字幕两条链路都走当前会话的代理端口。
_OrigCommunicate = edge_tts.Communicate


class _ProxyCommunicate(_OrigCommunicate):
    def __init__(self, *args, **kwargs):
        p = _proxy()
        if p and not kwargs.get("proxy"):
            kwargs["proxy"] = p
        super().__init__(*args, **kwargs)


edge_tts.Communicate = _ProxyCommunicate


async def tts_one(text: str, dst: Path) -> None:
    for attempt in range(3):
        try:
            c = edge_tts.Communicate(text, VOICE, rate=RATE)
            await c.save(str(dst))
            if dst.exists() and dst.stat().st_size > 2000:
                return
        except Exception as e:  # noqa: BLE001
            log(f"    TTS 重试 {attempt + 1}/3: {type(e).__name__}")
            await asyncio.sleep(1.2)
    raise RuntimeError(f"TTS 失败: {dst.name}")


async def make_voice(narration: list[str]) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, text in enumerate(narration, 1):
        mp3 = WORK / f"v{i:02d}.mp3"
        wav = WORK / f"v{i:02d}.wav"
        if not wav.exists() or wav.stat().st_size < 2000:
            await tts_one(text, mp3)
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3),
                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(wav)],
                check=True, capture_output=True,
            )
        wavs.append(wav)
        log(f"  [{i:02d}/{N_PAGES}] 旁白 {wav.stat().st_size // 1024} KB")
    return wavs


def wav_duration(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def build_audio(wavs: list[Path]) -> tuple[Path, list[float], float]:
    with wave.open(str(wavs[0]), "rb") as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
    silence = b"\x00" * (int(rate * GAP) * width * ch)
    out = WORK / "narration.wav"
    durations: list[float] = []
    with wave.open(str(out), "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(width)
        o.setframerate(rate)
        for p in wavs:
            with wave.open(str(p), "rb") as w:
                data = w.readframes(w.getnframes())
                d = w.getnframes() / w.getframerate()
            o.writeframes(data)
            o.writeframes(silence)
            durations.append(d + GAP)
    return out, durations, wav_duration(out)


def build_ass(narration: list[str], durations: list[float]) -> Path | None:
    # 运行时重定向 make_subtitles 的产物路径，旧版 boundaries.json / subs.ass 不受影响
    ms.WORK = WORK
    ms.CACHE = WORK / "boundaries.json"
    ms.ASS = WORK / "subs.ass"
    ms.SRT = SRT
    ms.VOICE = VOICE
    ms.RATE = RATE
    ms.GAP = GAP
    ass = ms.build_subtitles(narration, durations)
    if ass and ass.exists():
        # 新版 PPT 的正文一直排到画面最底边，字幕带调薄并贴底，尽量少压正文
        css = ass.read_text(encoding="utf-8")
        css = css.replace("Microsoft YaHei,28,", "Microsoft YaHei,26,")
        css = css.replace(",2,50,50,14,1", ",2,50,50,8,1")
        ass.write_text(css, encoding="utf-8")
        log("  字幕样式：26px / 贴底 8px（减少对页脚小字的遮挡）")
    return ass


def build_video(durations: list[float], ass: Path | None) -> Path:
    frames = WORK / "frames.txt"
    lines: list[str] = []
    for i, d in enumerate(durations, 1):
        png = (SLIDES / f"p{i:02d}.png").resolve().as_posix()
        lines.append(f"file '{png}'")
        lines.append(f"duration {d:.3f}")
    lines.append(f"file '{(SLIDES / f'p{N_PAGES:02d}.png').resolve().as_posix()}'")
    frames.write_text("\n".join(lines) + "\n", encoding="utf-8")

    silent = WORK / "silent.mp4"
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2")
    cwd = None
    if ass and ass.exists():
        # concat 图片序列每页仅 1 帧，必须先补到 25fps 再叠字幕，
        # 否则 libass 只在页起始那一帧渲染，整页会复制无字幕帧。
        vf += f",fps=25,ass={ass.name},format=yuv420p"
        cwd = str(ass.parent)
        log("  已烧录中文字幕（硬字幕，任意播放器可见）")
    else:
        vf += ",format=yuv420p"
        log("  ⚠ 未烧录字幕")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(frames),
         "-vf", vf, "-r", "25", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(silent)],
        check=True, capture_output=True, cwd=cwd,
    )
    log(f"  无声画面: {silent.stat().st_size / 1048576:.1f} MB")

    audio = WORK / "narration.wav"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-i", str(silent), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-shortest", "-movflags", "+faststart", str(MP4)],
        check=True, capture_output=True,
    )
    return MP4


def write_timeline(narration: list[str], durations: list[float], total: float) -> None:
    lines = [
        "# 安巡 Agent · 21 页视频实测时间轴",
        "",
        f"- 画面：`演示文稿1.pptx`（21 页 · 16:9）逐页导出，1920×1080 → 1280×720",
        f"- 旁白：`视频讲解稿_21页_简明版.md`（TTS zh-CN-YunxiNeural · rate {RATE}）",
        f"- 字幕：edge-tts 句边界对齐，ASS 硬字幕烧录；外挂 `{SRT.name}`",
        f"- 实测总时长：**{int(total // 60)} 分 {total % 60:04.1f} 秒**（官方上限 6 分钟）",
        "",
        "| 页 | 起始 | 停留 | 旁白首句 |",
        "|---|---|---|---|",
    ]
    t = 0.0
    for i, (text, d) in enumerate(zip(narration, durations), 1):
        mm, ss = int(t // 60), t % 60
        head = re.split(r"[。；]", text, maxsplit=1)[0][:34]
        lines.append(f"| P{i:02d} | {mm:02d}:{ss:04.1f} | {d:.1f}s | {head} |")
        t += d
    lines += [
        "",
        "## 重跑提示",
        "",
        "- 逐页 TTS 与句边界缓存均在 `deliver/.video_work/v21/`，重跑会复用。",
        "- 更换讲解稿后需删除 `v*.wav` 与 `boundaries.json` 再跑，避免音字错位。",
        "- 若要真人录音：按页放 `v01.wav` … `v21.wav` 进上述目录后重跑。",
        "",
    ]
    TIMELINE.write_text("\n".join(lines), encoding="utf-8")


def probe(path: Path) -> None:
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    for line in r.stderr.splitlines():
        if "Duration:" in line or "Stream #" in line:
            log("  " + line.strip())


def main() -> None:
    narration = load_narration()
    for i in range(1, N_PAGES + 1):
        if not (SLIDES / f"p{i:02d}.png").exists():
            raise RuntimeError(f"缺页面图 p{i:02d}.png")

    log("1/5 生成 21 段中文旁白…")
    wavs = asyncio.run(make_voice(narration))
    log("2/5 拼接音轨…")
    _, durations, total = build_audio(wavs)
    log(f"  旁白总长 {total:.1f}s = {int(total // 60)} 分 {total % 60:04.1f} 秒")
    if total > MAX_TOTAL:
        raise RuntimeError(
            f"旁白 {total:.1f}s 超过 {MAX_TOTAL:.0f}s 上限："
            "请精简文案、把 GAP 降到 0.20，或把 RATE 提到 +14% 后删 v*.wav 重跑"
        )

    log("3/5 生成逐句字幕…")
    ass = build_ass(narration, durations)
    if ass is None:
        raise RuntimeError("句边界全部不可用，无法生成字幕（本次要求必须有字幕）")

    log("4/5 合成画面与音轨…")
    out = build_video(durations, ass)
    log("5/5 写实测时间轴…")
    write_timeline(narration, durations, total)
    probe(out)
    log(f"\n视频: {out}  {out.stat().st_size / 1048576:.2f} MB  {total:.1f}s")
    log(f"字幕: {SRT}")
    log(f"时间轴: {TIMELINE}")


if __name__ == "__main__":
    main()
