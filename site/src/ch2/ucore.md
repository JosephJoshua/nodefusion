# uCore 实现

本节分析课程仓库 `ch2-api-impl` 的提交 [`729e1ad`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/729e1ad1632bb639dfe546f34765c0537b503990)。应用测试来自 [`1733f46`](https://github.com/LearningOS/uCore-Tutorial-Test/tree/1733f460c596b013b1c509ad42afa428640783b0)，使用课程提供的测试构建补丁。

## 批次状态与装载

[`loader.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/loader.c) 使用 `app_num` 保存应用数，`app_cur` 保存当前序号，`app_info_ptr` 指向应用位置表。初始化将 `app_cur` 设为 -1；每次 `run_next_app` 先增加序号并移动表指针，再判断批次是否结束。

`load_app` 清零从 `0x80400000` 开始的 `0x20000` 字节，再用 `memmove` 复制选中应用。本版装载函数没有 `fence.i`。这两步之后，`run_next_app` 清零 `trap_page`，准备下一应用的入口和用户栈指针。

应用 0 正在运行时，`app_cur` 的值为 0。当前应用保存在固定执行区域中，其他应用仍是内核映像中的待装载二进制。

## 首次进入用户态

用户栈 `user_stack` 和上下文页 `trap_page` 各有 4 KiB，按页对齐。`run_next_app` 将 `trap_page` 的开头解释为 `struct trapframe`，设置 `epc = 0x80400000` 与 `sp = user_stack + USER_STACK_SIZE`，再调用 `usertrapret`。

[`usertrapret`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/trap.c#L59) 准备下次进入内核时使用的栈地址、处理函数地址和 hart 标识，设置 `sepc` 与用户态返回状态，随后进入 `userret` 汇编。

## 异常入口与上下文

[`trampoline.S`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/trampoline.S) 的 `uservec` 用 `a0` 与 `sscratch` 交换，取得 `trapframe` 地址。它保存用户寄存器，把原用户 `a0` 从 `sscratch` 写入对应字段，再记录 `sepc`。

随后，入口从 `trapframe` 读取 `kernel_sp`、`kernel_trap` 和 `kernel_hartid`，切换到内核栈并调用 `usertrap`。`trapframe` 共 288 字节，包括 31 个通用寄存器和五个内核或控制状态字段。

返回汇编以 `a0` 中的上下文地址恢复寄存器，最后恢复用户 `a0` 并执行 `sret`。本章汇编中的 `satp` 切换与 `sfence.vma` 指令被注释，程序使用裸地址运行。

## 系统调用与返回

[`usertrap`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/trap.c#L19) 对用户系统调用将 `trapframe->epc` 增加 4，再进入 [`syscall`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/syscall.c)。分发器直接读取全局 `trap_page` 中的 `a7` 和参数，调用接口并将结果写入保存的 `a0`。

`sys_write` 接受描述符 1，逐字节输出，成功时返回长度；其他描述符返回 -1。未知系统调用号也返回 -1。缓冲区按地址直接读取，没有用户地址范围检查。C 用户库的 RISC-V 包装函数将 `a0` 作为 `long` 返回，因此寄存器中全一的位模式会被解释为 -1。

处理函数再次调用 `usertrapret`，从更新后的 `epc` 返回用户程序。

## 退出与应用异常

`sys_exit` 输出退出码，调用 `run_next_app`。批次尚有应用时，它启动下一应用；批次结束时，退出路径输出 `ALL DONE` 并调用 `shutdown`。

异常分发单独处理非法指令以及若干未对齐或页异常。其余原因进入默认诊断分支，随后同样装载下一应用。本次向地址零写入产生原因 7，进入默认分支。日志中的 `core dumped.` 是诊断文字，程序没有生成转储文件。

## 栈地址与上下文页

参考实现将 `usertrapret` 的第二个参数设为 `boot_stack_top`，函数内部又加上 `PGSIZE`：

```c
trapframe->kernel_sp = kstack + PGSIZE;
```

本次参考构建的 ELF 给出以下布局：

| 区域或符号 | 地址 |
| --- | --- |
| 启动栈 | `[0x80209000, 0x80219000)` |
| `boot_stack_top` | `0x80219000` |
| `trap_page` | `[0x80219000, 0x8021a000)` |
| `user_stack` | `[0x8021a000, 0x8021b000)` |

于是，异常入口取得的 `kernel_sp` 为 `0x8021a000`。栈向低地址增长，处理函数的调用栈就落在 `trap_page` 内。装载下一应用时，`run_next_app` 又把这整页清零。

第 11,788,381 条指令处，清零 `trap_page` 的 `memset` 入口记录为：目标地址 `0x80219000`，长度 4,096，`sp = 0x80219f70`。正在使用的栈位于清零区间内。随后保存的返回地址被覆盖，第 11,800,681 条指令处出现地址零的取指访问异常。参考构建在第一个应用退出后停滞，`app_cur` 保持 1。

独立修正构建将这行改为 `trapframe->kernel_sp = kstack;`，使用调用者已经传入的启动栈顶。处理栈由此位于上下文页之前，三个普通应用依次结束，退出码为 1234、0、0。

## 运行观察

| 构建与应用 | 结果 | `usertrap` 次数 | 用户 exit 次数 |
| --- | --- | ---: | ---: |
| 原参考构建，三个普通应用 | 第二应用启动前停滞，录制超时 | 1 | 1 |
| 栈地址修正版，同一普通批次 | 三应用结束 | 16 | 3 |
| 栈地址修正版，三个异常应用 | 三应用异常后继续，批次结束 | 3 | 0 |

普通批次包含 `ch2b_exit`、`ch2b_hello_world` 和 `ch2b_power`。修正构建的 16 次用户异常全部是系统调用，包括 13 次 write 和三次 exit。`run_next_app` 进入四次，最后一次检查批次结束。

异常批次的三个应用依次向地址零写入、执行 `sret`、读取 `sstatus`，记录到的异常原因为 7、2、2。每次异常之后都装载下一应用，最后关机。该批次没有用户系统调用，也没有用户 exit。

可分别打开[原参考构建报告](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-reference.html)、[栈地址修正版报告](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-stack-fixed.html)和[异常批次报告](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-faults.html)。先筛选 `usertrap` 与 `memset`，比较入口的栈指针，再查看上下文页中的 `kernel_sp` 和 `epc`。

<details>
<summary>构建与录制参数</summary>

交叉编译器为 GCC 14.2.0，CMake 为 3.31.6，QEMU 为 10.2.2，固件为 OpenSBI 1.7。构建时将 Makefile 的 `AS_SRCS` 改为立即展开，避免生成的应用汇编被重复收集。两份修正构建另有上述栈地址修改。原参考构建的课程检查结果保留为 `FAIL`。

原参考构建使用 `tools/run_lab.py --mode positive` 准备三个普通应用。修正普通批次复用相同的用户二进制，在独立目录执行 `make build LOG=debug`；异常批次将三个第二章异常程序按同一执行地址构建后单独装载。

修正普通批次的录制命令在远程任务的 `tool` 目录执行：

```sh
/home/joseph/nf/venv313/bin/python -m nodefusion.host.cli record \
  --kernel /home/joseph/nf/education-2026A-20260927/ucore-ch2-stack-fixed \
  --kernel-kind ucore --runs /home/joseph/nf/education-2026A-20260927/runs \
  --name ucore-2026A-ch2-stack-fixed --no-build --function-returns --watch-all \
  --profile uniform --snapshots 80 --max-ram-bytes 268435456 \
  --timeout 60 --no-render --event-stream never
```

原参考轨迹包含 1,534,392 条事件，报告保留 150,000 条；两份修正轨迹各有 4,370 和 2,324 条事件，全部保留。正文计数来自完整轨迹。

完整命令、源码补丁和校验和：[原参考构建](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-reference.json)、[普通批次修正构建](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-stack-fixed.json)、[异常批次](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-faults.json)。各报告的同名 `.log` 文件保存串口输出。

</details>

## 源码阅读练习

1. `app_cur` 初值为什么是 -1？`app_info_ptr++` 后相邻两个元素分别表示什么？
2. 用户 `a0` 被用于取得上下文地址后，它原来的值保存在哪里？
3. `usertrapret` 的参数若改为栈区域的起点，`kernel_sp` 应如何计算？需要检查哪些调用者？
4. 根据 ELF 区间判断 `memset` 是否覆盖当前调用栈，再解释修正后首次与后续异常为什么都安全。
