# 运行报告

每份 HTML 的证据记录原始 trace、manifest、watchlist、布局、ELF 和 HTML 的
SHA-256，以及覆盖检查和函数入口数量。独立报告使用同名 `.evidence.json`；
已有视频的报告写入视频 JSON 的 `report` 字段；uCoreOS 每章使用 `coverage.json`。
同目录的 MP4 对应同名 JSON，较早的独立录制仍以自己的文件名保留。
HTML 可以直接在浏览器打开。原始 trace 和 ELF 体积较大，保留在录制归档中。
覆盖百分比按该次运行的适用检查计算；执行路径范围取决于工作负载。

| 内核 | 报告 | 覆盖情况 |
|---|---|---|
| uCoreOS | [ch1–ch8](ucoreos/) | 八章严格检查均通过 |
| StarryOS | [showcase](starryos/showcase/starry-100pct-final.html)、[应用](starryos/apps/) | showcase 和两个应用均通过严格检查 |
| rCore | [ch1–ch8](rcore/) | 八章严格检查均通过 |
| ArceOS | [应用](arceos/apps/) | 当前录制有缺项 |
| xv6 | [lab3-cow](xv6/lab3-cow/lab3-cowtest-mac.html) | 当前录制有缺项；其他旧样例未重新录制 |

报告的「函数轨迹」展示观察点命中的入口顺序和直接调用方。用
`nodefusion record --function-returns` 新录制的轨迹还能显示经返回指令核对的
观测调用链；旧轨迹没有返回事件。交互报告最多保留 150,000 条事件，
按 kind 保留代表样本；统计与覆盖检查使用完整原始记录。抽样数量见 HTML 和证据 JSON。

从归档重建一份报告：

```sh
python -m scripts.regenerate_artifact \
  --run nodefusion/runs/<run-name> \
  --out artifacts/<kernel>/<chapter-or-app>/<run-name>.html \
  --replace
```

仅在要求所有适用项通过时加 `--strict`。命令默认生成独立证据；同一次录制的
视频与报告可用 `python -m scripts.consolidate_artifacts artifacts` 做一次性合并
（针对仓库已知的章节与应用路径）。不同录制批次以各自的来源哈希区分。
