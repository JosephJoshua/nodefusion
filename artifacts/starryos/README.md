# StarryOS

[showcase 报告](showcase/starry-100pct-final.html) 覆盖本次归档运行的子系统。
原始函数入口数量与交互抽样数量见
[证据](showcase/starry-100pct-final.evidence.json)。

应用录制：[forkecho](apps/forkecho/starry-forkecho-ram512.html)、
[fsprobe](apps/fsprobe/starry-fsprobe-ram512.html)。两份报告的覆盖结果与来源哈希
在同目录的视频 JSON 的 `report` 字段。两次录制均通过严格覆盖检查，
包含返回指令核对的调用链；原始事件分别为 17,423,047 和 16,667,116 条，
交互报告各保留 150,000 条。`showcase/` 下的 MP4/JSON 属于此前的分子系统
录制批次，与应用报告的原始 trace 不同。
