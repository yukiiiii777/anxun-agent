# -*- coding: utf-8 -*-
"""生成 20 页参赛幻灯片：HTML -> Chrome 截图 -> PPTX。

一次生成同时供 PPT 与视频使用，保证画面一致。
口径：安巡风险分级标准 v1.4 / techline-v3.1.0 实测数据。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliver"
SLIDES = OUT / "slides"
ASSETS = OUT / "assets"
def _find_browser() -> str:
    """找一个可用的 Chromium 内核浏览器：Chrome 优先，其次 Edge。

    写死 Chrome 路径在只装了 Edge 的机器上会直接失败（截图静默不出文件）。
    可用 CHROME_PATH 环境变量强制指定。
    """
    cands = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    return "chrome"


CHROME = _find_browser()
W, H = 1280, 720

CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1280px;height:720px;overflow:hidden}
body{font-family:"Microsoft YaHei","微软雅黑",sans-serif;background:#F5F7FA;color:#0F2740;-webkit-font-smoothing:antialiased}
.slide{width:1280px;height:720px;position:relative;background:#F5F7FA;padding:44px 60px 46px}
.slide:before{content:"";position:absolute;left:0;top:0;width:100%;height:6px;background:var(--accent)}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.chapter{font-size:13px;letter-spacing:2px;color:var(--accent);font-weight:700;display:flex;align-items:center;gap:9px}
.chapter i{display:block;width:9px;height:9px;border-radius:50%;background:var(--accent)}
.brand{font-size:12px;color:#8996A5;letter-spacing:.5px}
h1{font-size:36px;line-height:1.24;letter-spacing:-.5px;font-weight:800;color:#0F2740}
.sub{font-size:15px;color:#66788B;margin-top:8px;line-height:1.6}
.rule{height:1px;background:#E1E7EE;margin:20px 0 22px}
.foot{position:absolute;left:60px;right:60px;bottom:18px;display:flex;justify-content:space-between;
      font-size:11px;color:#9AA7B5;border-top:1px solid #E6EBF1;padding-top:10px}
.body{position:relative;z-index:1}
/* ---- 组件 ---- */
.row{display:flex;gap:16px}.col{flex:1;min-width:0}
.card{background:#fff;border:1px solid #E4EAF1;border-radius:12px;padding:20px 22px;
      box-shadow:0 2px 10px rgba(15,39,64,.035)}
.card h3{font-size:17px;font-weight:800;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.card h3 .n{display:inline-flex;width:24px;height:24px;border-radius:6px;background:var(--accent);
      color:#fff;font-size:12px;align-items:center;justify-content:center;font-weight:700;flex:none}
.card p{font-size:13.5px;line-height:1.75;color:#44586C}
.card ul{margin:8px 0 0 18px}.card li{font-size:13.5px;line-height:1.85;color:#44586C}
.card .small{font-size:12px;color:#7C8B9B;line-height:1.7;margin-top:8px}
.kpi{background:#fff;border:1px solid #E4EAF1;border-radius:12px;padding:15px 18px;text-align:center}
.kpi .v{font-size:38px;font-weight:800;color:var(--accent);line-height:1.1;letter-spacing:-1px}
.kpi .v.ok{color:#2E7D5B}.kpi .v.warn{color:#C98A16}
.kpi .l{font-size:12.5px;color:#5B6D80;margin-top:8px;font-weight:600}
.kpi .t{font-size:11px;color:#9AA7B5;margin-top:5px}
.tag{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11.5px;font-weight:700;
     background:#EAF1F8;color:#2C5B84;margin-right:6px}
.tag.a{background:#FBE9E6;color:#B43C32}.tag.b{background:#FDF1DC;color:#A2720F}
.tag.c{background:#E9F3ED;color:#2E7D5B}.tag.mute{background:#EDF0F4;color:#6B7A8C}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff;border-radius:10px;overflow:hidden}
th{background:#EDF2F7;color:#3D5064;font-weight:700;text-align:left;padding:7px 11px;font-size:12.5px}
td{padding:7px 11px;border-top:1px solid #EDF1F5;color:#44586C;line-height:1.5}
tr.hl td{background:#FFF6EC;font-weight:700;color:#0F2740}
.note{background:#FFF8EC;border-left:3px solid #D99A2B;padding:11px 16px;border-radius:0 8px 8px 0;
      font-size:12.5px;color:#7A5C1C;line-height:1.65;margin-top:14px}
.note.blue{background:#EEF5FB;border-color:#3A7CA8;color:#2B5673}
.note.red{background:#FDF0EE;border-color:#C4453C;color:#8E3A32}
.flow{display:flex;align-items:center;gap:8px}
.step{background:#fff;border:1px solid #DDE5ED;border-radius:9px;padding:12px 10px;text-align:center;flex:1}
.step b{display:block;font-size:13.5px;color:#0F2740}.step span{font-size:11px;color:#8695A5}
.arrow{color:var(--accent);font-size:19px;font-weight:800;flex:none}
.bar{height:9px;background:#E8EDF3;border-radius:6px;overflow:hidden;margin-top:7px}
.bar i{display:block;height:100%;background:var(--accent);border-radius:6px}
.mono{font-family:Consolas,"Courier New",monospace;font-size:12px;background:#F2F5F8;
      border:1px solid #E3E9F0;border-radius:6px;padding:9px 11px;color:#33475C;line-height:1.6}
.big{font-size:19px;font-weight:800;line-height:1.6}
.center{text-align:center}
.lead{font-size:15px;line-height:1.85;color:#44586C}
.hl{color:var(--accent);font-weight:800}
.dim{color:#8996A5}
.imgframe{background:#fff;border:1px solid #E1E7EE;border-radius:10px;padding:8px;display:flex;
          align-items:center;justify-content:center;overflow:hidden}
.imgframe img{max-width:100%;max-height:100%;display:block;border-radius:5px}
.smalltxt{font-size:11.5px;color:#8996A5;line-height:1.6}
.card.compact{padding:14px 18px}
.card.compact li{font-size:12px;line-height:1.6;margin-bottom:3px}
.card.compact .note{padding:8px 12px;font-size:11.5px;margin-top:9px}
.split{display:flex;gap:18px;height:100%}
.pill{padding:5px 12px;background:#fff;border:1px solid #DDE5ED;border-radius:20px;font-size:12px;color:#4A5E72}
.cover{background:#0F2740;color:#fff;padding:0}
.cover:before{display:none}
.cover .inner{position:absolute;inset:0;padding:96px 88px;display:flex;flex-direction:column;justify-content:center}
.cover .grid{position:absolute;inset:0;opacity:.09;
  background-image:linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px);
  background-size:52px 52px}
.cover h1{color:#fff;font-size:66px;letter-spacing:2px;line-height:1.15}
.cover .en{font-size:16px;letter-spacing:5px;color:#7FA8C9;margin-top:14px;text-transform:uppercase}
.cover .line{width:76px;height:5px;background:#E28B4A;margin:32px 0}
.cover .desc{font-size:20px;color:#C8D7E5;line-height:1.9}
.cover .meta{position:absolute;left:88px;bottom:64px;font-size:14px;color:#8FA9BF;line-height:2}
.cover .badge{position:absolute;right:88px;top:96px;border:1px solid #3C6285;border-radius:10px;
  padding:14px 20px;font-size:13px;color:#A9C6DE;line-height:1.9;text-align:right}
.quote{font-size:27px;font-weight:800;line-height:1.65;color:#0F2740}
.quote em{font-style:normal;color:var(--accent)}
.svgwrap{display:flex;align-items:center;justify-content:center;height:100%}
"""


