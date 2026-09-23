# xv6-riscv

[lab3-cow 单次报告](lab3-cow/lab3-cowtest-mac.html)使用同名 `.evidence.json`。

仓库还保留三份早期报告：

| 报告 | 内容 |
| --- | --- |
| [boot](boot/boot-trace.html) | 从上电到 shell 的启动过程 |
| [lab3-lazy](lab3-lazy/lab3-lazy.html) | lazy allocation 实验 |
| [COW 对比](lab3-cow/compare-cow.html) | COW 开启与关闭的并排报告 |

这三份报告生成于 manifest 机制之前，`manifest.json` 中没有 `kernel_kind`。录制元数据
保留原始 Windows 内核路径；本仓库不包含对应的 xv6 源码树。
