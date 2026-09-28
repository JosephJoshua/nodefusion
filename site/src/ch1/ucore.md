# uCore 实现

参考实现固定到课程仓库提交 [`9e6da1f`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080)。本章通过入口汇编建立栈，进入 C 主函数，输出内存布局，然后调用 SBI 关机接口。

## 入口与启动栈

[`entry.S`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/entry.S) 的 `_entry` 先把 `sp` 设为 `boot_stack_top`，再调用 `main`。`boot_stack` 与栈顶之间预留 64 KiB。

[`kernel.ld`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/kernel.ld) 将入口放在 `0x80200000`，代码与数据段按 4 KiB 对齐。启动栈排在普通 BSS 之前，`s_bss` 位于启动栈之后。

## 清零与主函数

[`main.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/main.c) 的 `clean_bss` 从 `s_bss` 开始逐字节写零，直到地址达到 `e_bss`。主函数调用它后进入 `console_init`；本章的控制台初始化函数为空，字符输出直接使用 SBI 服务。

`main` 输出问候信息和各段边界，最后执行 `panic("ALL DONE")`。本章 `threadid()` 固定返回 0，该数字是日志标签，并不对应已创建的线程。本章尚无进程表和调度器。

## 输出与终止

[`printf.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/printf.c) 逐个处理格式字符，通过 `consputc` 输出。指针格式 `%p` 打印十六进制地址。

[`sbi.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/sbi.c) 的封装将服务号放入 `a7`，参数放入 `a0` 等寄存器，再执行 `ecall`。关机使用服务号 8。`panic` 宏打印消息后调用 `shutdown`，因而本章的 `ALL DONE` 是参考程序的完成路径。

## 运行观察

记录 `ucore-2026A-ch1-verified` 使用未修改的参考实现。课程检查结果为 PASS。本次 ELF 的布局如下：

| 区域 | 地址区间 |
| --- | --- |
| 代码 | `[0x80200000, 0x80201000)` |
| 只读数据 | `[0x80201000, 0x80202000)` |
| 可写数据边界 | `s_data = e_data = 0x80202000` |
| 启动栈 | `[0x80202000, 0x80212000)` |
| 清零区间 | `s_bss = e_bss = 0x80212000` |

第 10,762,845 条指令处进入 `main`，`sp` 为 `0x80212000`。进入 `clean_bss` 时，`sp` 已减少 16 字节，变为 `0x80211ff0`。

本次清零区间为空。清零函数仍然被调用，其循环条件第一次检查便不成立。第 10,762,866 条指令处进入 `console_init`，随后沿格式化输出路径运行。第 10,930,452 条指令处进入 `shutdown`，此时 `sp` 仍为 `0x80211ff0`。

整个运行执行 10,931,358 条指令，保存 11 份快照与 842 条函数入口事件。录制结果为 `completed`，派生报告保留全部入口事件。分析这些数字时，可以将格式化输出拆成打印函数、逐字符输出与 SBI 调用三个层次。

[打开本次运行报告](../reports/ucoreos/ch1/2026a/ucore-2026A-ch1-verified.html)。在函数调用视图中查找 `main`、`clean_bss`、`printf` 和 `shutdown`，比较一次格式化输出涉及的调用。

<details>
<summary>构建与录制参数</summary>

在参考仓库根目录执行 `python tools/run_lab.py --mode positive`，课程工具完成构建与检查。本次使用 GCC 14.2.0、CMake 3.31.6 和 QEMU 10.2.2。课程检查结果、ELF 校验和与完整命令保存在[录制信息](../reports/ucoreos/ch1/2026a/recording.json)中。

```sh
python -m nodefusion.host.cli record \
  --kernel "$KERNEL_DIR" --kernel-kind ucore \
  --runs "$RUNS_DIR" --name ucore-2026A-ch1-verified \
  --no-build --function-returns --watch-all --profile uniform \
  --snapshots 80 --max-ram-bytes 268435456 --timeout 90 \
  --no-render --event-stream never
```

报告通过 `python -m scripts.regenerate_artifact --run "$RUN_DIR" --out "$REPORT_HTML" --strict` 生成。启动栈边界和入口寄存器由同一 ELF 与完整原始轨迹提取。

</details>

## 源码阅读练习

1. BSS 区间为空时，为什么主函数仍可调用 `clean_bss`？
2. `console_init` 为空，为何后续字符仍能输出？沿 `printf`、`consputc` 和 SBI 封装回答。
3. 日志中的线程编号 0 来自哪里？后续章节需要怎样改变它？
4. 对比 rCore 的退出设备写入与本章 SBI 关机调用，分别指出请求的接收方。