def page(idx: int, chapter: str, title: str, sub: str, body: str, accent: str) -> str:
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="style.css"><style>:root{{--accent:{accent}}}</style></head>
<body><div class="slide">
  <div class="head"><div class="chapter"><i></i>{chapter}</div>
    <div class="brand">安巡 Agent · 第二届全国人工智能应用创新大赛 · 通用赛道 · 制造领域</div></div>
  <h1>{title}</h1><div class="sub">{sub}</div>
  <div class="rule"></div>
  <div class="body">{body}</div>
  <div class="foot"><span>上海中侨职业技术大学 · 人工智能学院　|　本科生组</span><span>{idx:02d} / 20</span></div>
</div><div id="diag" style="display:none"></div>
<script>(function(){{var bad=[];document.querySelectorAll('.card,.body,.kpi').forEach(function(e){{
  if(e.scrollHeight>e.clientHeight+2) bad.push((e.className||'?').split(' ')[0]+' '+e.scrollHeight+'/'+e.clientHeight);}});
  var s=document.querySelector('.slide');if(s&&s.scrollHeight>s.clientHeight+2)bad.push('SLIDE '+s.scrollHeight+'/'+s.clientHeight);
  document.getElementById('diag').textContent='DIAG:'+(bad.length?bad.join(' | '):'OK');}})();</script>
</body></html>"""


C = {
    1: "#0F2740", 2: "#1B6E8C", 3: "#5E4B9B",
    4: "#C25E2A", 5: "#2E7D5B", 6: "#B03A48",
}
CH = {
    1: "第 1 章 · 作品背景与说明", 2: "第 2 章 · 数据收集与处理",
    3: "第 3 章 · 分析过程", 4: "第 4 章 · 创新性与独特视角",
    5: "第 5 章 · 结果解释与建议", 6: "第 6 章 · 应用结果呈现",
}

# ---------------------------------------------------------------- 20 页内容
COVER = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="style.css"></head><body>
<div class="slide cover"><div class="grid"></div><div class="inner">
  <div class="en">Multi-Agent Safety Inspection System</div>
  <h1>安巡 Agent</h1>
  <div class="line"></div>
  <div class="desc">厂区安全巡检多智能体系统<br>把摄像头画面变成<span style="color:#F0A468;font-weight:800">可执行的整改工单</span></div>
</div>
<div class="badge">第二届全国人工智能应用创新大赛<br><b style="color:#DCE9F4">通用赛道 · 制造领域 · 本科生组</b></div>
<div class="meta">上海中侨职业技术大学　人工智能学院<br>3 名队员 + 1 名指导老师　·　2026 年 11 月</div>
</div></body></html>"""

P02 = """
<div class="row" style="height:118px">
  <div class="card" style="flex:1.5;background:#0F2740;border-color:#0F2740">
    <div style="font-size:12px;color:#8FB0CC;letter-spacing:2px;margin-bottom:8px">一句话定位</div>
    <div style="font-size:20px;color:#fff;font-weight:800;line-height:1.5">别人做的是告警，我们做的是工单。<br>
      <span style="color:#F0A468">告警是一条通知，工单是一个责任。</span></div>
  </div>
  <div class="card" style="flex:1">
    <h3>解决什么</h3>
    <p>摄像头已经装好了，但「看到未戴安全帽」之后，没人负责把它变成一张限期整改、可签署、可追责的通知单。</p>
  </div>
</div>
<div class="row" style="margin-top:16px;height:170px">
  <div class="card col"><h3><span class="n">1</span>技术线</h3><p>五类 PPE 权重训练、评测集构建、指标实测与误差归因；提供 ONNX 推理服务。</p><div class="small">交付：best.onnx · metrics_real.json · 技术页 P10–13</div></div>
  <div class="card col"><h3><span class="n">2</span>系统线</h3><p>判定与定级的确定性实现、三智能体编排、研判台前后端与 Word 工单导出。</p><div class="small">交付：规则引擎 · 研判台 · 分级标准 v1.4</div></div>
  <div class="card col"><h3><span class="n">3</span>材料线</h3><p>赛事口径核对、20 页 PPT、6 分钟视频、提交包与答辩预案。</p><div class="small">交付：PPT · MP4 · 链接说明</div></div>
</div>
<div class="card" style="margin-top:16px;padding:16px 22px">
  <h3 style="margin-bottom:8px">参考来源（单列）</h3>
  <div class="smalltxt" style="line-height:1.9">
  <b>数据</b>　Chapian/ppev3（Roboflow <span class="mono" style="padding:1px 5px">ppe-detection-9p0pu</span> v3，CC BY 4.0）· Chapian/PPE_detection（CC BY 4.0）　|
  <b>法规</b>　《中华人民共和国安全生产法》（2021 年第三次修正）第四十一、四十五、四十六、五十七条　|
  <b>标准</b>　GB 2811-2019《头部防护 安全帽》· GB 39800.1-2020《个体防护装备配备规范 第 1 部分：总则》　|
  <b>框架</b>　Ultralytics YOLOv8s · ONNX Runtime · FastAPI</div>
</div>
<div class="note blue">按交付物分工，不按环节分工；三条线的接口是「检测框 JSON / 事件 JSON / 素材清单」，互不等待。</div>
"""

P03 = """
<div class="row" style="height:290px">
  <div class="card col" style="border-top:4px solid #2E7D5B">
    <h3>法规是刚性的</h3>
    <ul>
      <li>《安全生产法》第四十五条：必须提供符合标准的劳动防护用品，<b>并监督、教育从业人员按规则佩戴</b>。</li>
      <li>GB 2811-2019 / GB 39800.1-2020 对安全帽与配备规范有明确要求。</li>
      <li>企业要留痕：谁检查、发现什么、多久整改完、谁验收。</li>
    </ul>
    <div class="small">条文原文可在研判台 <span class="mono" style="padding:1px 5px">law_lookup</span> 中逐条查到，查不到就写「未检索到」。</div>
  </div>
  <div class="card col" style="border-top:4px solid #C4453C">
    <h3>执行是虚化的</h3>
    <ul>
      <li>一名安全员管多个车间，人工巡查每班只有 2 次 × 15 分钟。</li>
      <li>检查的人一走，帽子就摘——<b>看得见的违规，抓不住的时间窗</b>。</li>
      <li>监控系统只推「一条告警」，没有等级、时限、责任，也没有复查。</li>
      <li>告警太多之后，人就把提醒关了。</li>
    </ul>
    <div class="small">195 条逐帧告警里，真正需要处理的只有 13 个事件。</div>
  </div>
</div>
<div class="row" style="margin-top:18px;height:96px">
  <div class="card col" style="text-align:center;padding-top:20px"><div class="kpi" style="border:0;box-shadow:none;padding:0">
    <div class="v" style="font-size:30px">30 <span style="font-size:16px">分钟/班</span></div><div class="l">人工巡查覆盖</div></div></div>
  <div class="card col" style="text-align:center;padding-top:20px"><div class="kpi" style="border:0;box-shadow:none;padding:0">
    <div class="v" style="font-size:30px">195 <span style="font-size:16px">条</span></div><div class="l">34.8 秒视频产生的逐帧告警</div></div></div>
  <div class="card col" style="text-align:center;padding-top:20px"><div class="kpi" style="border:0;box-shadow:none;padding:0">
    <div class="v" style="font-size:30px">13 <span style="font-size:16px">个</span></div><div class="l">去重后真正要办的事件</div></div></div>
</div>
<div class="note">不是工人不怕，是<b>没人盯得住</b>；也不是没有摄像头，是<b>没人把画面变成一件要办的事</b>。</div>
"""

