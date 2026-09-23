# 测试

在仓库根目录运行普通测试：

```bash
python -m pytest nodefusion/tests -q
```

测试覆盖 manifest 解析、DWARF 布局、source plan、reader、观察点选择、轨迹解码、
状态重建、覆盖审计、报告数据、调用链、产物写入和内核集成补丁。

## 运行语料

带 `corpus` 标记的用例读取本机 `nodefusion/runs/`。普通测试会跳过这些用例。

```bash
python -m pytest nodefusion/tests -q --run-corpus
```

默认只发现不超过 256 MiB 的轨迹。归档机上验证全部运行记录：

```bash
NF_CORPUS_MAX_TRACE_MIB=0 \
  python -m pytest nodefusion/tests -q --run-corpus
```

## 独立检查脚本

| 脚本 | 检查内容 |
| --- | --- |
| `stress_pagetable.py` | 页表环、损坏项和超大遍历的边界 |
| `fuzz_trace.py` | 截断、位翻转和异常长度下的轨迹解码 |
| `crosscheck_artifacts.py` | `trace.nfb`、`events.jsonl` 与 HTML 内嵌数据的一致性 |

`fuzz_trace.py` 和 `crosscheck_artifacts.py` 当前读取
`/tmp/nf_runs/rcore-ch4`。使用其他录制时修改脚本开头的 `SRC` 或 `RD`。

涉及 xv6 构建、QEMU 启动或 shell 驱动的改动，在 xv6-riscv 源码树上补充端到端运行。
`test_shell_verdict.py` 使用录制的控制台片段验证运行结局。
