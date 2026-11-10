# -*- coding: utf-8 -*-
"""为演示视频生成与 TTS 旁白逐句对齐的中文字幕（SRT + ASS）。

时间轴来自 edge-tts 的 SentenceBoundary 事件（句级精确，由合成引擎给出），
句内再按次级标点切成适合单行显示的短句，并按字符数比例细分时间。
每页起始偏移由调用方传入的 durations（wav 时长 + GAP）计算，
与 build_video.py 拼音轨的口径完全一致。

产出：
  deliver/制造-上海中侨职业技术大学-张璟瑜-安巡Agent.srt   通用字幕（备用 / 播放器外挂）
  deliver/.video_work/subs.ass          烧录用（带样式，供 ffmpeg ass 滤镜）
  deliver/.video_work/boundaries.json   TTS 边界缓存（离线可复跑）
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliver"
WORK = OUT / ".video_work"
CACHE = WORK / "boundaries.json"
ASS = WORK / "subs.ass"
SRT = OUT / "制造-上海中侨职业技术大学-张璟瑜-安巡Agent.srt"

VOICE = "zh-CN-YunxiNeural"
RATE = "+12%"
GAP = 0.32
MAX_CHARS = 26  # 单行上限，1280px / 28px 字号下留足余量

# 样式：底部居中、微软雅黑、半透明黑底带，只压住页脚，不挡正文卡片
ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,28,&H00FFFFFF,&H00FFFFFF,&H00151515,&H80000000,-1,0,0,0,100,100,0,0,3,1.5,0,2,50,50,14,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_SECONDARY = "，,；;：:、。！？!?"
# 长句无处可断时：优先在连词「前」断，其次在标点「后」断，最后才硬切
_CONJ = "与和及但而并或且则即"
_PUNCT_AFTER = _SECONDARY + "」』）) "


def _hard_split(p: str) -> list[str]:
    out = []
    while len(p) > MAX_CHARS:
        window = p[:MAX_CHARS]
        cut = 0
        for j in range(MAX_CHARS - 1, max(MAX_CHARS - 10, 0), -1):
            if window[j] in _CONJ:
                cut = j
                break
            if window[j] in _PUNCT_AFTER:
                cut = j + 1
                break
        if cut <= 0:
            cut = MAX_CHARS
        out.append(p[:cut])
        p = p[cut:]
    if p:
        out.append(p)
    return out


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _fetch_one(text: str) -> list[dict]:
    """只取边界事件，音频数据丢弃（音频复用已缓存的 wav，保证音画不变）。"""
    for attempt in range(3):
        try:
            c = edge_tts.Communicate(text, VOICE, rate=RATE)
            cues: list[dict] = []
            async for ch in c.stream():
                if ch["type"] == "SentenceBoundary":
                    cues.append({
                        "start": ch["offset"] / 1e7,
                        "end": (ch["offset"] + ch["duration"]) / 1e7,
                        "text": ch["text"],
                    })
            if cues:
                return cues
        except Exception as e:  # noqa: BLE001
            _log(f"    边界重试 {attempt + 1}/3: {type(e).__name__}")
            await asyncio.sleep(1.0)
    return []


async def _fetch_all(narration: list[str]) -> list[list[dict]]:
    result = []
    for i, text in enumerate(narration, 1):
        cues = await _fetch_one(text)
        result.append(cues)
        _log(f"  [{i:02d}/{len(narration)}] 句边界 {len(cues)} 条")
    return result


def load_boundaries(narration: list[str]) -> list[list[dict]]:
    WORK.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) == len(narration):
                _log(f"  复用句边界缓存 {CACHE.name}（{sum(len(x) for x in data)} 条）")
                return data
        except Exception:  # noqa: BLE001
            pass
    _log("  向云端取 TTS 句级时间轴…")
    data = asyncio.run(_fetch_all(narration))
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def split_long(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    """把一句切成 ≤MAX_CHARS 的短句，按字符比例分配区间。"""
    parts = re.findall(r"[^" + _SECONDARY + r"]+[" + _SECONDARY + r"]?", text) or [text]
    chunks: list[str] = []
    buf = ""
    for p in parts:
        if len(p) > MAX_CHARS:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_hard_split(p))
        elif len(buf) + len(p) <= MAX_CHARS:
            buf += p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)

    total_ch = sum(len(c) for c in chunks) or 1
    span = max(end - start, 0.01)
    t = start
    out = []
    for c in chunks:
        d = span * len(c) / total_ch
        s = c.strip(" ，,；;：:、")
        if s:
            out.append((s, t, t + d))
        t += d
    return out


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_subtitles(narration: list[str], durations: list[float]) -> Path | None:
    """返回 ASS 路径；TTS 边界全不可用时返回 None（不烧字幕，视频照常产出）。"""
    boundaries = load_boundaries(narration)
    if not any(boundaries):
        _log("  ⚠ 句边界不可用，本次跳过字幕（不影响视频）")
        return None

    cues: list[tuple[str, float, float]] = []
    offset = 0.0
    for i, (text, dur) in enumerate(zip(narration, durations)):
        speak = max(dur - GAP, 0.5)   # 该页语音实际时长（去掉页末静音）
        page_cues = boundaries[i]
        if not page_cues:
            # 回退：整页按字符比例均分为若干短句
            page_cues = [{"start": 0.0, "end": speak, "text": text}]
        for b in page_cues:
            st = offset + max(0.0, min(b["start"], speak))
            en = offset + min(max(b["end"], st - offset + 0.4), speak)
            if en <= st:
                en = st + 0.4
            cues.extend(split_long(b["text"], st, en))
        offset += dur

    # 防重叠：后一条不得早于前一条结束
    fixed = []
    for txt, st, en in cues:
        if fixed and st < fixed[-1][2]:
            st = fixed[-1][2]
            en = max(en, st + 0.4)
        fixed.append((txt, st, en))
    cues = fixed

    srt_lines = []
    ass_lines = [ASS_HEAD.rstrip("\n")]
    for idx, (txt, st, en) in enumerate(cues, 1):
        srt_lines += [str(idx), f"{_srt_time(st)} --> {_srt_time(en)}", txt, ""]
        ass_lines.append(
            f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Default,,0,0,0,,{txt}"
        )
    SRT.write_text("\n".join(srt_lines), encoding="utf-8")
    ASS.write_text("\n".join(ass_lines) + "\n", encoding="utf-8")
    _log(f"  字幕 {len(cues)} 条 → {SRT.name} / {ASS.name}")
    return ASS


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_video

    wavs = [WORK / f"v{i:02d}.wav" for i in range(1, 21)]
    durs = [build_video.wav_duration(p) + GAP for p in wavs]
    build_subtitles(build_video.NARRATION, durs)