P04 = """
<div class="row" style="height:105px">
  <div class="kpi col"><div class="v">2,451</div><div class="l">训练图像</div><div class="t">ppe_full/train</div></div>
  <div class="kpi col"><div class="v">272</div><div class="l">验证图像</div><div class="t">ppe_full/valid</div></div>
  <div class="kpi col"><div class="v">17,610</div><div class="l">训练集标注框</div><div class="t">全部有标注，无空标注</div></div>
  <div class="kpi col"><div class="v warn">165</div><div class="l">剔除的重名图像</div><div class="t">防止与评测集泄漏重叠</div></div>
</div>
<div class="row" style="margin-top:16px;height:215px">
  <div class="card" style="flex:1.35">
    <h3>来源与授权</h3>
    <table><tr><th style="width:96px">项目</th><th>内容</th></tr>
      <tr><td>数据集</td><td>Chapian/ppev3（Roboflow <span class="mono" style="padding:1px 4px">ppe-detection-9p0pu</span> v3）</td></tr>
      <tr><td>许可协议</td><td><b>CC BY 4.0</b>（允许商用与再分发，须署名）</td></tr>
      <tr><td>获取时间</td><td>2026-11-01，经 HF 镜像获取</td></tr>
      <tr><td>原始类别</td><td>9 类</td></tr>
      <tr class="hl"><td>重映射</td><td>5 类：person / helmet / no-helmet / vest / no-vest</td></tr>
    </table>
  </div>
  <div class="card" style="flex:1">
    <h3>为什么重映射为 5 类</h3>
    <p>一次前向同时得到「人」与「装备状态」，不再外挂 COCO 人体模型做二级串联，
       避免两个模型的框对不齐造成漏判。</p>
    <div class="small">goggles / gloves / no-gloves 等原始类别在本项目<b>不参与判定</b>，只保留接口，
       避免「模型没检却写进结论」。</div>
    <div class="note blue" style="margin-top:12px">对外只能说「自训五类 PPE 权重」：架构来自 Ultralytics YOLOv8s，
       数据与训练由本项目完成。</div>
  </div>
</div>
<div class="note">数据卡片的每张图、每个框数都可核对；<b>本项目自采 0 张</b>，这一点在第 16 页主动披露。</div>
"""

P05 = """
<div class="row" style="height:120px">
  <div class="kpi col"><div class="v">100</div><div class="l">独立评测图像</div><div class="t">PPE_detection · test</div></div>
  <div class="kpi col"><div class="v">295</div><div class="l">真值人员框</div><div class="t">由标注框推导佩戴状态</div></div>
  <div class="kpi col"><div class="v">466</div><div class="l">模型检出框</div><div class="t">n_boxes</div></div>
  <div class="kpi col"><div class="v ok">0</div><div class="l">参与训练的张数</div><div class="t">也不参与选轮次</div></div>
</div>
<div class="row" style="margin-top:16px;height:196px">
  <div class="card" style="flex:1.2">
    <h3>第二渠道，也是唯一的报数出口</h3>
    <ul><li>与主训练集<b>同源不同集</b>，单独下载、单独建索引，不进训练目录。</li>
      <li>四个对外指标（mAP / 误报 / 漏报 / 单帧）全部在这 100 张上测。</li>
      <li>真值佩戴状态由标注框推导：Hardhat 落在头部区域记合规，只有 NO-Hardhat 记违规，两者都无则跳过。</li>
      <li>判定结论由规则引擎给出，不由模型自由发挥。</li></ul>
  </div>
  <div class="card" style="flex:1">
    <h3>诚实边界</h3>
    <p>同源不同集，<b>跨域泛化未验证</b>。100 张的颗粒度是「每 1 例 ≈ 1 个百分点」，
       能分辨差一个量级，分辨不了差 1–2 个点。</p>
    <div class="small">漏报率 95% 置信区间 1.7%–10.7%，上界越过 5% 目标线，
       所以答辩只说「点估计达标」，不说「稳定达标」。</div>
    <div class="note red" style="margin-top:10px">这是全片最重要的一条自律：<b>没有实测的数字不写，推演值必须标注。</b></div>
  </div>
</div>
<div class="note blue">评测口径：<span class="mono" style="padding:1px 5px">rules_profile: v3</span> · 中心点判据 · conf 0.65 · min_aspect 0.80；
演示口径另有一套宽阈值用于展示「待复核」保护档，<b>两套不可混引</b>。</div>
"""

P06 = """
<div class="row" style="height:196px">
  <div class="card col"><h3><span class="n">1</span>法规层</h3><p>《安全生产法》第四十一、四十五、四十六、五十七条，第九十九条第（五）项。<b>存原文，不存改写</b>。</p><div class="small">引用前必查，查不到写「未检索到」</div></div>
  <div class="card col"><h3><span class="n">2</span>标准层</h3><p>GB 2811-2019、GB 39800.1-2020。区分<b>标准原文</b>与<b>要点摘要</b>，避免把解读当条文。</p><div class="small">条号 + 年份可回溯</div></div>
  <div class="card col"><h3><span class="n">3</span>操作层</h3><p>巡检流程、留痕要求、整改单要素（事实 / 要求 / 依据 / 签署）。</p><div class="small">对应 Word 通知单四段式</div></div>
  <div class="card col"><h3><span class="n">4</span>经验层</h3><p>逆光、遮挡、远处小目标等现场失效模式，以及对应的三道无效性保护。</p><div class="small">来自误差归因，不是拍脑袋</div></div>
</div>
<div class="row" style="margin-top:16px;height:150px">
  <div class="card" style="flex:1.1">
    <h3>条文库怎么被调用</h3>
    <div class="flow" style="margin-top:6px">
      <div class="step"><b>用户提问</b><span>「违反了哪条」</span></div><span class="arrow">→</span>
      <div class="step"><b>law_lookup</b><span>白名单检索</span></div><span class="arrow">→</span>
      <div class="step"><b>原文回填</b><span>条号 + 逐字原文</span></div><span class="arrow">→</span>
      <div class="step"><b>写入工单</b><span>法规依据栏</span></div>
    </div>
    <div class="small" style="margin-top:14px">系统提示词第 3 条：不许编造条文或文号；第 10 条：只写本轮上下文明确给出的事实。</div>
  </div>
  <div class="card" style="flex:1">
    <h3>为什么要做白名单</h3>
    <p>大模型会把「大概有这么一条」说得像真的。工业场景里一条错误的法规引用，
       足以让整张整改单失去效力。</p>
    <div class="small">提交前逐字核对原文；法规模板、标准号、数据集出处必须能指认来源。</div>
  </div>
</div>
<div class="note">知识库不是给模型「补充常识」，是给结论<b>一个可被追责的出处</b>。</div>
"""

P07 = """
<div class="flow" style="margin-bottom:18px">
  <div class="step"><b>公开集下载</b><span>2 个渠道</span></div><span class="arrow">→</span>
  <div class="step"><b>9→5 类重映射</b><span>统一标签</span></div><span class="arrow">→</span>
  <div class="step"><b>剔除 165 张重叠</b><span>防泄漏</span></div><span class="arrow">→</span>
  <div class="step"><b>数据增强</b><span>对应现场问题</span></div><span class="arrow">→</span>
  <div class="step"><b>80 轮训练</b><span>best ep62</span></div><span class="arrow">→</span>
  <div class="step"><b>独立评测</b><span>100 张</span></div>
</div>
<div class="row" style="height:200px">
  <div class="card col"><h3>逆光 / 弱光</h3><p>调整 HSV 明度与饱和度，模拟车间侧窗强光、夜间照明不足。</p><div class="small"><span class="mono" style="padding:1px 5px">hsv_v / hsv_h</span></div></div>
  <div class="card col"><h3>遮挡</h3><p>随机擦除，模拟设备、料架、同行人员挡住上半身。</p><div class="small"><span class="mono" style="padding:1px 5px">erasing</span></div></div>
  <div class="card col"><h3>监控距离</h3><p>尺度缩放，模拟远处小目标与近距离大目标同时出现。</p><div class="small"><span class="mono" style="padding:1px 5px">scale</span></div></div>
  <div class="card col"><h3>安装倾斜</h3><p>小角度旋转，模拟摄像头非正装、俯角偏差。</p><div class="small"><span class="mono" style="padding:1px 5px">degrees</span></div></div>
</div>
<div class="note blue">每一项增强都在 <span class="mono" style="padding:1px 5px">train_yolo.py</span> 里注释了「对应哪个现场问题」——
不是「我们做了数据增强」这种空话，而是<b>增强与失效模式一一对应</b>。</div>
"""

