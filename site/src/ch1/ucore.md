# uCore 实现

从 [`_entry`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/entry.S) 到 `main`，内核只需要一块可用的栈；完成输出与关机则依靠 SBI。以下代码来自 [uCore 2026A 第一章](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080)。

## 入口与启动栈

[`entry.S`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/entry.S) 的 `_entry` 先把 `sp` 设为 `boot_stack_top`，再调用 `main`。`boot_stack` 与栈顶之间预留 64 KiB。

[`kernel.ld`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/kernel.ld) 将内核起始地址设为 `0x80200000`，各段按页对齐。启动栈位于普通 BSS 之前，因而清零 BSS 不会抹掉正在使用的栈。

## 清零与主函数

[`main.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/main.c) 的 `clean_bss` 清零 `[s_bss, e_bss)`。随后 `main` 调用 `console_init` 并输出各段边界。本章的 `console_init` 为空，字符输出由 SBI 完成。

最后，`main` 执行 `panic("ALL DONE")`，由 `panic` 调用关机函数。本章的 `threadid()` 固定返回 0；进程与线程管理要到后续章节才引入。

## 输出与终止

[`printf.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/printf.c) 逐个处理格式字符，通过 `consputc` 输出。指针格式 `%p` 打印十六进制地址。

[`sbi.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9e6da1f5d27aac35c1bbbac7e7d090f6c82d5080/os/sbi.c) 将服务号放入 `a7`、参数放入 `a0` 等寄存器，再执行 `ecall`。关机服务号为 8。沿着 `printf → consputc → SBI` 和 `panic → shutdown → SBI` 两条路径，可以看到同一套固件接口如何承担输出与关机。

## 运行观察

运行报告中的 ELF 各段边界如下：

| 区域 | 地址区间 |
| --- | --- |
| 代码 | `[0x80200000, 0x80201000)` |
| 只读数据 | `[0x80201000, 0x80202000)` |
| 可写数据边界 | `s_data = e_data = 0x80202000` |
| 启动栈 | `[0x80202000, 0x80212000)` |
| 清零区间 | `s_bss = e_bss = 0x80212000` |

`s_bss` 与 `e_bss` 相等，因此 `clean_bss` 的循环执行零次。进入 `main` 时 `sp = 0x80212000`，正好指向栈顶；调用 `clean_bss` 后，栈指针向低地址移动，为函数调用留出空间。

[查看启动过程](../reports/ucoreos/ch1/2026a/ucore-2026A-ch1-verified.html) · [录制信息](../reports/ucoreos/ch1/2026a/recording.json)
