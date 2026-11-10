# -*- coding: utf-8 -*-
"""用 20 页幻灯片 + 中文 TTS 旁白合成参赛视频（MP4 ≤6 分钟 ≤300MB）。

画面与 PPT 逐页一致；旁白按页生成，每页停留时长由该段音频决定。
输出：deliver/制造-上海中侨职业技术大学-张璟瑜-安巡Agent.mp4、deliver/旁白稿.md
"""
from __future__ import annotations

import asyncio
import math
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_subtitles import build_subtitles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliver"
SLIDES = OUT / "slides"
WORK = OUT / ".video_work"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = "zh-CN-YunxiNeural"
RATE = "+12%"
GAP = 0.32  # 每页讲完后的停顿（秒）
SUBTITLES = True  # 烧录硬字幕；置 False 可退回无字幕版本

NARRATION = [
    "安巡 Agent，厂区安全巡检多智能体系统。把摄像头画面，变成可执行的整改工单。",
    "别人做的是告警，我们做的是工单。告警只是一条通知，工单是一个责任。系统由三个人分三条线完成：技术线负责模型与指标，系统线负责判定与研判台，材料线负责提交与答辩。参考来源包括两个公开数据集、安全生产法与两项国家标准，均在页面上单列。",
    "法规要求必须监督从业人员正确佩戴劳动防护用品，但一名安全员要管多个车间，每班巡查只有两次、十五分钟。检查的人一走，帽子就摘了。监控只推一条告警，没有等级、没有时限、没有人负责。页面下方是国务院「人工智能+」行动意见与安全生产法主席令的官方原文截图。",
    "主训练集来自 Chapian ppe v3，采用 CC BY 4.0 授权，两千四百五十一张训练、两百七十二张验证。九类原始标签重映射为五类：人、安全帽、裸头、反光背心、未穿背心。我们剔除了与评测集重名的一百六十五张图像，防止数据泄漏。",
    "第二渠道是一百张独立评测图像，全程不参与训练，也不参与选轮次。四个对外指标全部在它上面测。同源不同集，跨域泛化未验证，这一点我们在局限页主动说明。",
    "知识库分四层：法规、标准、操作和经验。每条法规存原文、不存改写，引用前必须由 law lookup 检索，查不到就写未检索到。因为一条错误的法规引用，足以让整张整改单失去效力。",
    "预处理不是笼统地说做了数据增强。逆光弱光、遮挡、监控距离、安装倾斜，每一种增强都对应训练脚本里注释的一个现场失效模式。",
    "为什么拆成多个 Agent？因为感知、研判、工单的确定性要求完全不同。等级和工单号交给代码，模型只负责理解与表达。我们前后用了四版风险矩阵，最后把它推翻了：按区域历史次数定级，同一张图换个区域，等级就变。",
    "这是全片的骨架。一帧画面走到一张工单，中间要经过四态判定、三道无效性保护、时序聚合、按人数分档、法规映射、工单生成和签署复查。左侧解决判得准，右侧解决落得下。",
    "检测模型、规则引擎、Agent 编排三层解耦。模型没训好也能演示，换模型不动业务，换平台不用重写，同一输入结果可复现。线上托管用 best onnx 对真实图片实算，不是预置回答。",
    "一百张独立评测集上，mAP 零点五为零点八六五四，误报百分之六点一二，漏报百分之四点三五，GPU 单帧十五点零毫秒，四项点估计全部达标。但漏报的百分之九十五置信区间上界是百分之十点七，越过目标线，所以答辩只说点估计达标，不说稳定达标。",
    "火焰检测是语义判断，蒸汽、反光、红色物料都会造成边界模糊，加数据也未必收敛。PPE 检测是存在性判断，目标明确、有国标可依。我们没有放弃视觉能力，换掉的是那个边界说不清的任务。",
    "三个创新点：感知闭环、定级有据、可解释的克制。跨学科视角是安全工程、计算机视觉与管理学 P D C A。技术只是其中一环，真正有价值的是把一次看见，放进企业既有的管理闭环。",
    "分级标准 v1.4 只回答一个问题：这一单多久内必须处理完。确认未佩戴三人以上，A 级，两小时内；一到两人，B 级，二十四小时内；仅待复核，C 级，七天内核实；全合规不出单。线上实测四个场景，同一张图换区域，等级不变。",
    "三十四点八秒单路视频，逐帧触发一百九十五条告警，经连续三帧聚合去重，只剩十三件真正要办的事，降噪百分之九十三点三三。判定覆盖百分之七十六点九二，合规率百分之五十七点一四，待复核与无法判定单列、不进分母。巡检覆盖十六倍是排班假设推演，不是实测，我们单独标注。",
    "主动说六条局限：自采数据零张；评测集只有一百张，每一例约一个百分点；背心类 mAP 约零点六六三，明显更弱；护目镜与手套只留接口；现场素材无真实整改过程；研判台现场需联网。装完美的作品，一戳就破。",
    "隐私上，工人影像不落地、不进提交包；误报信任上，置信度三档、连续三帧、小目标拦截三道保护，宁可转人工也不硬判；责任边界上，系统只做辅助判定，责任人、复查人、验收项一律留空由现场手填。",
    "这是线上研判台真实交互的整屏截图。左侧是真实发出的提问和云端 Agent 的实时回复，右侧四态统计、B 级二十四小时、整改工单和法规依据，全部由规则引擎与 ONNX 模型实算。",
    "三组提示词全部来自线上研判台真实对话截图，覆盖 B 级、A 级和不出单。黑气泡是输入，白气泡是实时回复。等级、时限、工单号都不交给大模型，必须先调 grade risk。右侧是可访问链接与二维码，含完整 sharecode。",
    "下一步先把判定做稳，再把闭环接进企业台账，最后扩到更多装备与多路摄像头。我们没把系统说成已经替企业管好了安全。它现在做到的是：把一次看见，变成一件有人签、有时限、能复查的事。感谢评审。",
]