P08 = """
<div class="row" style="height:206px">
  <div class="card" style="flex:1.1">
    <h3>为什么要拆成多个 Agent</h3>
    <p>感知、研判、工单三件事的<b>确定性要求完全不同</b>：</p>
    <table style="margin-top:10px"><tr><th>角色</th><th>职责</th><th>确定性</th></tr>
      <tr><td>视觉感知</td><td>输出四态判定</td><td>代码判定</td></tr>
      <tr><td>隐患研判</td><td>人数 → 等级 → 时限</td><td>规则引擎</td></tr>
      <tr class="hl"><td>工单闭环</td><td>生成通知单与留痕位</td><td>系统编号</td></tr>
      <tr><td>对话 Agent</td><td>理解问题、组织语言</td><td>大模型</td></tr>
    </table>
  </div>
  <div class="card" style="flex:1">
    <h3>等级为什么只由本次人数决定</h3>
    <p>我们前后用了四版 <b>R = L × S</b> 风险矩阵，最后把它推翻了：</p>
    <ul><li>L 取「区域近 30 天违规次数」→ 同一张图换个区域登记，等级就变。</li>
        <li>S 取「作业类型」→ 回答的是「场景多危险」，不是「多久要处理」。</li></ul>
    <div class="small">曾出现 1 人少穿背心判 2 小时内、7 人全缺 PPE 判 30 天内的倒挂。</div>
  </div>
</div>
<div class="row" style="margin-top:16px;height:96px">
  <div class="kpi col"><div class="v">A</div><div class="l">≥3 人 · 2 小时内</div></div>
  <div class="kpi col"><div class="v">B</div><div class="l">1–2 人 · 24 小时内</div></div>
  <div class="kpi col"><div class="v">C</div><div class="l">仅待复核 · 7 天内核实</div></div>
  <div class="kpi col"><div class="v">—</div><div class="l">全合规 · 不出单</div></div>
</div>
<div class="note">把「推翻自己用了四版的矩阵」写进分析过程，是<b>优化改进</b>而不是返工：
等级唯一由本次判定的人数决定，不由模型拍脑袋，也不由台账决定。</div>
"""

# ---- 第 09 页：思维导图（SVG 中心辐射）
MIND = """
<svg viewBox="0 0 1120 400" width="1060" height="380" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,sans-serif">
 <defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
   <path d="M0,0 L8,4 L0,8 z" fill="#B9C6D3"/></marker></defs>
 <g stroke="#C9D5E1" stroke-width="2" fill="none" marker-end="url(#ah)">
  <path d="M470,200 C380,200 360,72 292,72"/><path d="M470,200 C380,200 360,150 292,150"/>
  <path d="M470,200 C380,200 360,250 292,250"/><path d="M470,200 C380,200 360,328 292,328"/>
  <path d="M650,200 C740,200 760,72 828,72"/><path d="M650,200 C740,200 760,150 828,150"/>
  <path d="M650,200 C740,200 760,250 828,250"/><path d="M650,200 C740,200 760,328 828,328"/>
 </g>
 <rect x="452" y="152" width="216" height="96" rx="16" fill="#0F2740"/>
 <text x="560" y="190" fill="#fff" font-size="20" font-weight="800" text-anchor="middle">一帧画面</text>
 <text x="560" y="218" fill="#F0A468" font-size="20" font-weight="800" text-anchor="middle">→ 一张工单</text>
 <g font-size="13" font-weight="700">
  <g><rect x="60" y="46" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="76" y="68" fill="#1B6E8C">① 四态判定</text><text x="76" y="87" fill="#7C8B9B" font-size="11" font-weight="400">已佩戴 / 未佩戴 / 待复核 / 无法判定</text></g>
  <g><rect x="60" y="124" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="76" y="146" fill="#1B6E8C">② 三道无效性保护</text><text x="76" y="165" fill="#7C8B9B" font-size="11" font-weight="400">置信度三档 / 连续 3 帧 / 小目标拦截</text></g>
  <g><rect x="60" y="224" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="76" y="246" fill="#5E4B9B">③ 时序聚合</text><text x="76" y="265" fill="#7C8B9B" font-size="11" font-weight="400">195 条逐帧告警 → 13 个事件</text></g>
  <g><rect x="60" y="302" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="76" y="324" fill="#5E4B9B">④ 分档规则 v1.4</text><text x="76" y="343" fill="#7C8B9B" font-size="11" font-weight="400">只看本次确认未佩戴人数</text></g>
  <g><rect x="828" y="46" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="844" y="68" fill="#C25E2A">⑤ 等级与时限</text><text x="844" y="87" fill="#7C8B9B" font-size="11" font-weight="400">A 2h / B 24h / C 7d / 不出单</text></g>
  <g><rect x="828" y="124" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="844" y="146" fill="#C25E2A">⑥ 法规映射</text><text x="844" y="165" fill="#7C8B9B" font-size="11" font-weight="400">条号 + 原文，查不到写未检索到</text></g>
  <g><rect x="828" y="224" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="844" y="246" fill="#2E7D5B">⑦ 工单生成</text><text x="844" y="265" fill="#7C8B9B" font-size="11" font-weight="400">系统编号，模型不编人名与地名</text></g>
  <g><rect x="828" y="302" width="232" height="52" rx="9" fill="#fff" stroke="#DDE5ED"/>
     <text x="844" y="324" fill="#2E7D5B">⑧ 签署与复查</text><text x="844" y="343" fill="#7C8B9B" font-size="11" font-weight="400">留空由现场手填，导出 Word 通知单</text></g>
 </g>
</svg>"""
P09 = f"""<div class="svgwrap">{MIND}</div>
<div class="note blue" style="margin-top:2px">中心问题只有一个：<b>这一帧画面，最后要谁、在多久之内、办成一件什么事</b>。
左侧是「判得准」，右侧是「落得下」。</div>"""

