# 验证脚本

这些脚本的判据不是"跑完没报错"，而是**产物有没有在不知道的地方编数**。
NodeFusion 的整个价值建立在"读不到就说读不到"上，所以每个脚本都在找同一类问题：
把"测不到"悄悄变成一个看起来正常的数字。

跑法（在仓库根目录）：

```bash
python3 nodefusion/tests/test_units.py            # 秒级
python3 nodefusion/tests/stress_pagetable.py      # 约 10 秒
python3 nodefusion/tests/fuzz_trace.py            # 约 1 分钟，需要一份真实 trace.nfb
python3 nodefusion/tests/crosscheck_artifacts.py  # 需要一份录好并渲染过的运行目录
```

`fuzz_trace.py` 和 `crosscheck_artifacts.py` 里的运行目录路径写死成
`/tmp/nf_runs/rcore-ch4`，换目录时改文件开头的 `RD` / `SRC`。

## 各自查什么

| 脚本 | 查什么 | 为什么值得单独查 |
| --- | --- | --- |
| `test_units.py` | `KernelProfile.classify` 的判定顺序、`shell.path`、`cli._path` | rCore 正常跑完是**走 panic 处理器**的（`Panicked at ... All applications completed!`），控制台里 done 标记和 panic 标记同时存在。顺序写反，一次成功的运行会被记成崩溃，而且看不出来。 |
| `stress_pagetable.py` | `walk_pagetable` 对环形 / 损坏 / 超大页表的行为 | 轨迹文件是可能损坏的。这里发现过一棵"每项都指回自己"的页表让遍历跑 59 秒（1+512+512² 个结点），因为原来的上限只卡叶子数，而这种页表一个叶子都不产生。 |
| `fuzz_trace.py` | `nftrace` 解析器吃截断 / 位翻转 / 长度字段爆值 | 解析器崩溃不可怕，**把垃圾读成一份看起来正常的轨迹**才可怕。判据是每个变异体必须落进"正常解析 / 标记截断 / 抛异常"三类之一，绝不能读出暴涨的快照数或指令数。 |
| `crosscheck_artifacts.py` | `events.jsonl`、内嵌 HTML 数据与 `trace.nfb` 三者对账 | 三份产物各自自洽没有意义，必须互相对得上：事件数 == 轨迹里的 discon 数，HTML 内嵌事件分布 == jsonl 分布，没有观测点的指标必须是 `null` 而不是 `0`。 |

本机 `runs/` 是忽略目录，随手放入一份数 GB 的展示轨迹不应让普通测试突然扫几个
小时。穷举全部录制的测试标为 `corpus`，普通 `pytest` 会明确 skip；在容量充足的
归档机上显式运行
`NF_CORPUS_MAX_TRACE_MIB=0 python -m pytest nodefusion/tests --run-corpus`。只想跑本机
中等轨迹时省略环境变量，默认发现上限是 256 MiB。

## 已知未覆盖

**xv6 路径没有经过实际运行验证** —— 这台机器上没有 xv6 源码树，
`record.py` 的 `_drive_shell`（交互式 shell 驱动）、`XV6` profile 的编译与启动参数
都只做了静态自检。改动这些地方时必须在有 xv6 的机器上实跑一遍。

其中**结局判定那一段已经能单测了**（`test_shell_verdict.py`）：`_verdict` 是
"完整控制台文本 -> 结局"的纯函数，喂真实控制台片段就能查，不需要内核。原来判定
散在轮询循环里，用的是"这一刻谁已经出现在缓冲区里"，既没法单测，也会让同一份
控制台给出两种结论 —— 语料里 `rcore-mmap` 和 `rcore-unmap` 证据逐字节相同，结局
一个 completed 一个 panic。`_drive_shell` 剩下的部分（送命令、等提示符、
`stdin_after`）仍然只有静态自检。