def log(msg: str) -> None:
    print(msg, flush=True)


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


async def make_voice() -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, text in enumerate(NARRATION, 1):
        mp3 = WORK / f"v{i:02d}.mp3"
        wav = WORK / f"v{i:02d}.wav"
        if not wav.exists():
            await tts_one(text, mp3)
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3),
                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(wav)],
                check=True, capture_output=True,
            )
        wavs.append(wav)
        log(f"  [{i:02d}/20] 旁白 {wav.stat().st_size // 1024} KB")
    return wavs


def wav_duration(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def build_audio(wavs: list[Path]) -> tuple[Path, list[float], float]:
    """按 语音 + 静音 顺序拼接为单个 wav，返回每段的总显示时长。"""
    with wave.open(str(wavs[0]), "rb") as w:
        params = w.getparams()
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
    gap_frames = int(rate * GAP)
    silence = b"\x00" * (gap_frames * width * ch)
    out = WORK / "narration.wav"
    durations = []
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
    total = wav_duration(out)
    return out, durations, total


def build_video(audio: Path, durations: list[float], total: float,
                ass: Path | None) -> Path:
    frames = WORK / "frames.txt"
    lines = []
    for i, d in enumerate(durations, 1):
        png = (SLIDES / f"p{i:02d}.png").resolve().as_posix()
        lines.append(f"file '{png}'")
        lines.append(f"duration {d:.3f}")
    # concat demuxer 要求最后一张图再出现一次，否则最后一页时长不生效
    lines.append(f"file '{(SLIDES / 'p20.png').resolve().as_posix()}'")
    frames.write_text("\n".join(lines) + "\n", encoding="utf-8")

    silent = WORK / "silent.mp4"
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2")
    cwd = None
    if ass and ass.exists():
        # concat 图片序列每页仅 1 帧，必须先补到 25fps 再叠字幕；
        # 否则 libass 只在页起始那一帧渲染，整页会复制无字幕帧。
        # ass 用相对文件名 + cwd，避开 Windows 路径冒号转义。
        vf += f",fps=25,ass={ass.name},format=yuv420p"
        cwd = str(ass.parent)
        log("  已烧录中文字幕（硬字幕，任意播放器可见）")
    else:
        vf += ",format=yuv420p"
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(frames),
        "-vf", vf,
        "-r", "25", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(silent),
    ]
    subprocess.run(cmd, check=True, capture_output=True, cwd=cwd)
    log(f"  无声画面: {silent.stat().st_size / 1048576:.1f} MB")

    out = OUT / "制造-上海中侨职业技术大学-张璟瑜-安巡Agent.mp4"
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-i", str(silent), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def write_script(durations: list[float], total: float) -> None:
    lines = [
        "# 安巡 Agent · 6 分钟视频旁白稿",
        "",
        "> 与 `制造-上海中侨职业技术大学-张璟瑜-安巡Agent.mp4` 逐页对应，画面即 PPT 第 1–20 页。",
        "> 当前音轨由中文 TTS 合成；如需真人录音，按页替换后重新合成即可。",
        f"> 总时长约 {int(total // 60)} 分 {int(total % 60):02d} 秒（官方上限 6 分钟）。",
        "> 视频已烧录中文字幕；外挂字幕：制造-上海中侨职业技术大学-张璟瑜-安巡Agent.srt。",
        "",
        "| 页 | 停留 | 旁白 |",
        "|---|---|---|",
    ]
    t = 0.0
    titles = [
        "封面", "作品背景与说明", "场景痛点", "数据来源一", "数据来源二",
        "知识库构建", "数据预处理", "分析方法选择", "思维导图", "系统架构",
        "模型实测指标", "为什么放弃火焰检测", "创新点与跨学科视角", "结果解读",
        "价值量化", "问题与优化建议", "风险识别与应对", "应用对话界面",
        "提示词示例与链接", "结尾与展望",
    ]
    for i, (text, d) in enumerate(zip(NARRATION, durations), 1):
        mm, ss = int(t // 60), int(t % 60)
        lines.append(f"| {i:02d} {titles[i-1]} | {mm}:{ss:02d} · {d:.1f}s | {text} |")
        t += d
    lines += [
        "",
        "## 录制替换提示",
        "",
        "- 语速平稳，**不要念 PPT**：画面上已有的数字不必逐字重复，讲「为什么」更重要。",
        "- 第 11、14、15、16 页的口径红线：只说「点估计达标」，不说「稳定达标」；",
        "  16× 覆盖率是推演值；等级只讲 A/B/C，不讲颜色与 R 值。",
        "- 第 18 页现场必须联网；建议另备一段连续录屏作为备份。",
        "- 若要真人录音：按页录成 `v01.wav` … `v20.wav` 放进 `deliver/.video_work/`，",
        "  删掉同名 mp3 后重跑 `python tools/build_video.py`。",
        "",
    ]
    (OUT / "旁白稿.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    log("1/5 生成中文旁白…")
    wavs = asyncio.run(make_voice())
    log("2/5 拼接音轨…")
    audio, durations, total = build_audio(wavs)
    log(f"  旁白总长 {total:.1f}s = {int(total // 60)} 分 {int(total % 60):02d} 秒")
    if total > 358:
        raise RuntimeError(f"旁白 {total:.1f}s 超过 6 分钟上限，请精简文案或提高 RATE")
    log("3/5 生成逐句字幕…")
    ass = build_subtitles(NARRATION, durations) if SUBTITLES else None
    log("4/5 合成画面与音轨…")
    out = build_video(audio, durations, total, ass)
    log("5/5 写旁白稿…")
    write_script(durations, total)
    log(f"\n视频: {out}  {out.stat().st_size / 1048576:.2f} MB  {total:.1f}s")
    log(f"旁白稿: {OUT / '旁白稿.md'}")


if __name__ == "__main__":
    main()