ARCH = """
<svg viewBox="0 0 1120 320" width="1080" height="300" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,sans-serif">
 <rect x="20" y="96" width="170" height="96" rx="12" fill="#EAF1F8" stroke="#C6D8E8"/>
 <text x="105" y="132" font-size="15" font-weight="800" text-anchor="middle" fill="#0F2740">摄像头画面</text>
 <text x="105" y="158" font-size="11" text-anchor="middle" fill="#6B7A8C">1920×1080 · 单帧</text>
 <rect x="230" y="96" width="180" height="96" rx="12" fill="#0F2740"/>
 <text x="320" y="128" font-size="15" font-weight="800" text-anchor="middle" fill="#fff">检测模型</text>
 <text x="320" y="152" font-size="11" text-anchor="middle" fill="#A9C6DE">自训五类 · YOLOv8s</text>
 <text x="320" y="172" font-size="11" text-anchor="middle" fill="#F0A468">15.0 ms / 帧</text>
 <rect x="450" y="96" width="180" height="96" rx="12" fill="#0F2740"/>
 <text x="540" y="128" font-size="15" font-weight="800" text-anchor="middle" fill="#fff">规则引擎</text>
 <text x="540" y="152" font-size="11" text-anchor="middle" fill="#A9C6DE">四态 / 分档 / 工单</text>
 <text x="540" y="172" font-size="11" text-anchor="middle" fill="#F0A468">确定性，可复现</text>
 <rect x="670" y="96" width="180" height="96" rx="12" fill="#EAF1F8" stroke="#C6D8E8"/>
 <text x="760" y="128" font-size="15" font-weight="800" text-anchor="middle" fill="#0F2740">Agent 编排</text>
 <text x="760" y="152" font-size="11" text-anchor="middle" fill="#6B7A8C">理解 / 检索 / 组织语言</text>
 <text x="760" y="172" font-size="11" text-anchor="middle" fill="#6B7A8C">工具调用轨迹可查</text>
 <rect x="890" y="96" width="200" height="96" rx="12" fill="#FDF1DC" stroke="#E8C98A"/>
 <text x="990" y="128" font-size="15" font-weight="800" text-anchor="middle" fill="#8A5D0F">整改通知单</text>
 <text x="990" y="152" font-size="11" text-anchor="middle" fill="#8A743F">A/B/C · 时限 · 法规</text>
 <text x="990" y="172" font-size="11" text-anchor="middle" fill="#8A743F">Word 可签署留痕</text>
 <g stroke="#C05A2A" stroke-width="2.5" fill="none" marker-end="url(#ar)">
  <path d="M190,144 L226,144"/><path d="M410,144 L446,144"/><path d="M630,144 L666,144"/><path d="M850,144 L886,144"/></g>
 <defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
   <path d="M0,0 L8,4 L0,8 z" fill="#C05A2A"/></marker></defs>
 <rect x="230" y="228" width="620" height="62" rx="10" fill="#fff" stroke="#E0E7EF"/>
 <text x="250" y="254" font-size="13" font-weight="800" fill="#C25E2A">核心设计：判定逻辑与检测模型解耦</text>
 <text x="250" y="276" font-size="12" fill="#5B6D80">模型没训好也能演示 · 换模型不动业务 · 换平台不重写 · 同一输入结果可复现</text>
</svg>"""
P10 = f"""<div class="svgwrap">{ARCH}</div>
<div class="row" style="margin-top:8px;height:92px">
 <div class="card col" style="padding:14px 18px"><h3 style="font-size:14px">五 Agent 职责</h3><p style="font-size:12px">巡检规划 · 视觉感知 · 隐患研判 · 工单闭环 · 合规问答，前三步构成主链路。</p></div>
 <div class="card col" style="padding:14px 18px"><h3 style="font-size:14px">两个后端</h3><p style="font-size:12px">torch-GPU 与 ONNX-CPU 走同一套规则，线上托管用 best.onnx 实算，不是预置回答。</p></div>
 <div class="card col" style="padding:14px 18px"><h3 style="font-size:14px">一条原则</h3><p style="font-size:12px">数值判定与编号生成不交给大模型；模型只负责理解与表达。</p></div>
</div>"""

P11_TMPL = """
<div class="row" style="height:104px">
  <div class="kpi col"><div class="v ok">0.8654</div><div class="l">mAP@0.5</div><div class="t">目标 ≥ 0.85 ✓</div></div>
  <div class="kpi col"><div class="v ok">6.12%</div><div class="l">误报率（6 / 98）</div><div class="t">目标 ≤ 10% ✓</div></div>
  <div class="kpi col"><div class="v ok">4.35%</div><div class="l">漏报率（4 / 92）</div><div class="t">目标 ≤ 5% ✓</div></div>
  <div class="kpi col"><div class="v ok">15.0 ms</div><div class="l">单帧耗时（GPU）</div><div class="t">目标 ≤ 50 ms ✓</div></div>
</div>
<div class="row" style="margin-top:14px;height:228px">
  <div class="card" style="flex:1;padding:12px;display:flex;flex-direction:column">
    <div style="font-size:12.5px;font-weight:800;margin-bottom:6px">混淆矩阵 · helmet</div>
    <div class="imgframe" style="flex:1"><img src="{IMG_CM}"></div>
  </div>
  <div class="card" style="flex:1;padding:12px;display:flex;flex-direction:column">
    <div style="font-size:12.5px;font-weight:800;margin-bottom:6px">PR 曲线</div>
    <div class="imgframe" style="flex:1"><img src="{IMG_PR}"></div>
  </div>
  <div class="card" style="flex:1.05;padding:13px 16px">
    <h3 style="font-size:15px;margin-bottom:7px">口径与误差归因</h3>
    <p style="font-size:12px;line-height:1.6">100 张独立评测集，<b>rules_profile v3</b> · 中心点判据 · conf 0.65 · min_aspect 0.80；ONNX-CPU 36.5 ms/帧。</p>
    <table style="margin-top:8px;font-size:11.5px"><tr><th>类别</th><th>AP</th><th>说明</th></tr>
      <tr><td>person</td><td>0.8463</td><td>254 TP / 51 FP</td></tr>
      <tr><td>helmet</td><td>0.8845</td><td>133 TP / 28 FP</td></tr>
      <tr class="hl"><td>判定覆盖</td><td>89.62%</td><td>190 / 212 人次</td></tr></table>
    <div class="small" style="margin-top:8px;font-size:11px">4 例漏报中 2 例是「无法判定」被正确保护。</div>
  </div>
</div>
<div class="note red" style="margin-top:10px">⚠️ 漏报 95% 区间 1.7%–10.7%、误报 2.8%–12.7%，上界均越线：
<b>只能说「点估计达标」，不能说「稳定达标」</b>。100 张里每 1 例 ≈ 1 个百分点。</div>
"""

P12 = """
<div class="row" style="height:238px">
  <div class="card col" style="border-top:4px solid #B03A48">
    <h3>火焰检测 · 语义判断</h3>
    <p>要回答「这块红色是火、是蒸汽、是反光，还是红色物料？」——
       <b>同类外观、不同语义</b>，边界由场景定义，加数据也未必收敛。</p>
    <ul><li>误报来源：蒸汽、夕照、红色工装、焊花。</li>
        <li>标注本身就有分歧，不同人框得不一样。</li>
        <li>上一轮模型的准确率问题，本质是<b>任务级语义模糊</b>。</li></ul>
  </div>
  <div class="card col" style="border-top:4px solid #2E7D5B">
    <h3>PPE 检测 · 存在性判断</h3>
    <p>要回答「这个人的头上有没有一顶帽子？」——
       <b>目标明确、边界清晰、有国标可依</b>，是工程问题不是定义问题。</p>
    <ul><li>漏报看得见、归因得到：小目标、遮挡、框没对齐。</li>
        <li>补样本、调阈值、换 backbone 都有明确路径。</li>
        <li>实测误报 6.12% / 漏报 4.35%，四项指标全达标。</li></ul>
  </div>
</div>
<div class="row" style="margin-top:16px;height:104px">
  <div class="card col" style="padding:16px"><div class="big">场景是对的，感知任务是选的</div>
    <div class="smalltxt" style="margin-top:6px">我们没有放弃视觉能力，也没有放弃厂区巡检；
       换掉的是那个「边界说不清」的任务。</div></div>
  <div class="card col" style="padding:16px"><div class="big">从告警到工单，价值落在闭环</div>
    <div class="smalltxt" style="margin-top:6px">火焰检测做到最好也只是更早报警；
       PPE 检测后面接得上等级、时限、法规与签署。</div></div>
</div>
<div class="note blue">答辩预设：「你们不就是换了个检测目标吗？」——
换的是<b>可判定性</b>与<b>可闭环性</b>：前者的误差无法归因，后者每一例漏报都能指到具体帧。</div>
"""

