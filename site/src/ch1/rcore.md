# rCore 实现

第一章的内核从汇编入口进入 Rust 主函数，完成全局变量清零、控制台输出和关机。以下代码取自 [2026A 第一章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/ebb82caa6bec05652a041e613c12a52fde3813f0)。

## 入口与启动栈

处理器从 `_start` 开始执行。[`entry.asm`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/entry.asm) 先把 `sp` 设为 `boot_stack_top`，再调用 `rust_main`。启动栈位于 `.bss.stack`，大小为 64 KiB。

[`linker.ld`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/linker.ld) 把内核入口放在 `0x80200000`，依次排列代码、只读数据、可写数据和 BSS。启动栈位于 BSS 的最前面；`sbss` 标记其后的清零起点。这一布局使内核能够在使用启动栈的同时初始化其余 BSS。

## 清零与主函数

[`clear_bss`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/main.rs) 逐字节清零 `[sbss, ebss)`。`rust_main` 在访问全局状态之前调用它，随后初始化日志，输出问候语和数组 `[1, 2, 3, 4, 5]` 的求和结果。

内核通过链接脚本提供的符号打印各段边界。这里使用的是符号地址，例如 `stext as usize`，而不是调用同名函数。代码、只读数据、可写数据、启动栈和 BSS 分别使用 trace、debug、info、warn、error 级别。

## 输出与终止

格式化输出最终通过 SBI 写到控制台。主函数调用 [`QEMU_EXIT_HANDLE.exit_success()`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/boards/qemu.rs) 向 QEMU 测试设备写入成功退出值。`rust_main` 的返回类型为 `!`；程序不会回到 `_start` 中的 `call` 之后。

## 运行观察

运行报告中，`rust_main` 入口的 `sp` 为 `0x80214000`，正好是启动栈顶。进入 `clear_bss` 时，`sp` 已降至 `0x80213e80`；这段空间属于主函数的调用栈。

本次构建的清零区间为 `[0x80214000, 0x80215000)`，从启动栈顶开始。对照链接脚本和这两个函数入口，就能确定 `clear_bss` 清零时没有覆盖正在使用的栈。

[查看函数调用报告](../reports/rcore/ch1/2026a/rcore-2026A-ch1-verified.html) · [录制数据](../reports/rcore/ch1/2026a/recording.json)
