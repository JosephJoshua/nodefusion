
from __future__ import annotations

import html
import os
from pathlib import Path

from . import bundle as bundle_mod
from .analyze import Analysis

ASSETS = Path(__file__).parent / "assets"

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>__TITLE__</title>
<style>
__CSS__
</style>
</head>
<body>
<div id="loading" style="padding:40px;color:#9aa7b5;font-family:system-ui">
  正在解压运行记录…
</div>

<div id="app" style="display:none">
  <header>
    <h1>Node<span>Fusion</span> · 运行观测报告</h1>
    <span id="outcome" class="badge"></span>
    <div class="hmeta" id="hmeta"></div>
  </header>

  <div class="capability" id="capability" style="display:none"></div>

  <div class="timebar">
    <button id="prev">◀ 上一快照</button>
    <button id="play">播放</button>
    <button id="next">下一快照 ▶</button>
    <input type="range" id="slider" min="0" value="0">
    <span class="tlabel" id="tlabel"></span>
  </div>
  <div class="minimapwrap"><canvas id="minimap"></canvas></div>

  <!-- 变化摘要条：只回答"相对上一个快照，这一刻有什么变了"。
       全部是从两个快照相减得到的纯事实，不含任何对实验意图的猜测。 -->
  <div class="deltabar" id="deltabar" style="display:none"></div>

  <div class="main">
    <div class="left">
      <nav class="tabs">
        <button data-tab="compare">对比</button>
        <button data-tab="overview" class="on">概览</button>
        <button data-tab="phys">物理内存</button>
        <button data-tab="procs">进程与调度</button>
        <button data-tab="vm">虚拟内存与页表</button>
        <button data-tab="fs">文件系统与磁盘</button>
        <button data-tab="events">事件</button>
        <button data-tab="metrics">指标</button>
        <button data-tab="console">控制台</button>
      </nav>
      <div class="panel on" id="panel-overview"></div>
      <div class="panel" id="panel-phys"></div>
      <div class="panel" id="panel-procs"></div>
      <div class="panel" id="panel-vm"></div>
      <div class="panel" id="panel-fs"></div>
      <div class="panel" id="panel-events"></div>
      <div class="panel" id="panel-metrics"></div>
      <div class="panel" id="panel-console"></div>
      <div class="panel" id="panel-compare"></div>
    </div>
    <div class="right">
      <div id="detail">
        <div class="dsec">
          <div class="t">使用方法</div>
          <div class="hint">
            <b>按时间看</b>：拖动上方时间轴，或用 ← → 逐个快照步进，
            下面各页会显示那一刻整个系统的状态。<br><br>
            <b>按事件看</b>：切到「事件」页，筛选某类 syscall / 缺页 / 中断 /
            上下文切换 / 磁盘事件，点任意一行会把时间定位过去，
            这里会显示它的参数、前后系统变化和邻近事件。<br><br>
            凡是外部观测无法确定的信息，都会明确标成未知，不会用推测值填充。
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

__DATA__

<script>
__JS__
</script>
</body>
</html>
"""


def _data_block(b64: str, name: str) -> str:
    return (f'<script type="application/nodefusion" data-name="{html.escape(name)}">'
            f'{b64}</script>')


def render(analyses: list[Analysis], out_path: Path, *, title: str | None = None) -> Path:
    if not analyses:
        raise ValueError("至少需要一次运行的分析结果")

    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    js = (ASSETS / "app.js").read_text(encoding="utf-8")

    blocks = []
    for a in analyses:
        b = bundle_mod.build(a)
        blocks.append(_data_block(bundle_mod.encode(b), b["meta"]["run"] or "run"))

    if title is None:
        names = " vs ".join(a.manifest.get("run_name", "run") for a in analyses)
        title = f"NodeFusion · {names}"

    page = (_PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__CSS__", css)
            .replace("__JS__", js)
            .replace("__DATA__", "\n".join(blocks)))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(page, encoding="utf-8", newline="\n")
        tmp.replace(out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return out_path