P13 = """
<div class="row" style="height:212px">
  <div class="card col"><h3><span class="n">1</span>感知闭环</h3>
    <p><b>看得见 → 判得准 → 落得下</b>。不是把检测框推给人，而是把一次判定变成
       带等级、时限、法规依据和签署位的通知单。</p>
    <div class="small">195 条逐帧告警 → 13 个事件 → 可签署工单</div></div>
  <div class="card col"><h3><span class="n">2</span>定级有据</h3>
    <p>等级由<b>本次确认未佩戴人数</b>唯一确定，规则引擎给值，大模型不拍脑袋；
       同一输入连跑三次结果一致。</p>
    <div class="small">工具调用轨迹可在研判台右栏逐条点开</div></div>
  <div class="card col"><h3><span class="n">3</span>可解释的克制</h3>
    <p>四态判定 + 三道无效性保护，把「不确定」显式说出来；
       工单不预填责任人、地名、验收项，画面确认不了就不写。</p>
    <div class="small">宁可转人工，也不生成一条看起来很确定的错单</div></div>
</div>
<div class="card" style="margin-top:16px;padding:18px 22px;height:130px">
  <h3>跨学科视角 · 安全工程 × 计算机视觉 × 管理学</h3>
  <div class="flow" style="margin-top:12px">
    <div class="step"><b>安全工程</b><span>风险分级 / 法规留痕</span></div><span class="arrow">×</span>
    <div class="step"><b>计算机视觉</b><span>五类检测 / 时序聚合</span></div><span class="arrow">×</span>
    <div class="step"><b>管理学 PDCA</b><span>Plan 派单 → Do 整改 → Check 复查 → Act 归档</span></div>
  </div>
  <div class="small" style="margin-top:10px">技术只是其中一环：真正让系统有价值的，是它把一次「看见」放进了企业既有的管理闭环里。</div>
</div>
<div class="note">创新点不宣称「算法原创」，而是<b>把已有技术组织成一件办得完的事</b>——这正是通用赛道考察的应用创新。</div>
"""

P14 = """
<div class="row" style="height:112px">
  <div class="kpi col" style="border-left:4px solid #B03A48"><div class="v">A</div><div class="l">≥3 人 · 2 小时内</div></div>
  <div class="kpi col" style="border-left:4px solid #C98A16"><div class="v">B</div><div class="l">1–2 人 · 24 小时内</div></div>
  <div class="kpi col" style="border-left:4px solid #2E7D5B"><div class="v">C</div><div class="l">仅待复核 · 7 天内核实</div></div>
  <div class="kpi col" style="border-left:4px solid #8996A5"><div class="v">—</div><div class="l">全合规 · 不出单</div></div>
</div>
<div class="card" style="margin-top:14px;padding:16px 20px">
  <h3 style="font-size:15px;margin-bottom:8px">线上接口实测四场景（同一批 best.onnx 权重）</h3>
  <table><tr><th>场景</th><th>本次判定</th><th>等级</th><th>处理时限</th><th>说明</th></tr>
    <tr><td>二楼平台</td><td>1 人未穿反光背心</td><td><span class="tag b">B</span></td><td>24 小时内</td><td>作业类型是高处，但不升档</td></tr>
    <tr class="hl"><td>装卸区</td><td>8 人未穿反光背心</td><td><span class="tag a">A</span></td><td>2 小时内</td><td>面上失控，立即处置</td></tr>
    <tr><td>喷漆房</td><td>5 人未戴安全帽</td><td><span class="tag a">A</span></td><td>2 小时内</td><td>人数决定，不看区域台账</td></tr>
    <tr><td>通道</td><td>全部已佩戴</td><td><span class="tag mute">不出单</span></td><td>—</td><td>没有工单也是一次完整研判</td></tr>
  </table>
</div>
<div class="note">关键结论：<b>同一张图换到哪个区域登记，等级都不变。</b>
这是 v1.4 相对旧矩阵最想说明的事——等级回答「多久处理」，不由台账和场景替你回答。</div>
"""

P15 = """
<div class="row" style="height:118px">
  <div class="kpi col" style="flex:1.3"><div class="v">195 → 13</div><div class="l">逐帧告警 → 去重事件</div><div class="t">降噪 93.33%</div></div>
  <div class="kpi col"><div class="v ok">76.92%</div><div class="l">判定覆盖率</div><div class="t">10 / 13 事件活到 3 帧窗口</div></div>
  <div class="kpi col"><div class="v ok">57.14%</div><div class="l">合规率（helmet）</div><div class="t">4 / 7，待复核单列不进分母</div></div>
</div>
<div class="row" style="margin-top:14px;height:196px">
  <div class="card" style="flex:1.25;padding:18px 22px">
    <h3>主角数字：降噪 93.33%</h3>
    <p>34.8 秒单路视频、28 人次，逐帧共触发 <b>195 条告警</b>；经连续 3 帧时序聚合去重后，
       只剩 <b>13 个需要人去办的事件</b>。</p>
    <div style="margin-top:14px"><div style="font-size:12px;color:#5B6D80">逐帧告警 195</div>
      <div class="bar"><i style="width:100%;background:#C9D5E1"></i></div>
      <div style="font-size:12px;color:#5B6D80;margin-top:10px">去重后事件 13</div>
      <div class="bar"><i style="width:6.7%;background:#C25E2A"></i></div></div>
    <div class="small" style="margin-top:12px">这正好回扣「告警是一条通知，工单是一个责任」：
       系统真正交付的不是更多提醒，是<b>更少但更该办的事</b>。</div>
  </div>
  <div class="card" style="flex:1;padding:18px 22px">
    <h3>数字分两类，别混</h3>
    <table style="font-size:12.5px"><tr><th>数字</th><th>性质</th></tr>
      <tr><td>195→13 / 93.33%</td><td><span class="tag c">实测</span></td></tr>
      <tr><td>76.92% / 57.14%</td><td><span class="tag c">实测</span></td></tr>
      <tr><td>0.8654 / 6.12% / 4.35%</td><td><span class="tag c">实测</span></td></tr>
      <tr class="hl"><td>巡检覆盖 16×</td><td><span class="tag b">推演</span></td></tr></table>
    <div class="small" style="margin-top:10px">16× 来自「人工每班 2 次 × 15 分钟 vs 单路连续 8 小时」的<b>排班假设</b>，
       不是实测；放出来必须标注，评委一问基线才不会塌。</div>
  </div>
</div>
<div class="note blue">价值量化不写「节省多少万元」这类无法核对的估算，只写能从数据里复算出来的三件事：
<b>降噪、覆盖、合规率口径</b>。</div>
"""

P16 = """
<div class="row" style="height:156px">
  <div class="card col"><h3>① 自采 0 张</h3><p>全部数据来自两个公开集，同源不同集，<b>跨域泛化未验证</b>。真实工厂的光照、摄像头角度、工装颜色都可能不同。</p><div class="small">下一步：补现场数据并单独建评测集</div></div>
  <div class="card col"><h3>② 评测集只有 100 张</h3><p>每 1 例 ≈ 1 个百分点。漏报 95% 区间上界 <b>10.7%</b>、误报上界 12.7%，都越过目标线。</p><div class="small">只能说点估计达标；扩到 500+ 张才有稳定结论</div></div>
  <div class="card col"><h3>③ 背心类明显更弱</h3><p>vest 的 mAP 约 <b>0.663</b>，训练图仅 100 张，误漏报都高于 helmet。试过重增强，收益有限。</p><div class="small">下一步：补带 vest 标注的独立数据源</div></div>
</div>
<div class="row" style="margin-top:14px;height:120px">
  <div class="card col"><h3>④ 类别覆盖不全</h3><p>goggles / gloves 只保留接口，不参与判定；系统提示词明确禁止模型把没检的装备写进结论。</p></div>
  <div class="card col"><h3>⑤ 现场素材有限</h3><p>价值量化基于 34.8 秒单路视频、无真实整改过程，因此<b>不体现「违规→合规」的整改耗时</b>。</p></div>
  <div class="card col"><h3>⑥ 离线依赖</h3><p>研判台已取消离线降级，现场需联网；已准备录屏备份与二维码备用入口。</p></div>
</div>
<div class="note">主动把局限摆出来，是因为这些数字<b>评委一问就要重跑</b>。
装完美的作品一戳就破；能说清边界的作品，才像真的做过。</div>
"""

P17 = """
<div class="row" style="height:196px">
  <div class="card col"><h3>隐私风险</h3><p>工人影像<b>不落地、不进截图、不进提交包</b>；研判台只输出结构化判定与工单，
       不输出人脸身份信息。</p><div class="small">提交前逐张检查：无正脸、无工牌、无姓名</div></div>
  <div class="card col"><h3>误报信任风险</h3><p>工业场景里误报几次，安全员就把告警关了。三道无效性保护把「不确定」显式说出来，
       宁可转人工，不硬判。</p><div class="small">实测误报 6.12%</div></div>
  <div class="card col"><h3>责任边界风险</h3><p>系统只做<b>辅助判定</b>，不替代安全员签字；工单里责任人、复查人、验收项一律留空由现场手填。</p>
    <div class="small">输出的是可签署、可追责的通知单</div></div>
</div>
<div class="card" style="margin-top:16px;padding:18px 22px;height:142px">
  <h3>三道无效性保护（对应第 09 页思维导图左支）</h3>
  <div class="flow" style="margin-top:12px">
    <div class="step"><b>置信度三档</b><span>定论 / 转人工 / 丢弃</span></div><span class="arrow">→</span>
    <div class="step"><b>连续 3 帧聚合</b><span>结论一致才输出，否则待复核</span></div><span class="arrow">→</span>
    <div class="step"><b>小目标拦截</b><span>框面积 &lt; 8000 px² 判无法判定</span></div><span class="arrow">→</span>
    <div class="step"><b>四态输出</b><span>禁止「可能 / 大概」</span></div>
  </div>
  <div class="small" style="margin-top:12px">「无法判定」与「待复核」不得被时序聚合成「待复核」以外的任何结论——
     这是规则引擎里专门修过的一个 bug，失效状态不允许被改写成违规。</div>
</div>
<div class="note blue">答辩口径：系统不自动指派责任人，<b>它把该由谁签字、什么时候验收的位置留出来</b>。</div>
"""

P18_TMPL = """
<div class="row" style="height:330px">
  <div class="card" style="flex:1.55;padding:10px;display:flex;flex-direction:column">
    <div style="font-size:12.5px;font-weight:800;margin:2px 0 6px 4px">在线研判台 · 真实界面（2026-11-10 截取）</div>
    <div class="imgframe" style="height:268px;max-height:268px;flex:none"><img src="{IMG_DESK}"></div>
  </div>
  <div class="card compact" style="flex:1">
    <h3>这一屏能证明什么</h3>
    <ul><li>左侧对话、右侧实时研判，<b>不是预置回答</b>。</li>
        <li>右栏顶部四态统计：已佩戴 / 待复核 / 未佩戴 / 无法判定。</li>
        <li>处置等级卡片直接给 <b>B 级 · 当日处置 · 24 小时内</b>，并写明分档规则。</li>
        <li>整改工单、法规依据可点开追到条号与原文。</li></ul>
    <div class="small" style="margin-top:8px">底部标注：判定与工单以规则引擎输出为准，右侧由 best.onnx 对帧图实算。</div>
    <div class="note red" style="margin-top:9px">现场必须联网：研判台已无离线降级，连不上会明说「云端未连接」。<b>另备录屏。</b></div>
  </div>
</div>
<div class="row" style="margin-top:14px;height:88px">
  <div class="card col" style="padding:12px 16px"><h3 style="font-size:14px">上传真图片</h3><p style="font-size:12px">上传后由 ONNX 模型实算，四态与等级走 /api/inspect，工单号由系统生成。</p></div>
  <div class="card col" style="padding:12px 16px"><h3 style="font-size:14px">导出 Word 通知单</h3><p style="font-size:12px">《安全隐患整改通知单》1 页，含基本信息 / 违规事实 / 整改要求 / 法规依据 / 签署栏。</p></div>
  <div class="card col" style="padding:12px 16px"><h3 style="font-size:14px">工具轨迹可查</h3><p style="font-size:12px">grade_risk → A/B/C 与时限、law_lookup → 条文原文，均可逐条点开核对。</p></div>
</div>
"""

P19_TMPL = """
<div class="row" style="height:264px">
  <div class="card col" style="padding:12px 14px">
    <div class="tag b">示例一</div><h3 style="font-size:13px;margin-top:7px;margin-bottom:6px">提示词</h3>
    <div class="mono" style="font-size:11.5px">把这张图的违规开一张整改工单，说清楚等级和依据。</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输入</h3><div class="smalltxt">确认未佩戴 1 人 · 待复核 0 人</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输出</h3>
    <div class="big" style="font-size:16px;color:#C98A16">B 级 · 24 小时内</div>
    <div class="smalltxt" style="margin-top:6px">四态判定 → grade_risk → 工单卡片；责任人留空</div>
  </div>
  <div class="card col" style="padding:12px 14px">
    <div class="tag a">示例二</div><h3 style="font-size:13px;margin-top:7px;margin-bottom:6px">提示词</h3>
    <div class="mono" style="font-size:11.5px">同一批权重，装卸区这一帧呢？为什么等级变了？</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输入</h3><div class="smalltxt">确认未佩戴 8 人 · 待复核 1 人</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输出</h3>
    <div class="big" style="font-size:16px;color:#B03A48">A 级 · 2 小时内</div>
    <div class="smalltxt" style="margin-top:6px">差别只在人数；待复核转人工，不进违规统计</div>
  </div>
  <div class="card col" style="padding:12px 14px">
    <div class="tag c">示例三</div><h3 style="font-size:13px;margin-top:7px;margin-bottom:6px">提示词</h3>
    <div class="mono" style="font-size:11.5px">这一帧有违规吗？需要开工单吗？</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输入</h3><div class="smalltxt">确认未佩戴 0 人 · 3 人全部已佩戴</div>
    <h3 style="font-size:13px;margin-top:8px;margin-bottom:6px">输出</h3>
    <div class="big" style="font-size:16px;color:#2E7D5B">不出单</div>
    <div class="smalltxt" style="margin-top:6px">grade_risk 未返回等级，未调用 create_ticket</div>
  </div>
</div>
<div class="row" style="margin-top:10px;height:124px">
  <div class="card" style="flex:1.55;padding:12px 16px;display:flex;gap:16px;align-items:center">
    <div class="imgframe" style="width:104px;height:104px;flex:none"><img src="{IMG_QR}" style="width:100%"></div>
    <div><h3 style="font-size:15px">Agent 可访问链接（官方硬要求）</h3>
      <div class="mono" style="font-size:11px;margin-top:8px">https://anxun-desk.app.workbuddy.host/?sharecode=OLOGYZUPHO</div>
      <div class="small" style="margin-top:8px">⚠️ 二维码与链接必须含完整 <b>?sharecode=OLOGYZUPHO</b>，裸域名返回 403。<br>
        已在非本人设备验证；现场联网 + 录屏备份。</div></div>
  </div>
  <div class="card" style="flex:1;padding:14px 18px">
    <h3 style="font-size:15px">提示词设计要点</h3>
    <p style="font-size:12.5px">系统提示词共 14 条，核心是<b>等级、时限、工单号都不交给大模型</b>：
       必先调 grade_risk，引用条文先调 law_lookup，开工单必调 create_ticket。</p>
    <div class="small" style="margin-top:8px">完整三组提示词 → 输入 → 输出见仓库 docs/12-Agent提示词示例.md</div>
  </div>
</div>
<div class="note blue" style="margin-top:8px">三组覆盖 B / A / 不出单；C 档（仅待复核 → 7 天内核实）为规则补充，
未在三组实测场景中出现，<b>不冒充实测</b>。</div>
"""

P20 = """
<div class="card" style="padding:26px 32px;height:170px;background:#0F2740;border-color:#0F2740">
  <div style="font-size:13px;color:#8FB0CC;letter-spacing:2px">回到最初那一句</div>
  <div class="quote" style="color:#fff;margin-top:14px">别人做的是告警，我们做的是工单。<br>
    <em>告警是一条通知，工单是一个责任。</em></div>
</div>
<div class="row" style="margin-top:18px;height:170px">
  <div class="card col"><h3><span class="n">1</span>先把判定做稳</h3><p>扩评测集到 500+ 张、补现场自采数据，把漏报置信区间压到目标线以内；
       单独补 vest 标注数据源。</p></div>
  <div class="card col"><h3><span class="n">2</span>再把闭环接通</h3><p>对接企业既有隐患台账，让工单编号、复查、归档进入 PDCA；
       责任人由现场在签署栏确认，系统不代填。</p></div>
  <div class="card col"><h3><span class="n">3</span>最后扩到更多场景</h3><p>在可判定性成立的前提下，逐步接入护目镜、手套等装备类别，
       以及多路摄像头的排班覆盖。</p></div>
</div>
<div class="note">我们没把系统说成已经替企业管好了安全。它现在做到的是：
<b>把一次「看见」，变成一件有人签、有时限、能复查的事。</b></div>
<div class="center" style="margin-top:18px;font-size:13px;color:#8996A5">感谢评审　·　安巡 Agent　·　2026 年 11 月</div>
"""


def build() -> None:
    SLIDES.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (SLIDES / "style.css").write_text(CSS, encoding="utf-8", newline="\n")

    def uri(p: Path) -> str:
        # 相对 slides/ 目录，保证仓库 clone 后 HTML 仍能打开
        return os.path.relpath(p.resolve(), SLIDES.resolve()).replace("\\", "/")

    vals = {
        "IMG_CM": uri(ROOT / "techline-v3.1.0/docs/figs/confusion_matrix.png"),
        "IMG_PR": uri(ROOT / "techline-v3.1.0/docs/figs/pr_curve.png"),
        "IMG_DESK": uri(ASSETS / "desk_online.png"),
        "IMG_QR": uri(ASSETS / "qrcode.png"),
    }
    P11 = P11_TMPL.format(**vals)
    P18 = P18_TMPL.format(**vals)
    P19 = P19_TMPL.format(**vals)

    entries = [
        (None, None, None, COVER, C[1]),
        (1, "作品背景与说明", "别人做告警，我们做工单", "三人分工、一句话定位与参考来源", P02, C[1]),
        (1, "场景痛点", "法规是刚性的，执行是虚化的", "摄像头已经装好了，缺的是把画面变成一件要办的事", P03, C[1]),
        (2, "数据来源一 · 主训练集", "2,451 张训练图像，全部可追溯", "Chapian/ppev3 · CC BY 4.0 · 9 类重映射为 5 类", P04, C[2]),
        (2, "数据来源二 · 独立评测集", "100 张，全程不参与训练与选轮次", "四个对外指标的唯一报数出口", P05, C[2]),
        (2, "知识库构建", "四层知识库，每条结论可追到条号", "法规 / 标准 / 操作 / 经验，原文与摘要严格区分", P06, C[2]),
        (2, "数据预处理流程", "每种增强都对应一个现场问题", "不是「做了数据增强」，而是增强与失效模式一一对应", P07, C[2]),
        (3, "分析方法选择", "等级只由本次人数决定，不由模型拍脑袋", "我们用了四版风险矩阵，最后把它推翻了", P08, C[3]),
        (3, "分析流程 · 思维导图", "一帧画面 → 一张工单", "左侧判得准，右侧落得下；中心只有一次完整研判", P09, C[3]),
        (3, "系统架构", "判定逻辑与检测模型解耦", "检测模型 → 规则引擎 → Agent 编排 → 整改通知单", P10, C[3]),
        (4, "模型实测指标", "四个数，一个说得清的口径", "100 张独立评测集 · rules_profile v3 · 四项点估计全部达标", P11, C[4]),
        (4, "为什么放弃火焰检测", "场景是对的，感知任务是选的", "语义判断 vs 存在性判断：前者的误差无法归因", P12, C[4]),
        (4, "创新点与跨学科视角", "看得见 → 判得准 → 落得下", "安全工程 × 计算机视觉 × 管理学 PDCA", P13, C[4]),
        (5, "结果解读", "同一张图换区域，等级不变", "v1.4 分档 · 线上接口实测四场景", P14, C[5]),
        (5, "价值量化", "195 条告警，只留下 13 件该办的事", "降噪 93.33%；实测与推演分栏，不拿假设冒充结果", P15, C[5]),
        (5, "问题与优化建议", "主动承认六条局限", "评委一问就要重跑的数字，不如现在就摆出来", P16, C[5]),
        (5, "风险识别与应对", "隐私、误报信任、责任边界", "三道无效性保护，以及一条不越界的叙事红线", P17, C[5]),
        (6, "应用对话界面", "真实研判台，不是设计稿", "上传真图片 → 四态判定 → A/B/C 定级 → 导出 Word 通知单", P18, C[6]),
        (6, "三组提示词示例 + Agent 链接", "官方硬要求：提示词、输出、可访问链接", "三组覆盖 B / A / 不出单；二维码含完整 sharecode", P19, C[6]),
        (6, "结尾与展望", "把一次「看见」，变成一件办得完的事", "先做稳判定，再接通闭环，最后扩场景", P20, C[6]),
    ]

    import re
    for i, item in enumerate(entries, 1):
        if item[0] is None:
            html = item[3]
        else:
            _, ch_short, title, sub, body, accent = item
            html = page(i, CH[item[0]], title, sub, body, accent)
        # 固定 height 会让内容多的卡片溢出遮挡下方元素；
        # 改成 min-height 后容器随内容自适应，版式仍保持原有最小高度。
        html = re.sub(
            r'(<div class="(?:row|card|kpi)" style="[^"]*?)\bheight:(\d+px)',
            r'\1min-height:\2', html,
        )
        (SLIDES / f"p{i:02d}.html").write_text(html, encoding="utf-8", newline="\n")

    # 单个总览页（方便人直接翻）
    allpages = "\n".join(
        f'<iframe src="p{i:02d}.html" style="width:640px;height:360px;border:1px solid #ccc"></iframe>'
        for i in range(1, 21)
    )
    (OUT / "slides_overview.html").write_text(
        f'<!DOCTYPE html><meta charset="utf-8"><title>安巡 Agent · 20 页总览</title>'
        f'<body style="background:#E9EDF2;font-family:Microsoft YaHei;padding:20px">'
        f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:14px">{allpages}</div></body>',
        encoding="utf-8", newline="\n",
    )
    print(f"生成 20 页 HTML → {SLIDES}")


def shoot() -> None:
    for i in range(1, 21):
        src = (SLIDES / f"p{i:02d}.html").as_uri()
        dst = SLIDES / f"p{i:02d}.png"
        cmd = [
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            "--allow-file-access-from-files", "--virtual-time-budget=3500",
            f"--window-size={W},{H}", f"--screenshot={dst}", src,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if not dst.exists():
            raise RuntimeError(f"第 {i} 页截图失败: {r.stderr.decode(errors='ignore')[:300]}")
        print(f"  [{i:02d}/20] {dst.name} {dst.stat().st_size // 1024} KB", flush=True)


def make_pptx() -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for i in range(1, 21):
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(
            str(SLIDES / f"p{i:02d}.png"), 0, 0,
            width=prs.slide_width, height=prs.slide_height,
        )
    out = OUT / "安巡Agent_PPT_1110.pptx"
    prs.save(out)
    return out


if __name__ == "__main__":
    build()
    shoot()
    p = make_pptx()
    print(f"\nPPTX: {p}  {p.stat().st_size / 1048576:.2f} MB  页数 20")
